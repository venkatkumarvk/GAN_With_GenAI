import os
import json
import io
import base64
import fitz  # PyMuPDF
import pandas as pd
import gc
import tempfile
import zipfile
from datetime import datetime
from azure.storage.blob import BlobServiceClient, ContentSettings

def load_config():
    """
    Load configuration from config.json file.
    """
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        return config
    except Exception as e:
        print(f"Error loading configuration: {e}")
        return None

def get_blob_service_client(connection_string):
    """
    Get Azure Blob Storage client.
    """
    try:
        return BlobServiceClient.from_connection_string(connection_string)
    except Exception as e:
        print(f"Error creating blob service client: {e}")
        return None

def list_blobs_in_folder(blob_service_client, container_name, folder_path):
    """
    List all blobs in a specific folder.
    """
    blobs = []
    try:
        container_client = blob_service_client.get_container_client(container_name)
        blob_list = container_client.list_blobs(name_starts_with=folder_path)
        for blob in blob_list:
            blobs.append(blob.name)
    except Exception as e:
        print(f"Error listing blobs: {e}")
    return blobs

def download_blob_to_memory(blob_service_client, container_name, blob_name):
    """
    Download a blob to memory.
    """
    try:
        container_client = blob_service_client.get_container_client(container_name)
        blob_client = container_client.get_blob_client(blob_name)
        download_stream = blob_client.download_blob()
        return download_stream.readall()
    except Exception as e:
        print(f"Error downloading blob {blob_name}: {e}")
        return None

def parse_csv_from_blob(blob_service_client, container_name, blob_name):
    """
    Download and parse a CSV file from blob storage.
    """
    try:
        # Download the CSV content
        csv_content = download_blob_to_memory(blob_service_client, container_name, blob_name)
        if csv_content:
            # Create a DataFrame
            csv_io = io.BytesIO(csv_content)
            df = pd.read_csv(csv_io)
            return df
        return None
    except Exception as e:
        print(f"Error parsing CSV file {blob_name}: {e}")
        return None

def get_pdf_preview(blob_service_client, container_name, blob_name):
    """
    Get a preview image of the first page of a PDF.
    """
    try:
        # Download the PDF
        pdf_content = download_blob_to_memory(blob_service_client, container_name, blob_name)
        if not pdf_content:
            return None
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(pdf_content)
            tmp_path = tmp_file.name
        
        try:
            # Open the PDF and get the first page
            with fitz.open(tmp_path) as doc:
                if len(doc) > 0:
                    page = doc.load_page(0)
                    zoom = 1.5
                    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                    img_bytes = pix.tobytes()
                    return img_bytes
                return None
        finally:
            # Clean up the temporary file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    except Exception as e:
        print(f"Error getting PDF preview: {e}")
        return None

def convert_pdf_to_base64(blob_service_client, container_name, blob_name):
    """
    Convert a PDF from blob storage to base64 for embedding in HTML.
    """
    try:
        pdf_content = download_blob_to_memory(blob_service_client, container_name, blob_name)
        if pdf_content:
            base64_pdf = base64.b64encode(pdf_content).decode('utf-8')
            return base64_pdf
        return None
    except Exception as e:
        print(f"Error converting PDF to base64: {e}")
        return None

def extract_filename_without_path(blob_name):
    """
    Extract filename without the path.
    """
    return blob_name.split('/')[-1]

def update_blob_content(blob_service_client, container_name, blob_name, content, content_type):
    """
    Update blob content.
    """
    try:
        container_client = blob_service_client.get_container_client(container_name)
        blob_client = container_client.get_blob_client(blob_name)
        
        # Set content settings
        content_settings = ContentSettings(content_type=content_type)
        
        # Upload the content
        blob_client.upload_blob(content, overwrite=True, content_settings=content_settings)
        return True
    except Exception as e:
        print(f"Error updating blob {blob_name}: {e}")
        return False

def update_csv_in_blob(blob_service_client, container_name, blob_name, updated_df):
    """
    Update a CSV file in blob storage.
    """
    try:
        # Convert DataFrame to CSV
        csv_content = updated_df.to_csv(index=False).encode('utf-8')
        
        # Update the blob
        return update_blob_content(blob_service_client, container_name, blob_name, csv_content, 'text/csv')
    except Exception as e:
        print(f"Error updating CSV in blob {blob_name}: {e}")
        return False

