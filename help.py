# helper_functions.py
import os
import io
import json
import base64
import tempfile
import fitz  # PyMuPDF
import pandas as pd
from datetime import datetime
import gc
from azure.storage.blob import BlobServiceClient
from openai import AzureOpenAI
import streamlit as st

# Load configuration from a JSON file
def load_config(config_path="config.json"):
    """Load configuration from JSON file."""
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
        return config
    except Exception as e:
        st.error(f"Error loading configuration: {str(e)}")
        return None

# Initialize Azure Blob Storage client
def get_blob_service_client(connection_string):
    """Get Azure Blob Storage client."""
    try:
        return BlobServiceClient.from_connection_string(connection_string)
    except Exception as e:
        st.error(f"Error initializing Blob Storage client: {str(e)}")
        return None

# Initialize Azure OpenAI client
def get_openai_client(endpoint, api_key):
    """Get Azure OpenAI client."""
    try:
        return AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version="2025-03-01-preview"  # Using latest version with batch support
        )
    except Exception as e:
        st.error(f"Error initializing OpenAI client: {str(e)}")
        return None

# List blobs in a container with a specific prefix
def list_blobs_with_prefix(blob_service_client, container_name, prefix=""):
    """List all blobs with given prefix in the container."""
    try:
        container_client = blob_service_client.get_container_client(container_name)
        blobs = container_client.list_blobs(name_starts_with=prefix)
        return list(blobs)
    except Exception as e:
        st.error(f"Error listing blobs: {str(e)}")
        return []

# Download blob to memory
def download_blob_to_memory(blob_service_client, container_name, blob_name):
    """Download a blob to memory."""
    try:
        container_client = blob_service_client.get_container_client(container_name)
        blob_client = container_client.get_blob_client(blob_name)
        download_stream = blob_client.download_blob()
        content = download_stream.readall()
        return content
    except Exception as e:
        st.error(f"Error downloading blob {blob_name}: {str(e)}")
        return None

# Convert PDF content to base64
def convert_pdf_to_base64(pdf_content):
    """Convert PDF content to base64 for embedding in HTML."""
    try:
        if hasattr(pdf_content, 'getvalue'):
            pdf_bytes = pdf_content.getvalue()
        else:
            pdf_bytes = pdf_content

        base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
        return base64_pdf
    except Exception as e:
        st.error(f"Error converting PDF to base64: {str(e)}")
        return None

# Display PDF viewer
def display_pdf_viewer(base64_pdf, height=500):
    """Display a PDF viewer using base64 encoded PDF."""
    if not base64_pdf:
        st.error("No PDF data available to display")
        return

    pdf_display = f"""
    <iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="{height}"
    type="application/pdf"></iframe>
    """

    st.markdown(pdf_display, unsafe_allow_html=True)

# Load CSV from blob storage
def load_csv_from_blob(blob_service_client, container_name, blob_name):
    """Load CSV from blob storage into a pandas DataFrame."""
    try:
        blob_content = download_blob_to_memory(blob_service_client, container_name, blob_name)
        if blob_content:
            return pd.read_csv(io.BytesIO(blob_content))
        else:
            return None
    except Exception as e:
        st.error(f"Error loading CSV from blob: {str(e)}")
        return None

# Upload to blob storage
def upload_to_blob_storage(blob_service_client, container_name, blob_name, data, content_type):
    """Upload data to Azure Blob Storage."""
    try:
        container_client = blob_service_client.get_container_client(container_name)

        # Create the container if it doesn't exist
        if not container_client.exists():
            container_client.create_container()

        # Upload blob
        blob_client = container_client.get_blob_client(blob_name)

        # Upload the file
        blob_client.upload_blob(data, overwrite=True)

        return True, blob_client.url
    except Exception as e:
        st.error(f"Error uploading to blob: {str(e)}")
        return False, str(e)

# Extract filename from blob path
def get_filename_from_blob_path(blob_path):
    """Extract filename from a blob path."""
    return blob_path.split('/')[-1] if '/' in blob_path else blob_path

# Match source and processed files
def match_source_and_processed_files(source_blobs, processed_blobs):
    """Match source PDFs with their processed CSV results."""
    source_filenames = {get_filename_from_blob_path(blob.name).split('.')[0]: blob.name for blob in source_blobs}
    processed_filenames = {get_filename_from_blob_path(blob.name).split('.')[0]: blob.name for blob in processed_blobs}

    matched_files = []
    for base_name in set(source_filenames.keys()) & set(processed_filenames.keys()):
        matched_files.append({
            "base_name": base_name,
            "source_blob": source_filenames[base_name],
            "processed_blob": processed_filenames[base_name]
        })

    return matched_files

# Apply edits to CSV
def apply_edits_to_csv(csv_df, edited_data):
    """Apply edits to a CSV DataFrame."""
    for idx, edits in edited_data.items():
        for col, value in edits.items():
            csv_df.at[int(idx), col] = value
    return csv_df

# Get total number of pages in a PDF
def get_pdf_page_count(pdf_content):
    """Get the total number of pages in a PDF."""
    try:
        pdf_io = io.BytesIO(pdf_content)
        with fitz.open(stream=pdf_io, filetype="pdf") as doc:
            return len(doc)
    except Exception as e:
        st.error(f"Error getting PDF page count: {str(e)}")
        return 0

# Format confidence level with color
def format_confidence(confidence_value):
    """Format confidence level with appropriate color."""
    if confidence_value >= 95:
        return f"<span style='color:green;font-weight:bold'>{confidence_value:.1f}%</span>"
    elif confidence_value >= 90:
        return f"<span style='color:orange;font-weight:bold'>{confidence_value:.1f}%</span>"
    else:
        return f"<span style='color:red;font-weight:bold'>{confidence_value:.1f}%</span>"

def prevent_cache(func):
    """Decorator to prevent caching of a function."""
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper
