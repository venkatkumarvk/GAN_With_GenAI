import os
import io
import json
import base64
import tempfile
import gc
import fitz  # PyMuPDF
import pandas as pd
import streamlit as st
from datetime import datetime
from azure.storage.blob import BlobServiceClient, ContentSettings

def load_config():
    """
    Load configuration from config.json file.
    """
    try:
        # First check if config.json exists in the current directory
        if os.path.exists("config.json"):
            with open("config.json", "r") as f:
                config = json.load(f)
            return config
        else:
            st.error("config.json file not found. Please create one with your Azure Blob Storage settings.")
            st.stop()
    except Exception as e:
        st.error(f"Error loading configuration: {e}")
        st.stop()

def get_blob_service_client(config):
    """
    Initialize the Azure Blob Storage client from config.
    """
    try:
        connection_string = config.get("azure_storage_connection_string")
        if not connection_string:
            st.error("Azure Storage connection string not found in config.json")
            st.stop()
            
        return BlobServiceClient.from_connection_string(connection_string)
    except Exception as e:
        st.error(f"Error connecting to Azure Blob Storage: {e}")
        st.stop()

def list_blobs_by_folder(blob_service_client, container_name, folder_prefix):
    """
    List all blobs in a specific folder within a container.
    """
    try:
        container_client = blob_service_client.get_container_client(container_name)
        
        # Filter blobs by folder prefix
        blobs = list(container_client.list_blobs(name_starts_with=folder_prefix))
        
        # Sort blobs by name
        blobs = sorted(blobs, key=lambda x: x.name)
        
        return blobs
    except Exception as e:
        st.error(f"Error listing blobs in {folder_prefix}: {e}")
        return []

def create_blob_dataframe(blobs, folder_prefix):
    """
    Create a DataFrame from blob list.
    """
    data = []
    for blob in blobs:
        # Remove folder prefix to get just the filename
        name = blob.name.replace(folder_prefix, '')
        
        # Skip if this is a folder
        if not name or name.endswith('/'):
            continue
            
        # Add to data
        data.append({
            "Filename": name,
            "Size (KB)": round(blob.size / 1024, 2),
            "Last Modified": blob.last_modified,
            "Full Path": blob.name
        })
    
    if data:
        return pd.DataFrame(data)
    else:
        return pd.DataFrame(columns=["Filename", "Size (KB)", "Last Modified", "Full Path"])

def download_blob_to_memory(blob_service_client, container_name, blob_name):
    """
    Download a blob to memory.
    """
    try:
        container_client = blob_service_client.get_container_client(container_name)
        blob_client = container_client.get_blob_client(blob_name)
        
        # Download the blob content
        download_stream = blob_client.download_blob()
        content = download_stream.readall()
        
        return content
    except Exception as e:
        st.error(f"Error downloading blob {blob_name}: {e}")
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
                
                # Render the page to an image
                zoom = 1.5  # Reduced zoom factor to save memory
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
        st.error(f"Error rendering PDF preview: {e}")
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
        st.error(f"Error converting PDF to base64: {e}")
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

def load_csv_from_blob(blob_service_client, container_name, blob_name):
    """
    Load a CSV file from a blob into a pandas DataFrame.
    """
    try:
        # Download blob content
        blob_content = download_blob_to_memory(blob_service_client, container_name, blob_name)
        
        if blob_content is None:
            return None
            
        # Convert to BytesIO and read with pandas
        content_stream = io.BytesIO(blob_content)
        df = pd.read_csv(content_stream)
        
        return df
    except Exception as e:
        st.error(f"Error loading CSV from {blob_name}: {e}")
        return None

def upload_to_blob_storage(blob_service_client, container_name, blob_name, data, content_type):
    """
    Upload data to Azure Blob Storage.
    """
    try:
        # Get the blob client
        container_client = blob_service_client.get_container_client(container_name)
        
        # Create the container if it doesn't exist
        if not container_client.exists():
            container_client.create_container()
        
        # Upload blob
        blob_client = container_client.get_blob_client(blob_name)
        
        # Set content settings
        content_settings = ContentSettings(content_type=content_type)
        
        # Upload the file
        blob_client.upload_blob(data, overwrite=True, content_settings=content_settings)
        
        return True, blob_client.url
    except Exception as e:
        return False, str(e)

