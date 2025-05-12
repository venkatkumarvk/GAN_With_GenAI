import os
import io
import json
import base64
import tempfile
import pandas as pd
import fitz  # PyMuPDF
import streamlit as st
from datetime import datetime
import gc
from azure.storage.blob import BlobServiceClient

def load_config(config_path="config.json"):
    """
    Load configuration from config.json file
    """
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return config
    except Exception as e:
        st.error(f"Error loading configuration: {str(e)}")
        return None

def get_blob_service_client(connection_string):
    """
    Get the Azure Blob Storage client
    """
    try:
        return BlobServiceClient.from_connection_string(connection_string)
    except Exception as e:
        st.error(f"Error connecting to Azure Blob Storage: {str(e)}")
        return None

def list_folders_in_container(blob_service_client, container_name, prefix=""):
    """
    List folders in a container
    """
    try:
        container_client = blob_service_client.get_container_client(container_name)
        
        # Get blobs with a prefix and extract folder names
        blobs = container_client.list_blobs(name_starts_with=prefix)
        
        folders = set()
        for blob in blobs:
            # Extract folder path
            name = blob.name
            if prefix:
                # Remove the prefix from the name
                if name.startswith(prefix):
                    name = name[len(prefix):]
            
            # Extract folder name
            if '/' in name:
                folder = name.split('/')[0]
                if folder:
                    folders.add(folder)
        
        return sorted(list(folders))
    except Exception as e:
        st.error(f"Error listing folders in container {container_name}: {str(e)}")
        return []

def list_blobs_in_folder(blob_service_client, container_name, folder_path):
    """
    List blobs in a specific folder
    """
    try:
        container_client = blob_service_client.get_container_client(container_name)
        
        # Ensure folder path ends with '/'
        if folder_path and not folder_path.endswith('/'):
            folder_path += '/'
        
        # Get blobs with the folder prefix
        blobs = container_client.list_blobs(name_starts_with=folder_path)
        
        # Organize blobs by file type
        pdf_blobs = []
        csv_blobs = []
        
        for blob in blobs:
            # Skip if it's a subfolder
            name = blob.name
            if name.endswith('/'):
                continue
                
            # Skip the folder prefix itself
            if name == folder_path:
                continue
                
            # Only include files directly in this folder (not in subfolders)
            name_without_prefix = name[len(folder_path):]
            if '/' in name_without_prefix:
                continue
                
            # Categorize by file type
            if name.lower().endswith('.pdf'):
                pdf_blobs.append(blob.name)
            elif name.lower().endswith('.csv'):
                csv_blobs.append(blob.name)
        
        return pdf_blobs, csv_blobs
    except Exception as e:
        st.error(f"Error listing blobs in folder {folder_path}: {str(e)}")
        return [], []

def download_blob_to_memory(blob_service_client, container_name, blob_name):
    """
    Download a blob to memory
    """
    try:
        container_client = blob_service_client.get_container_client(container_name)
        blob_client = container_client.get_blob_client(blob_name)
        
        # Download the blob content
        download_stream = blob_client.download_blob()
        content = download_stream.readall()
        
        return content
    except Exception as e:
        st.error(f"Error downloading blob {blob_name}: {str(e)}")
        return None

def upload_blob(blob_service_client, container_name, blob_name, data, content_type):
    """
    Upload data to Azure Blob Storage
    """
    try:
        # Get the container client
        container_client = blob_service_client.get_container_client(container_name)
        
        # Create the container if it doesn't exist
        if not container_client.exists():
            container_client.create_container()
        
        # Get the blob client
        blob_client = container_client.get_blob_client(blob_name)
        
        # Upload the data
        blob_client.upload_blob(data, overwrite=True, content_type=content_type)
        
        return True, blob_client.url
    except Exception as e:
        st.error(f"Error uploading blob {blob_name}: {str(e)}")
        return False, str(e)

def read_csv_from_blob(blob_service_client, container_name, blob_name):
    """
    Read a CSV file from blob storage into a pandas DataFrame
    """
    try:
        # Download the blob content
        content = download_blob_to_memory(blob_service_client, container_name, blob_name)
        
        if content:
            # Create a BytesIO object from the content
            csv_file = io.BytesIO(content)
            
            # Read the CSV into a DataFrame
            df = pd.read_csv(csv_file)
            
            return df
        else:
            st.error(f"Could not download CSV file: {blob_name}")
            return None
    except Exception as e:
        st.error(f"Error reading CSV from blob {blob_name}: {str(e)}")
        return None

