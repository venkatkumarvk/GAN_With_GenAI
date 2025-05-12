# helper_functions.py
import os
import io
import json
import base64
import fitz  # PyMuPDF
import pandas as pd
import tempfile
from datetime import datetime
import gc
from azure.storage.blob import BlobServiceClient, ContentSettings
import streamlit as st

def load_config(config_path="config.json"):
    """
    Load configuration from a JSON file.
    """
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return config
    except Exception as e:
        st.error(f"Error loading configuration: {str(e)}")
        st.info("Please ensure a valid config.json file is present.")
        return None

def get_blob_service_client(connection_string):
    """
    Get Azure Blob Storage client.
    """
    try:
        return BlobServiceClient.from_connection_string(connection_string)
    except Exception as e:
        st.error(f"Error connecting to Azure Blob Storage: {str(e)}")
        st.info("Please check your connection string in the config file.")
        return None

def list_blobs_with_prefix(blob_service_client, container_name, prefix):
    """
    List blobs with a specific prefix.
    """
    try:
        container_client = blob_service_client.get_container_client(container_name)
        blob_list = container_client.list_blobs(name_starts_with=prefix)
        return list(blob_list)
    except Exception as e:
        st.error(f"Error listing blobs: {str(e)}")
        return []

def download_blob_content(blob_service_client, container_name, blob_name):
    """
    Download blob content.
    """
    try:
        container_client = blob_service_client.get_container_client(container_name)
        blob_client = container_client.get_blob_client(blob_name)
        
        # Download the blob content
        download_stream = blob_client.download_blob()
        blob_content = download_stream.readall()
        
        return blob_content
    except Exception as e:
        st.error(f"Error downloading blob {blob_name}: {str(e)}")
        return None

def upload_blob_content(blob_service_client, container_name, blob_name, content, content_type):
    """
    Upload content to a blob.
    """
    try:
        container_client = blob_service_client.get_container_client(container_name)
        
        # Create container if it doesn't exist
        if not container_client.exists():
            container_client.create_container()
        
        # Get blob client
        blob_client = container_client.get_blob_client(blob_name)
        
        # Upload content
        content_settings = ContentSettings(content_type=content_type)
        blob_client.upload_blob(content, overwrite=True, content_settings=content_settings)
        
        return True, blob_client.url
    except Exception as e:
        st.error(f"Error uploading blob {blob_name}: {str(e)}")
        return False, str(e)

def get_matching_pdf_and_csv(source_blobs, processed_blobs):
    """
    Find matching PDF and CSV files based on names.
    """
    matches = []
    processed_dict = {}
    
    # Create a dictionary of processed files
    for blob in processed_blobs:
        name = blob.name.split('/')[-1]
        base_name = os.path.splitext(name)[0]
        processed_dict[base_name] = blob
    
    # Find matching source files
    for source_blob in source_blobs:
        name = source_blob.name.split('/')[-1]
        base_name = os.path.splitext(name)[0]
        
        if base_name in processed_dict:
            matches.append({
                "source": source_blob,
                "processed": processed_dict[base_name]
            })
    
    return matches

def render_pdf_preview(pdf_content):
    """
    Render a preview of the first page of a PDF file.
    """
    try:
        # Create a temporary file
        pdf_io = io.BytesIO(pdf_content)
        
        # Open the PDF
        with fitz.open(stream=pdf_io, filetype="pdf") as doc:
            if len(doc) > 0:
                # Get the first page
                page = doc.load_page(0)
                
                # Render the page
                zoom = 1.5
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                
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
        # Force garbage collection
        gc.collect()

def convert_pdf_to_base64(pdf_content):
    """
    Convert PDF content to base64 for embedding in HTML.
    """
    try:
        base64_pdf = base64.b64encode(pdf_content).decode('utf-8')
        return base64_pdf
    except Exception as e:
        st.error(f"Error converting PDF to base64: {str(e)}")
        return None

def display_pdf_viewer(base64_pdf, height=500):
    """
    Display a PDF viewer in the Streamlit app.
    """
    if not base64_pdf:
        st.error("No PDF data available to display")
        return
        
    # Create the HTML with PDF.js
    pdf_display = f"""
    <iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="{height}" 
    type="application/pdf"></iframe>
    """
    
    # Display the PDF
    st.markdown(pdf_display, unsafe_allow_html=True)

def parse_csv_content(csv_content):
    """
    Parse CSV content into a pandas DataFrame.
    """
    try:
        # Convert bytes to string
        if isinstance(csv_content, bytes):
            csv_text = csv_content.decode('utf-8')
        else:
            csv_text = csv_content
        
        # Parse CSV
        df = pd.read_csv(io.StringIO(csv_text))
        return df
    except Exception as e:
        st.error(f"Error parsing CSV content: {str(e)}")
        return None

def update_csv_with_edits(csv_df, edits):
    """
    Update CSV DataFrame with manual edits.
    """
    try:
        # Make a copy of the DataFrame
        edited_df = csv_df.copy()
        
        # Apply edits
        for row_idx, field, value in edits:
            if field in edited_df.columns and row_idx < len(edited_df):
                edited_df.at[row_idx, field] = value
                # Also add an edit indicator column if it doesn't exist
                if "Manual_Edit" not in edited_df.columns:
                    edited_df["Manual_Edit"] = "N"
                edited_df.at[row_idx, "Manual_Edit"] = "Y"
                
                # Add edit timestamp if it doesn't exist
                if "Edit_Timestamp" not in edited_df.columns:
                    edited_df["Edit_Timestamp"] = ""
                edited_df.at[row_idx, "Edit_Timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return edited_df
    except Exception as e:
        st.error(f"Error updating CSV with edits: {str(e)}")
        return csv_df  # Return original if update fails