def update_edited_data(filename, page_num, field, new_value):
    """
    Updates the edited data in the session state.
    """
    # Initialize the edited data structure if it doesn't exist
    if 'edited_data' not in st.session_state:
        st.session_state.edited_data = {}
    
    # Create the nested structure if it doesn't exist
    if filename not in st.session_state.edited_data:
        st.session_state.edited_data[filename] = {}
    
    if page_num not in st.session_state.edited_data[filename]:
        st.session_state.edited_data[filename][page_num] = {}
    
    # Store the edited value
    st.session_state.edited_data[filename][page_num][field] = new_value
    
    # Track edit timestamp
    if 'edit_timestamps' not in st.session_state:
        st.session_state.edit_timestamps = {}
    
    if filename not in st.session_state.edit_timestamps:
        st.session_state.edit_timestamps[filename] = {}
    
    if page_num not in st.session_state.edit_timestamps[filename]:
        st.session_state.edit_timestamps[filename][page_num] = {}
    
    # Store timestamp
    st.session_state.edit_timestamps[filename][page_num][field] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def apply_edits_to_csv(df, edited_data, timestamps):
    """
    Apply manual edits to the DataFrame and add edit tracking fields.
    """
    if not edited_data:
        return df
    
    # Create a copy to avoid modifying the original
    edited_df = df.copy()
    
    # Add timestamp and edit tracking columns if they don't exist
    if "Edit_Timestamp" not in edited_df.columns:
        edited_df["Edit_Timestamp"] = ""
    if "Manually_Edited_Fields" not in edited_df.columns:
        edited_df["Manually_Edited_Fields"] = ""
    if "Manual_Edit" not in edited_df.columns:
        edited_df["Manual_Edit"] = "N"
    
    # Apply the edits
    for filename, pages in edited_data.items():
        for page_num, fields in pages.items():
            # Convert page_num to int if it's a string
            if isinstance(page_num, str):
                page_num = int(page_num)
            
            # Find matching rows in the DataFrame
            rows = edited_df[(edited_df["Filename"] == filename) & (edited_df["Page"] == page_num)]
            
            if not rows.empty:
                row_idx = rows.index[0]
                
                # Apply edits to each field
                edited_field_names = []
                latest_timestamp = ""
                
                for field, new_value in fields.items():
                    if field in edited_df.columns:
                        # Update the value
                        edited_df.at[row_idx, field] = new_value
                        edited_field_names.append(f"{field}: {new_value}")
                        
                        # Get timestamp if available
                        if (timestamps and filename in timestamps and page_num in timestamps[filename] 
                            and field in timestamps[filename][page_num]):
                            field_timestamp = timestamps[filename][page_num][field]
                            if not latest_timestamp or field_timestamp > latest_timestamp:
                                latest_timestamp = field_timestamp
                
                # Update edit tracking fields
                if edited_field_names:
                    edited_df.at[row_idx, "Manually_Edited_Fields"] = "; ".join(edited_field_names)
                    edited_df.at[row_idx, "Edit_Timestamp"] = latest_timestamp
                    edited_df.at[row_idx, "Manual_Edit"] = "Y"
    
    return edited_df

def create_bulk_upload_csv(high_confidence_df, low_confidence_df):
    """
    Combine high and low confidence DataFrames for bulk upload.
    """
    if high_confidence_df is not None and not high_confidence_df.empty:
        high_confidence_df["Confidence_Level"] = "High"
    
    if low_confidence_df is not None and not low_confidence_df.empty:
        low_confidence_df["Confidence_Level"] = "Low"
    
    # Combine the DataFrames
    combined_df = pd.concat([high_confidence_df, low_confidence_df], ignore_index=True)
    
    # Ensure all columns are present
    required_columns = ["Filename", "Page", "Confidence_Level", "Manual_Edit", 
                        "Manually_Edited_Fields", "Edit_Timestamp"]
    
    for col in required_columns:
        if col not in combined_df.columns:
            combined_df[col] = ""
    
    return combined_df

def upload_edited_results(blob_service_client, config, edited_df, confidence_level):
    """
    Upload edited results to the output container.
    """
    try:
        # Get output container from config
        output_container = config.get("output_container", "pdf-extraction-results-final")
        
        # Determine folder based on confidence
        folder_prefix = f"{confidence_level.lower()}_confidence/"
        
        # Create CSV data
        csv_data = edited_df.to_csv(index=False)
        
        # Generate timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create blob name with folder prefix
        blob_name = f"{folder_prefix}edited_results_{timestamp}.csv"
        
        # Upload to blob storage
        success, url = upload_to_blob_storage(
            blob_service_client,
            output_container,
            blob_name,
            csv_data.encode('utf-8'),
            "text/csv"
        )
        
        if success:
            return True, url
        else:
            return False, url
            
    except Exception as e:
        return False, str(e)