def render_pdf_preview(pdf_content):
    """
    Render a preview of the first page of a PDF file.
    """
    tmp_path = None
    try:
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(pdf_content)
            tmp_path = tmp_file.name
            
        # Open the PDF and get the first page as an image
        with fitz.open(tmp_path) as doc:
            if len(doc) > 0:
                # Get the first page
                page = doc.load_page(0)
                
                # Render the page to an image (with reasonable resolution)
                zoom = 1.5
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                
                # Convert to an image
                img_bytes = pix.tobytes()
                
                # Return the image
                return img_bytes
            else:
                st.warning("PDF appears to be empty")
                return None
                
    except Exception as e:
        st.error(f"Error rendering PDF preview: {str(e)}")
        return None
    finally:
        # Clean up temporary file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception as cleanup_error:
                st.warning(f"Could not remove temporary preview file: {cleanup_error}")
        # Force garbage collection
        gc.collect()

def convert_pdf_to_base64(pdf_content):
    """
    Convert PDF content to base64 for embedding in HTML.
    """
    try:
        # Encode to base64
        base64_pdf = base64.b64encode(pdf_content).decode('utf-8')
        return base64_pdf
    except Exception as e:
        st.error(f"Error converting PDF to base64: {str(e)}")
        return None

def display_pdf_viewer(base64_pdf, height=500):
    """
    Display a PDF viewer in the Streamlit app using base64 encoded PDF.
    """
    if not base64_pdf:
        st.error("No PDF data available to display")
        return
        
    # Create the HTML with PDF.js for better viewing
    pdf_display = f"""
    <iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="{height}" 
    type="application/pdf"></iframe>
    """
    
    # Display the PDF
    st.markdown(pdf_display, unsafe_allow_html=True)

def parse_filename_components(filename):
    """
    Parse components from the filename (like invoice number, total, etc.)
    """
    try:
        # Remove file extension
        base_name = os.path.splitext(filename)[0]
        
        # Split by underscore
        parts = base_name.split('_')
        
        if len(parts) >= 4:
            # Assuming format is base_invoicenumber_total_timestamp
            base = parts[0]
            invoice_number = parts[1]
            total = parts[2]
            timestamp = '_'.join(parts[3:])  # Join remaining parts as timestamp
            
            return {
                "base": base,
                "invoice_number": invoice_number,
                "total": total,
                "timestamp": timestamp
            }
        else:
            # Not enough parts, return just the filename
            return {
                "base": base_name,
                "invoice_number": "",
                "total": "",
                "timestamp": ""
            }
    except Exception as e:
        st.warning(f"Error parsing filename components: {str(e)}")
        return {
            "base": os.path.splitext(filename)[0],
            "invoice_number": "",
            "total": "",
            "timestamp": ""
        }

def match_source_and_processed_files(pdf_files, csv_files):
    """
    Match source PDF files with their processed CSV files
    """
    matched_files = []
    
    for pdf_file in pdf_files:
        pdf_name = os.path.basename(pdf_file)
        pdf_base = os.path.splitext(pdf_name)[0]
        
        # Find matching CSV files
        matching_csvs = []
        for csv_file in csv_files:
            csv_name = os.path.basename(csv_file)
            
            # Check if the CSV file name contains the PDF base name
            if pdf_base in csv_name:
                matching_csvs.append(csv_file)
        
        # Add to matched files
        matched_files.append({
            "pdf_file": pdf_file,
            "pdf_name": pdf_name,
            "matching_csvs": matching_csvs
        })
    
    return matched_files

def update_extraction_data(df, field, page, new_value):
    """
    Update extraction data in a DataFrame
    """
    try:
        # Find the row for the given page
        mask = df['Page'] == page
        
        if mask.any():
            # Update the field value
            df.loc[mask, field] = new_value
            
            # Update the Manual_Edit column
            df.loc[mask, 'Manual_Edit'] = 'Y'
            
            # Update the Edit_Timestamp
            df.loc[mask, 'Edit_Timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Update the Manually_Edited_Fields column
            current_edited_fields = df.loc[mask, 'Manually_Edited_Fields'].iloc[0]
            if pd.isna(current_edited_fields) or current_edited_fields == "":
                df.loc[mask, 'Manually_Edited_Fields'] = f"{field}: {new_value}"
            else:
                df.loc[mask, 'Manually_Edited_Fields'] = f"{current_edited_fields}; {field}: {new_value}"
            
            # Update Original_Values if not already set
            current_original_values = df.loc[mask, 'Original_Values'].iloc[0]
            original_value = df.loc[mask, field].iloc[0]
            if pd.isna(current_original_values) or current_original_values == "":
                df.loc[mask, 'Original_Values'] = f"{field}: {original_value}"
            elif f"{field}:" not in current_original_values:
                df.loc[mask, 'Original_Values'] = f"{current_original_values}; {field}: {original_value}"
            
            return True
        else:
            st.warning(f"Page {page} not found in the data")
            return False
    except Exception as e:
        st.error(f"Error updating extraction data: {str(e)}")
        return False