def has_high_confidence(csv_data, threshold=95.0):
    """
    Determine if all fields in CSV data have confidence scores at or above threshold.
    """
    try:
        # Check if DataFrame contains confidence columns
        confidence_cols = [col for col in csv_data.columns if 'Confidence' in col]
        
        if not confidence_cols:
            return False
        
        # Check if all confidence values are above threshold
        for col in confidence_cols:
            # Convert to numeric, with NaN for non-numeric values
            csv_data[col] = pd.to_numeric(csv_data[col], errors='coerce')
            
            # Replace NaN with 0
            csv_data[col] = csv_data[col].fillna(0)
            
            # Check if any value is below threshold
            if (csv_data[col] < threshold).any():
                return False
        
        return True
    except Exception as e:
        print(f"Error checking confidence: {e}")
        return False

def create_zip_from_blobs(blob_service_client, container_name, blob_names):
    """
    Create a ZIP file containing multiple blobs.
    """
    try:
        # Create a BytesIO object to store the ZIP
        zip_buffer = io.BytesIO()
        
        # Create a ZIP file
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for blob_name in blob_names:
                # Download the blob
                blob_content = download_blob_to_memory(blob_service_client, container_name, blob_name)
                if blob_content:
                    # Extract filename without path
                    filename = extract_filename_without_path(blob_name)
                    
                    # Add to ZIP
                    zip_file.writestr(filename, blob_content)
        
        # Reset buffer position
        zip_buffer.seek(0)
        return zip_buffer
    except Exception as e:
        print(f"Error creating ZIP from blobs: {e}")
        return None

def apply_edits_to_csv(original_csv, edits):
    """
    Apply edits to a CSV DataFrame.
    
    Parameters:
    - original_csv: Original DataFrame
    - edits: Dictionary of edits {row_index: {column_name: new_value}}
    
    Returns:
    - Updated DataFrame
    """
    try:
        # Create a copy to avoid modifying the original
        updated_csv = original_csv.copy()
        
        # Apply edits
        for row_idx, column_edits in edits.items():
            for column, new_value in column_edits.items():
                updated_csv.at[int(row_idx), column] = new_value
                
                # If editing a field value, update the confidence
                if not column.endswith('Confidence') and column + ' Confidence' in updated_csv.columns:
                    updated_csv.at[int(row_idx), column + ' Confidence'] = 100.0
                    
                # Add a marker for manual edits
                if 'Manual_Edit' in updated_csv.columns:
                    updated_csv.at[int(row_idx), 'Manual_Edit'] = 'Y'
                else:
                    updated_csv['Manual_Edit'] = 'N'
                    updated_csv.at[int(row_idx), 'Manual_Edit'] = 'Y'
        
        return updated_csv
    except Exception as e:
        print(f"Error applying edits to CSV: {e}")
        return original_csv

def get_csv_summary(csv_data):
    """
    Get a summary of a CSV DataFrame.
    """
    try:
        # Get basic info
        num_rows = len(csv_data)
        
        # Get confidence stats if available
        confidence_stats = {}
        confidence_cols = [col for col in csv_data.columns if 'Confidence' in col]
        
        for col in confidence_cols:
            # Convert to numeric
            csv_data[col] = pd.to_numeric(csv_data[col], errors='coerce')
            
            field_name = col.replace(' Confidence', '')
            avg_confidence = csv_data[col].mean()
            min_confidence = csv_data[col].min()
            max_confidence = csv_data[col].max()
            
            confidence_stats[field_name] = {
                'avg': avg_confidence,
                'min': min_confidence,
                'max': max_confidence
            }
        
        # Check for edited fields
        edited_rows = 0
        if 'Manual_Edit' in csv_data.columns:
            edited_rows = (csv_data['Manual_Edit'] == 'Y').sum()
        
        return {
            'num_rows': num_rows,
            'confidence_stats': confidence_stats,
            'edited_rows': edited_rows
        }
    except Exception as e:
        print(f"Error getting CSV summary: {e}")
        return None
