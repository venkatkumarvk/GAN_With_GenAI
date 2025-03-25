import base64
import os
import json
import tempfile
import streamlit as st
from dotenv import load_dotenv
from openai import AzureOpenAI
from pathlib import Path
import fitz  # PyMuPDF
import pandas as pd
from datetime import datetime
import io
import zipfile
from azure.storage.blob import BlobServiceClient, ContentSettings
import gc  # For garbage collection

# Load environment variables from .env file
load_dotenv()

# Azure OpenAI environment variables
aoai_endpoint = os.getenv("AOAI_ENDPOINT")
aoai_api_key = os.getenv("AOAI_API_KEY")
aoai_deployment_name = os.getenv("AOAI_DEPLOYMENT")

# Azure Blob Storage environment variables
azure_storage_connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
azure_storage_container_name = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "pdf-extraction-results")

# Session state initialization for persistent data
if 'all_pdf_results' not in st.session_state:
    st.session_state.all_pdf_results = []
if 'results_df' not in st.session_state:
    st.session_state.results_df = None
if 'selected_pdf_for_editing' not in st.session_state:
    st.session_state.selected_pdf_for_editing = None
if 'edited_data' not in st.session_state:
    st.session_state.edited_data = {}
if 'download_completed' not in st.session_state:
    st.session_state.download_completed = False
if 'last_processing_timestamp' not in st.session_state:
    st.session_state.last_processing_timestamp = None
if 'original_files' not in st.session_state:
    st.session_state.original_files = None

# Initialize the Azure OpenAI client
@st.cache_resource
def get_client():
    return AzureOpenAI(
        azure_endpoint=aoai_endpoint,
        api_key=aoai_api_key,
        api_version="2024-08-01-preview"
    )

# Initialize the Azure Blob Storage client
@st.cache_resource
def get_blob_service_client():
    return BlobServiceClient.from_connection_string(azure_storage_connection_string)

def get_blob_containers(blob_service_client):
    """
    Get a list of available containers in the Azure Blob Storage account.
    """
    try:
        containers = []
        for container in blob_service_client.list_containers():
            containers.append(container.name)
        return containers
    except Exception as e:
        st.error(f"Error listing containers: {e}")
        return []

def get_blob_folders(blob_service_client, container_name):
    """
    Get a list of "folders" (common prefixes) in the Azure Blob Storage container.
    Note: Blob storage doesn't have actual folders, but we can simulate them using prefixes.
    """
    try:
        container_client = blob_service_client.get_container_client(container_name)
        
        # Get all blobs in the container
        blobs = container_client.list_blobs()
        
        # Extract folder paths (common prefixes before the last '/')
        folders = set()
        for blob in blobs:
            name = blob.name
            if '/' in name:
                folder = name.rsplit('/', 1)[0] + '/'
                folders.add(folder)
            
        # Add a root option
        folders.add("")  # root directory
        
        return sorted(list(folders))
    except Exception as e:
        st.error(f"Error listing folders in container {container_name}: {e}")
        return []

def list_pdf_blobs(blob_service_client, container_name, folder_prefix=""):
    """
    List all PDF blobs in the specified container and folder prefix.
    """
    try:
        container_client = blob_service_client.get_container_client(container_name)
        
        # Get blobs with the folder prefix that are PDFs
        pdf_blobs = []
        for blob in container_client.list_blobs(name_starts_with=folder_prefix):
            if blob.name.lower().endswith('.pdf'):
                pdf_blobs.append(blob.name)
                
        return pdf_blobs
    except Exception as e:
        st.error(f"Error listing PDF blobs: {e}")
        return []

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

def render_pdf_preview(pdf_file):
    """
    Render a preview of the first page of a PDF file.
    For uploaded files or blob downloads.
    Memory optimized version.
    """
    tmp_path = None
    try:
        # If it's a uploaded file, get the bytes
        if hasattr(pdf_file, 'getvalue'):
            pdf_bytes = pdf_file.getvalue()
        else:
            # Assume it's already bytes (from blob storage)
            pdf_bytes = pdf_file
            
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(pdf_bytes)
            tmp_path = tmp_file.name
            
        # Open the PDF and get the first page as an image
        with fitz.open(tmp_path) as doc:
            if len(doc) > 0:
                # Get the first page
                page = doc.load_page(0)
                
                # Render the page to an image (with reasonable resolution)
                zoom = 1.5  # slightly reduced zoom factor to save memory
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                
                # Convert to an image
                img_bytes = pix.tobytes()
                
                # Return the image
                return img_bytes
            else:
                st.sidebar.warning("PDF appears to be empty")
                return None
                
    except Exception as e:
        st.sidebar.error(f"Error rendering PDF preview: {e}")
        return None
    finally:
        # Clean up temporary file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception as cleanup_error:
                st.sidebar.warning(f"Could not remove temporary preview file: {cleanup_error}")
        # Force garbage collection
        gc.collect()

def display_pdf_previews_sidebar(files, blob_service_client=None, container_name=None):
    """
    Display preview thumbnails of PDFs in the sidebar.
    Works with both uploaded files and blob references.
    Memory optimized version.
    """
    st.sidebar.header("PDF Previews")
    
    if not files:
        st.sidebar.info("No PDF files to preview")
        return
    
    # Limit number of previews to avoid memory issues
    max_previews = 5
    preview_files = files[:max_previews] if len(files) > max_previews else files
    
    if len(files) > max_previews:
        st.sidebar.warning(f"Showing only {max_previews} of {len(files)} PDFs to conserve memory")
    
    # Create a scrollable area for previews
    preview_area = st.sidebar.container()
    
    with preview_area:
        for i, file in enumerate(preview_files):
            # Create an expander for each file
            if isinstance(file, str):  # It's a blob name
                filename = file.split('/')[-1]  # Extract filename from path
                with st.sidebar.expander(f"{i+1}. {filename}"):
                    # Download blob contents
                    blob_content = download_blob_to_memory(blob_service_client, container_name, file)
                    if blob_content:
                        with st.spinner("Generating preview..."):
                            img_bytes = render_pdf_preview(blob_content)
                        if img_bytes:
                            # Display image with caption
                            st.image(img_bytes, caption=f"Page 1 of {filename}", use_column_width=True)
                            del img_bytes  # Free memory
                        else:
                            st.warning("Could not generate preview")
                    else:
                        st.error(f"Could not download {filename}")
            else:  # It's an uploaded file
                with st.sidebar.expander(f"{i+1}. {file.name}"):
                    # Get file position
                    pos = file.tell()
                    
                    # Generate preview
                    with st.spinner("Generating preview..."):
                        img_bytes = render_pdf_preview(file)
                    
                    # Reset file position for later use
                    file.seek(pos)
                    
                    if img_bytes:
                        # Display image with caption
                        st.image(img_bytes, caption=f"Page 1 of {file.name}", use_column_width=True)
                        del img_bytes  # Free memory
                    else:
                        st.warning("Could not generate preview")
        
        # Force garbage collection after rendering previews
        gc.collect()

def convert_pdf_to_base64(pdf_file):
    """
    Convert a PDF file to base64 for embedding in HTML.
    
    Parameters:
    - pdf_file: Either a BytesIO object or bytes
    
    Returns:
    - base64 string of the PDF file
    """
    try:
        # If it's an uploaded file with getvalue method, use that
        if hasattr(pdf_file, 'getvalue'):
            pdf_bytes = pdf_file.getvalue()
        else:
            # Assume it's already bytes
            pdf_bytes = pdf_file
            
        # Encode to base64
        base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
        return base64_pdf
    except Exception as e:
        st.error(f"Error converting PDF to base64: {e}")
        return None

def display_pdf_viewer(base64_pdf, height=500):
    """
    Display a PDF viewer in the Streamlit app using base64 encoded PDF.
    No temporary files are created on disk.
    
    Parameters:
    - base64_pdf: base64 encoded PDF data
    - height: height of the viewer iframe
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

def display_pdf_preview_tab(all_pdf_results, files, input_method, blob_service_client=None, container_name=None):
    """
    Display PDF preview tab after processing.
    All previews are generated directly from memory without creating temporary files.
    Memory optimized version.
    
    Parameters:
    - all_pdf_results: Processed PDF results
    - files: Original files (either uploaded files or blob references)
    - input_method: "Upload Files" or "Azure Blob Storage"
    - blob_service_client: Optional, for Azure Blob Storage
    - container_name: Optional, for Azure Blob Storage
    """
    if not files or not all_pdf_results:
        st.info("No PDFs available to preview")
        return
    
    # Create tabs for each PDF
    pdf_tabs = st.tabs([pdf_result["filename"] for pdf_result in all_pdf_results])
    
    for i, tab in enumerate(pdf_tabs):
        with tab:
            try:
                filename = all_pdf_results[i]["filename"]
                
                if input_method == "Upload Files":
                    # For uploaded files, find the matching file object
                    file_obj = next((f for f in files if f.name == filename), None)
                    
                    if file_obj:
                        # Get file position and reset after use
                        pos = file_obj.tell()
                        with st.spinner(f"Loading {filename}..."):
                            base64_pdf = convert_pdf_to_base64(file_obj)
                        file_obj.seek(pos)  # Reset file position
                    else:
                        st.error(f"Could not find original file for {filename}")
                        continue
                else:
                    # For blob files, find the matching blob reference
                    blob_name = next((b for b in files if b.split('/')[-1] == filename), None)
                    
                    if blob_name and blob_service_client:
                        # Download blob content directly to memory
                        with st.spinner(f"Downloading {filename}..."):
                            blob_content = download_blob_to_memory(blob_service_client, container_name, blob_name)
                        if blob_content:
                            base64_pdf = convert_pdf_to_base64(blob_content)
                        else:
                            st.error(f"Could not download blob content for {filename}")
                            continue
                    else:
                        st.error(f"Could not find original blob for {filename}")
                        continue
                
                if base64_pdf:
                    st.write(f"### Preview of {filename}")
                    display_pdf_viewer(base64_pdf)
                    # Clear memory
                    del base64_pdf
                else:
                    st.error(f"Could not create preview for {filename}")
                    
            except Exception as e:
                st.error(f"Error displaying preview for PDF {i+1}: {e}")
            
            # Force garbage collection after each PDF display
            gc.collect()

def image_to_data_url(image_bytes, mime_type='image/png'):
    """
    Convert image bytes to a data URL.
    """
    base64_encoded_data = base64.b64encode(image_bytes).decode('utf-8')
    return f"data:{mime_type};base64,{base64_encoded_data}"

def call_azure_openai_vision(prompt, image_data_url, client, deployment_name):
    """
    Call the Azure OpenAI Vision service to analyze an image.
    """
    try:
        completion = client.chat.completions.create(
            model=deployment_name,
            messages=[{
                "role": "system",
                "content": "You are an AI helpful assistant that extracts information from invoice documents. Your task is to extract the following fields from invoices: VendorName, InvoiceNumber, InvoiceDate, CustomerName, PurchaseOrder, StockCode, UnitPrice, InvoiceAmount, Freight, Salestax, and Total. Return a JSON object with these keys. For each field, also include a confidence score between 0 and 1. The response format should be: {\"VendorName\": {\"value\": \"ABC Corp\", \"confidence\": 0.95}, \"InvoiceNumber\": {\"value\": \"INV-12345\", \"confidence\": 0.87}, ...and so on for each field.}"
            }, {
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": prompt
                }, {
                    "type": "image_url",
                    "image_url": {
                        "url": image_data_url
                    }
                }]
            }],
            max_tokens=2000,
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        
        # Extract and parse the response content
        response_content = completion.choices[0].message.content
        return json.loads(response_content)
    except Exception as e:
        st.error(f"Error calling Azure OpenAI: {str(e)}")
        return {"error": str(e)}
    
def display_pdf_preview_tab(all_pdf_results, files, input_method, blob_service_client=None, container_name=None):
    """
    Display PDF preview tab after processing.
    All previews are generated directly from memory without creating temporary files.
    Memory optimized version.
    
    Parameters:
    - all_pdf_results: Processed PDF results
    - files: Original files (either uploaded files or blob references)
    - input_method: "Upload Files" or "Azure Blob Storage"
    - blob_service_client: Optional, for Azure Blob Storage
    - container_name: Optional, for Azure Blob Storage
    """
    if not files or not all_pdf_results:
        st.info("No PDFs available to preview")
        return
    
    # Create tabs for each PDF
    pdf_tabs = st.tabs([pdf_result["filename"] for pdf_result in all_pdf_results])
    
    for i, tab in enumerate(pdf_tabs):
        with tab:
            try:
                filename = all_pdf_results[i]["filename"]
                
                if input_method == "Upload Files":
                    # For uploaded files, find the matching file object
                    file_obj = next((f for f in files if f.name == filename), None)
                    
                    if file_obj:
                        # Get file position and reset after use
                        pos = file_obj.tell()
                        with st.spinner(f"Loading {filename}..."):
                            base64_pdf = convert_pdf_to_base64(file_obj)
                        file_obj.seek(pos)  # Reset file position
                    else:
                        st.error(f"Could not find original file for {filename}")
                        continue
                else:
                    # For blob files, find the matching blob reference
                    blob_name = next((b for b in files if b.split('/')[-1] == filename), None)
                    
                    if blob_name and blob_service_client:
                        # Download blob content directly to memory
                        with st.spinner(f"Downloading {filename}..."):
                            blob_content = download_blob_to_memory(blob_service_client, container_name, blob_name)
                        if blob_content:
                            base64_pdf = convert_pdf_to_base64(blob_content)
                        else:
                            st.error(f"Could not download blob content for {filename}")
                            continue
                    else:
                        st.error(f"Could not find original blob for {filename}")
                        continue
                
                if base64_pdf:
                    st.write(f"### Preview of {filename}")
                    display_pdf_viewer(base64_pdf)
                    # Clear memory
                    del base64_pdf
                else:
                    st.error(f"Could not create preview for {filename}")
                    
            except Exception as e:
                st.error(f"Error displaying preview for PDF {i+1}: {e}")
            
            # Force garbage collection after each PDF display
            gc.collect()

def image_to_data_url(image_bytes, mime_type='image/png'):
    """
    Convert image bytes to a data URL.
    """
    base64_encoded_data = base64.b64encode(image_bytes).decode('utf-8')
    return f"data:{mime_type};base64,{base64_encoded_data}"

def call_azure_openai_vision(prompt, image_data_url, client, deployment_name):
    """
    Call the Azure OpenAI Vision service to analyze an image.
    """
    try:
        completion = client.chat.completions.create(
            model=deployment_name,
            messages=[{
                "role": "system",
                "content": "You are an AI helpful assistant that extracts information from invoice documents. Your task is to extract the following fields from invoices: VendorName, InvoiceNumber, InvoiceDate, CustomerName, PurchaseOrder, StockCode, UnitPrice, InvoiceAmount, Freight, Salestax, and Total. Return a JSON object with these keys. For each field, also include a confidence score between 0 and 1. The response format should be: {\"VendorName\": {\"value\": \"ABC Corp\", \"confidence\": 0.95}, \"InvoiceNumber\": {\"value\": \"INV-12345\", \"confidence\": 0.87}, ...and so on for each field.}"
            }, {
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": prompt
                }, {
                    "type": "image_url",
                    "image_url": {
                        "url": image_data_url
                    }
                }]
            }],
            max_tokens=2000,
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        
        # Extract and parse the response content
        response_content = completion.choices[0].message.content
        return json.loads(response_content)
    except Exception as e:
        st.error(f"Error calling Azure OpenAI: {str(e)}")
        return {"error": str(e)}
    
def create_results_dataframe(all_pdf_results):
    """
    Create a pandas DataFrame from the extracted results for easy viewing.
    Memory-optimized version.
    """
    rows = []
    
    # Define the fields we're extracting
    fields = [
        "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
        "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
        "Freight", "Salestax", "Total"
    ]
    
    for pdf_result in all_pdf_results:
        filename = pdf_result["filename"]
        
        for page in pdf_result["pages"]:
            page_num = page["page"]
            data = page["data"]
            
            # Check for errors
            if "error" in data:
                row_data = {
                    "Filename": filename,
                    "Page": page_num
                }
                
                # Add placeholders for all fields and confidence values
                for field in fields:
                    row_data[field] = "N/A"
                    row_data[f"{field} Confidence"] = 0
                
                rows.append(row_data)
                continue
            
            # Initialize row data
            row_data = {
                "Filename": filename,
                "Page": page_num
            }
            
            # Process each field
            for field in fields:
                field_data = data.get(field, {})
                
                if isinstance(field_data, dict):
                    value = field_data.get("value", "N/A")
                    confidence = field_data.get("confidence", 0)
                else:
                    value = field_data if field_data else "N/A"
                    confidence = 0
                
                # Ensure values are strings to avoid PyArrow errors
                if isinstance(value, (list, dict)):
                    value = str(value)
                
                # Add to row data
                row_data[field] = value
                row_data[f"{field} Confidence"] = round(confidence * 100, 2)
            
            # Add completed row to rows
            rows.append(row_data)
    
    try:
        # First method: Try creating a DataFrame with string type
        # This avoids PyArrow conversion issues for mixed types
        return pd.DataFrame(rows, dtype=str)
    except Exception as e:
        st.warning(f"Error creating DataFrame: {e}. Trying alternative method...")
        
        try:
            # Second method: Try with pandas default types but disable PyArrow
            with pd.option_context('mode.dtype_backend', 'numpy'):  # Use NumPy instead of PyArrow
                return pd.DataFrame(rows)
        except Exception as e:
            st.warning(f"Second method failed: {e}. Using final fallback method...")
            
            try:
                # Third method: Convert all values to strings explicitly before creating DataFrame
                string_rows = []
                for row in rows:
                    string_row = {}
                    for key, value in row.items():
                        string_row[key] = str(value)
                    string_rows.append(string_row)
                return pd.DataFrame(string_rows)
            except Exception as e:
                st.error(f"All DataFrame creation methods failed: {e}")
                # Return empty DataFrame as absolute last resort
                return pd.DataFrame()

def create_text_files_zip(all_pdf_results):
    """
    Create a zip file containing text files for each PDF.
    """
    # Create a BytesIO object to store the zip file
    zip_buffer = io.BytesIO()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Create a ZipFile object
    with zipfile.ZipFile(zip_buffer, 'a', zipfile.ZIP_DEFLATED, False) as zip_file:
        for pdf_result in all_pdf_results:
            filename = pdf_result["filename"]
            base_filename = os.path.splitext(filename)[0]
            
            # Create the text content for this PDF (only key-value pairs)
            page_results_text = create_page_results_text(pdf_result)
            
            # Add structured data as a text file with timestamp
            zip_file.writestr(f"{base_filename}_{timestamp}.txt", page_results_text)
    
    # Seek to the beginning of the BytesIO object
    zip_buffer.seek(0)
    return zip_buffer

def create_page_results_text(pdf_result):
    """
    Create a text file containing only the key-value pairs from each page.
    Returns a string with the formatted key-value pairs.
    """
    # Define the fields we're extracting
    fields = [
        "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
        "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
        "Freight", "Salestax", "Total"
    ]
    
    result_text = ""
    
    for page in pdf_result["pages"]:
        page_num = page["page"]
        data = page["data"]
        
        result_text += f"--- PAGE {page_num} ---\n"
        
        if "error" in data:
            result_text += f"error: {data['error']}\n\n"
            continue
            
        # Process fields with confidence scores
        for field in fields:
            display_field = ''.join(' ' + char if char.isupper() else char for char in field).strip().lower()
            
            field_data = data.get(field, {})
            if isinstance(field_data, dict):
                value = field_data.get("value", "N/A")
                confidence = field_data.get("confidence", 0)
                result_text += f"{display_field}: {value}\n"
                result_text += f"{display_field} confidence: {round(confidence * 100, 2)}%\n"
            else:
                result_text += f"{display_field}: {field_data}\n"
        
        result_text += "\n"
        
    return result_text

def evaluate_extraction_results(all_pdf_results):
    """
    Evaluate the quality and completeness of extraction results using the
    confidence scores provided by Azure AI Vision.
    """
    # Define the fields we're extracting
    fields = [
        "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
        "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
        "Freight", "Salestax", "Total"
    ]
    
    evaluation_results = {
        "total_documents": len(all_pdf_results),
        "total_pages": 0,
        "successful_pages": 0,
        "failed_pages": 0,
        "field_confidence": {},
        "documents_with_errors": []
    }
    
    # Initialize field confidence data structure
    for field in fields:
        evaluation_results["field_confidence"][field] = {
            "total": 0,
            "average_confidence": 0,
            "pages_above_threshold": 0,
            "percent_above_threshold": 0
        }
    
    confidence_threshold = 0.9  # 90% confidence threshold
    
    # Collect all confidence scores by field
    all_confidences = {}
    for field in fields:
        all_confidences[field] = []
    
    for pdf_result in all_pdf_results:
        filename = pdf_result["filename"]
        document_has_error = False
        
        for page in pdf_result["pages"]:
            evaluation_results["total_pages"] += 1
            data = page["data"]
            
            if "error" in data:
                evaluation_results["failed_pages"] += 1
                document_has_error = True
                continue
                
            page_successful = True
            
            # Check each field for confidence scores
            for field in fields:
                field_data = data.get(field, {})
                
                if isinstance(field_data, dict) and "confidence" in field_data:
                    confidence = field_data.get("confidence", 0)
                    evaluation_results["field_confidence"][field]["total"] += 1
                    all_confidences[field].append(confidence)
                    
                    # Count pages above threshold
                    if confidence >= confidence_threshold:
                        evaluation_results["field_confidence"][field]["pages_above_threshold"] += 1
                    else:
                        page_successful = False
                else:
                    page_successful = False
            
            if page_successful:
                evaluation_results["successful_pages"] += 1
            else:
                evaluation_results["failed_pages"] += 1
                document_has_error = True
        
        if document_has_error:
            evaluation_results["documents_with_errors"].append(filename)
    
    # Calculate average confidence for each field
    for field in all_confidences:
        confidences = all_confidences[field]
        if confidences:
            avg_confidence = sum(confidences) / len(confidences)
            evaluation_results["field_confidence"][field]["average_confidence"] = round(avg_confidence * 100, 2)
            
            # Calculate percentage of pages above threshold
            total = evaluation_results["field_confidence"][field]["total"]
            if total > 0:
                above_threshold = evaluation_results["field_confidence"][field]["pages_above_threshold"]
                evaluation_results["field_confidence"][field]["percent_above_threshold"] = round((above_threshold / total) * 100, 2)
    
    # Calculate overall success rate
    if evaluation_results["total_pages"] > 0:
        evaluation_results["success_rate"] = round((evaluation_results["successful_pages"] / evaluation_results["total_pages"]) * 100, 2)
    
    # Calculate overall confidence score (average of field confidence)
    field_scores = [field_data["average_confidence"] for field_data in evaluation_results["field_confidence"].values() if "average_confidence" in field_data]
    if field_scores:
        evaluation_results["overall_confidence_score"] = round(sum(field_scores) / len(field_scores), 2)
    
    return evaluation_results

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

def reset_download_state():
    """Reset the download completion state."""
    st.session_state.download_completed = False

def update_edited_data(pdf_filename, page_num, field, new_value):
    """
    Updates the edited data in the session state.
    """
    # Initialize the edited data structure if it doesn't exist
    if 'edited_data' not in st.session_state:
        st.session_state.edited_data = {}
    
    # Create the nested structure if it doesn't exist
    if pdf_filename not in st.session_state.edited_data:
        st.session_state.edited_data[pdf_filename] = {}
    
    if page_num not in st.session_state.edited_data[pdf_filename]:
        st.session_state.edited_data[pdf_filename][page_num] = {}
    
    # Store the edited value
    st.session_state.edited_data[pdf_filename][page_num][field] = new_value

def apply_edits_to_results(all_pdf_results, edited_data):
    """
    Apply manual edits to the PDF extraction results.
    Returns a copy of the results with edits applied.
    """
    # Create a deep copy to avoid modifying the original
    import copy
    edited_results = copy.deepcopy(all_pdf_results)
    
    # Apply the edits
    for pdf_filename, pages in edited_data.items():
        # Find the PDF result that matches this filename
        for pdf_result in edited_results:
            if pdf_result["filename"] == pdf_filename:
                # Apply edits for each page
                for page_num_str, fields in pages.items():
                    page_num = int(page_num_str)
                    
                    # Find the page data
                    for page_data in pdf_result["pages"]:
                        if page_data["page"] == page_num:
                            # Apply edits to each field
                            for field, new_value in fields.items():
                                if field in page_data["data"]:
                                    # Update value while keeping confidence
                                    if isinstance(page_data["data"][field], dict):
                                        page_data["data"][field]["value"] = new_value
                                        # Indicate this was manually edited
                                        page_data["data"][field]["manually_edited"] = True
                                    else:
                                        # If it's not a dict, just replace the value
                                        page_data["data"][field] = new_value
                
                # Break once we've found and edited the PDF
                break
    
    return edited_results

def show_manual_editing_interface(all_pdf_results):
    """
    Display an interface for manually editing extraction results.
    """
    st.subheader("Manual Extraction Editing")
    
    # List of PDFs to edit
    pdf_filenames = [pdf_result["filename"] for pdf_result in all_pdf_results]
    
    # Create two columns for selection
    col1, col2 = st.columns(2)
    
    with col1:
        selected_pdf = st.selectbox(
            "Select PDF to edit",
            pdf_filenames,
            key="edit_pdf_select"
        )
    
    # Find the selected PDF data
    selected_pdf_data = next((pdf for pdf in all_pdf_results if pdf["filename"] == selected_pdf), None)
    
    if selected_pdf_data:
        # Get pages from the selected PDF
        pages = [page["page"] for page in selected_pdf_data["pages"]]
        
        with col2:
            selected_page = st.selectbox(
                "Select page to edit",
                pages,
                key="edit_page_select"
            )
        
        # Find the selected page data
        selected_page_data = next((page for page in selected_pdf_data["pages"] if page["page"] == selected_page), None)
        
        if selected_page_data:
            # Define the fields we're extracting
            fields = [
                "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
                "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
                "Freight", "Salestax", "Total"
            ]
            
            # Show editable fields for the page
            st.write(f"### Editing {selected_pdf} - Page {selected_page}")
            
            # Check if there's error in the data
            if "error" in selected_page_data["data"]:
                st.error(f"Error in data extraction: {selected_page_data['data']['error']}")
                st.warning("Cannot edit data for this page due to extraction error.")
                return
            
            # Create a form for editing
            with st.form(key=f"edit_form_{selected_pdf}_{selected_page}"):
                # Create columns for field and confidence
                for field in fields:
                    col1, col2 = st.columns([3, 1])
                    
                    # Get field data
                    field_data = selected_page_data["data"].get(field, {})
                    
                    # Get current value and confidence
                    current_value = ""
                    confidence = 0
                    
                    if isinstance(field_data, dict):
                        current_value = field_data.get("value", "")
                        confidence = field_data.get("confidence", 0) * 100
                    else:
                        current_value = field_data if field_data else ""
                    
                    # Check if we have an edited value
                    edited_value = None
                    if (selected_pdf in st.session_state.edited_data and 
                        str(selected_page) in st.session_state.edited_data[selected_pdf] and
                        field in st.session_state.edited_data[selected_pdf][str(selected_page)]):
                        edited_value = st.session_state.edited_data[selected_pdf][str(selected_page)][field]
                    
                    # Display the field input
                    with col1:
                        # Add visual indicator for low confidence
                        field_label = field
                        if confidence < 90:
                            field_label = f"{field} ⚠️"
                        
                        # Use the edited value if available, otherwise the current value
                        value_to_show = edited_value if edited_value is not None else current_value
                        
                        # Text input for the field
                        new_value = st.text_input(
                            field_label,
                            value=value_to_show,
                            key=f"field_{selected_pdf}_{selected_page}_{field}"
                        )
                    
                    # Display confidence
                    with col2:
                        confidence_color = "green" if confidence >= 90 else "red"
                        st.markdown(f"<p style='color:{confidence_color};'>Confidence: {confidence:.1f}%</p>", unsafe_allow_html=True)
                
                # Submit button
                submit_button = st.form_submit_button("Save Edits")
                
                if submit_button:
                    # Update edited values in session state
                    for field in fields:
                        new_value = st.session_state[f"field_{selected_pdf}_{selected_page}_{field}"]
                        update_edited_data(selected_pdf, str(selected_page), field, new_value)
                    
                    st.success(f"Edits saved for {selected_pdf} - Page {selected_page}")
            
            # Show status of edited fields
            if (selected_pdf in st.session_state.edited_data and 
                str(selected_page) in st.session_state.edited_data[selected_pdf]):
                st.info(f"You have edited {len(st.session_state.edited_data[selected_pdf][str(selected_page)])} fields on this page.")

def update_results_with_edits():
    """
    Update the extraction results with manual edits.
    """
    if 'all_pdf_results' in st.session_state and st.session_state.all_pdf_results:
        # Apply edits to create updated results
        edited_results = apply_edits_to_results(
            st.session_state.all_pdf_results,
            st.session_state.edited_data
        )
        
        # Update the results DataFrame
        st.session_state.results_df = create_results_dataframe(edited_results)
        
        # Return the edited results
        return edited_results
    
    return None

def main():
    st.set_page_config(
        page_title="PDF Financial Data Extractor",
        page_icon="📊",
        layout="wide"
    )
    
    st.title("PDF Financial Data Extractor")
    st.subheader("Extract invoice data from PDF files")
    
    # Add a sidebar menu for navigation
    st.sidebar.title("Navigation")
    app_mode = st.sidebar.radio(
        "Choose a mode",
        ["Extract Data", "Manual Edit", "View Results"],
        index=0
    )
    
    # Display mode logic based on app_mode
    if app_mode == "Extract Data":
        # Check if Azure OpenAI credentials are available
        if not all([aoai_endpoint, aoai_api_key, aoai_deployment_name]):
            st.error("Azure OpenAI credentials are missing. Please set AOAI_ENDPOINT, AOAI_API_KEY, and AOAI_DEPLOYMENT environment variables.")
            return
        
        # Check if Azure Blob Storage credentials are available
        if not azure_storage_connection_string:
            st.warning("Azure Blob Storage connection string is missing. Some features will be disabled. Please set AZURE_STORAGE_CONNECTION_STRING environment variable.")
        
        # Initialize the clients
        client = get_client()
        blob_service_client = get_blob_service_client() if azure_storage_connection_string else None
        
        # Advanced settings in an expandable section
        with st.expander("Advanced Settings"):
            prompt = st.text_area(
                "Extraction Prompt", 
                """Based on this image, extract the following information from the invoice:   
                1) What is the vendor name?
                2) What is the invoice number?
                3) What is the invoice date?
                4) What is the customer name?
                5) What is the purchase order number?
                6) What is the stock code?
                7) What is the unit price?
                8) What is the invoice amount?
                9) What is the freight cost?
                10) What is the sales tax?
                11) What is the total amount?""",
                help="Customize the prompt sent to Azure OpenAI Vision to extract information"
            )
        
        # Input method selection
        input_method = st.radio(
            "Select Input Method",
            ["Upload Files", "Azure Blob Storage"],
            help="Choose how to input PDF files for processing"
        )
        
        files_to_process = None
        
        if input_method == "Upload Files":
            # File uploader
            uploaded_files = st.file_uploader(
                "Upload PDF files", 
                type="pdf", 
                accept_multiple_files=True,
                help="Upload one or more PDF files containing financial statements"
            )
            
            # Display previews in sidebar if files are uploaded
            if uploaded_files:
                display_pdf_previews_sidebar(uploaded_files)
            
            # Process button
            process_button = st.button("Process Documents", type="primary")
            
            if process_button and not uploaded_files:
                st.warning("Please upload at least one PDF file.")
                return
                
            files_to_process = uploaded_files if process_button else None
        
        else:  # Azure Blob Storage
            if not blob_service_client:
                st.error("Azure Blob Storage connection is required for this option. Please set AZURE_STORAGE_CONNECTION_STRING environment variable.")
                return
            
            # Get available containers
            containers = get_blob_containers(blob_service_client)
            
            if not containers:
                st.error("No containers found in the Azure Blob Storage account. Please create at least one container.")
                return
            
            # Container selection
            selected_container = st.selectbox(
                "Select Container",
                containers,
                help="Choose an Azure Blob Storage container"
            )
            
            # Get folders in the selected container
            folders = get_blob_folders(blob_service_client, selected_container)
            
            # Folder selection
            selected_folder = st.selectbox(
                "Select Folder",
                folders,
                format_func=lambda x: "Root (No Folder)" if x == "" else x,
                help="Choose a folder within the container"
            )
            
            # List available PDFs
            pdf_blobs = list_pdf_blobs(blob_service_client, selected_container, selected_folder)
            
            if not pdf_blobs:
                st.warning(f"No PDF files found in the selected location. Please choose another container or folder.")
                return
            
            # Show available PDFs
            st.write(f"Found {len(pdf_blobs)} PDF files:")
            
            # Create columns for better display
            pdf_cols = st.columns(3)
            for i, pdf in enumerate(pdf_blobs):
                display_name = pdf.split('/')[-1]  # Remove folder path for display
                pdf_cols[i % 3].write(f"- {display_name}")
                if i >= 11:  # Limit display to avoid cluttering
                    pdf_cols[(i + 1) % 3].write("...")
                    break
            
            # Display previews in sidebar
            display_pdf_previews_sidebar(pdf_blobs, blob_service_client, selected_container)
            
            # Process button
            process_button = st.button("Process Blob Documents", type="primary")
            
            files_to_process = pdf_blobs if process_button else None

        # Process files if requested
        if files_to_process:
            with st.spinner("Processing documents..."):
                # Create a container for the whole processing section
                processing_container = st.container()
                
                with processing_container:
                    # Store all PDF results
                    all_pdf_results = []
                    
                    # Create a timestamp for the filename
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    st.session_state.last_processing_timestamp = timestamp
                    
                    # Store original files reference for preview
                    st.session_state.original_files = files_to_process
                    
                    # Process the PDFs based on input method
                    if input_method == "Upload Files":
                        # Process uploaded PDFs
                        progress_bar = st.progress(0)
                        progress_text = st.empty()
                        
                        # Process each uploaded PDF
                        for i, pdf_file in enumerate(files_to_process):
                            progress_text.text(f"Processing file {i+1}/{len(files_to_process)}: {pdf_file.name}")
                            
                            # Process the PDF and get results
                            pdf_result = process_pdf(
                                pdf_file, 
                                prompt, 
                                client, 
                                aoai_deployment_name,
                                progress_bar,
                                progress_text
                            )
                            
                            # Add to our collection of all PDF results
                            all_pdf_results.append(pdf_result)
                            
                            # Update overall progress
                            progress_bar.progress((i + 1) / len(files_to_process))
                            
                        progress_text.text("Processing complete!")
                        progress_bar.progress(1.0)
                    else:
                        # Process PDFs from Blob Storage
                        all_pdf_results = process_blob_pdfs(
                            blob_service_client,
                            selected_container,
                            files_to_process,
                            prompt,
                            client,
                            aoai_deployment_name
                        )
                    
                    # Store in session state
                    st.session_state.all_pdf_results = all_pdf_results
                    
                    # Create DataFrame view
                    if all_pdf_results:
                        try:
                            results_df = create_results_dataframe(all_pdf_results)
                            st.session_state.results_df = results_df
                        except Exception as e:
                            st.error(f"Error creating results DataFrame: {e}")
                    
                    # Reset edited data when processing new files
                    st.session_state.edited_data = {}

                    
                    # Manual Editing Mode
    elif app_mode == "Manual Edit":
        st.header("Manual Edit Extraction Results")
        
        if 'all_pdf_results' not in st.session_state or not st.session_state.all_pdf_results:
            st.warning("No extraction results available. Please run extraction first.")
            return
        
        # Show manual editing interface
        show_manual_editing_interface(st.session_state.all_pdf_results)
        
        # Add button to apply edits and update results
        if st.button("Apply Edits and Update Results", type="primary"):
            edited_results = update_results_with_edits()
            if edited_results:
                st.success("Edits applied successfully!")
                st.session_state.all_pdf_results = edited_results
            else:
                st.error("Failed to apply edits. Please try again.")

    
    # View Results Mode
    elif app_mode == "View Results":
        st.header("View Extraction Results")
        
        if 'all_pdf_results' not in st.session_state or not st.session_state.all_pdf_results:
            st.warning("No extraction results available. Please run extraction first.")
            return
        
        all_pdf_results = st.session_state.all_pdf_results
        timestamp = st.session_state.last_processing_timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create tabs to organize content
        view_tabs = st.tabs(["Results Table", "Data by Document", "Confidence Analysis", "Download Options"])
        
        with view_tabs[0]:  # Results Table
            st.subheader("Extraction Results Table")
            
            if 'results_df' in st.session_state and not st.session_state.results_df.empty:
                # Show full table
                st.dataframe(st.session_state.results_df, use_container_width=True)
            else:
                try:
                    # Try to recreate the dataframe
                    results_df = create_results_dataframe(all_pdf_results)
                    
                    if not results_df.empty:
                        st.session_state.results_df = results_df
                        st.dataframe(results_df, use_container_width=True)
                    else:
                        st.warning("Could not create results table due to data format issues.")
                        
                except Exception as e:
                    st.error(f"Error displaying results table: {e}")
        
        with view_tabs[1]:  # Data by Document
            st.subheader("Extracted Key-Value Pairs by Document")
            
            # Create tabs for each PDF
            if len(all_pdf_results) > 0:
                pdf_tabs = st.tabs([pdf_result["filename"] for pdf_result in all_pdf_results])
                
                for i, tab in enumerate(pdf_tabs):
                    with tab:
                        pdf_result = all_pdf_results[i]
                        filename = pdf_result["filename"]
                        
                        # Generate page results text
                        page_results_text = create_page_results_text(pdf_result)
                        
                        # Display the key-value page results
                        st.text_area(
                            f"Extracted Data for {filename}",
                            value=page_results_text,
                            height=300,
                            disabled=True
                        )
        
        with view_tabs[2]:  # Confidence Analysis
            st.subheader("Extraction Confidence Analysis")
            
            # Run evaluation and display results
            evaluation_results = evaluate_extraction_results(all_pdf_results)
            
            # Create metrics row
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Documents Analyzed", evaluation_results["total_documents"])
            
            with col2:
                st.metric("Total Pages", evaluation_results["total_pages"])
            
            with col3:
                if "success_rate" in evaluation_results:
                    st.metric("Success Rate", f"{evaluation_results['success_rate']}%")
            
            # Create table of confidence levels by document
            confidence_by_document = {}
            
            for pdf_result in all_pdf_results:
                filename = pdf_result["filename"]
                confidence_by_document[filename] = {
                    "high": 0,  # 90-100%
                    "low": 0    # <90%
                }
                
                # Count fields in each confidence range for this document
                for page in pdf_result["pages"]:
                    data = page["data"]
                    
                    if "error" in data:
                        continue
                        
                    for field in ["VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
                                "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
                                "Freight", "Salestax", "Total"]:
                        field_data = data.get(field, {})
                        
                        if isinstance(field_data, dict) and "confidence" in field_data:
                            confidence = field_data.get("confidence", 0) * 100
                            
                            if confidence >= 90:
                                confidence_by_document[filename]["high"] += 1
                            else:
                                confidence_by_document[filename]["low"] += 1
            
            # Create table data with high and low categories
            doc_table_data = {
                "Document": [],
                "High Confidence (90-100%)": [],
                "Low Confidence (<90%)": []
            }
            
            for filename, counts in confidence_by_document.items():
                doc_table_data["Document"].append(filename)
                doc_table_data["High Confidence (90-100%)"].append(counts["high"])
                doc_table_data["Low Confidence (<90%)"].append(counts["low"])
            
            # Display the document confidence table
            doc_confidence_df = pd.DataFrame(doc_table_data)
            st.dataframe(doc_confidence_df, use_container_width=True)
            
            # Documents that need manual verification
            st.subheader("Documents Needing Manual Verification")
            
            # Get documents with fields in low confidence range
            docs_to_verify = []
            
            for filename, counts in confidence_by_document.items():
                if counts["low"] > 0:
                    docs_to_verify.append({
                        "filename": filename,
                        "low_count": counts["low"]
                    })
            
            if docs_to_verify:
                for doc in docs_to_verify:
                    st.warning(f"⚠️ {doc['filename']} - Needs verification ({doc['low_count']} fields with <90% confidence)")
                
                # Add button to go to manual edit mode
                if st.button("Go to Manual Edit"):
                    st.session_state.app_mode = "Manual Edit"
                    st.experimental_rerun()
            else:
                st.success("✅ No documents need manual verification (all fields above 90% confidence)")
        
        with view_tabs[3]:  # Download Options
            st.subheader("Download Options")
            
            # Create a container for download buttons
            download_container = st.container()
            
            with download_container:
                st.write("Select the data formats you want to download:")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    # Create text files zip only when needed to save memory
                    if st.button("Prepare Text Files Download", on_click=reset_download_state):
                        with st.spinner("Preparing text files..."):
                            text_zip = create_text_files_zip(all_pdf_results)
                            st.session_state.text_zip = text_zip
                            st.session_state.download_completed = True
                    
                    # Show download button only when data is ready
                    if 'text_zip' in st.session_state and st.session_state.download_completed:
                        st.download_button(
                            label="Download All Text Files (ZIP)",
                            data=st.session_state.text_zip,
                            file_name=f"extracted_data_{timestamp}.zip",
                            mime="application/zip",
                            on_click=reset_download_state
                        )
                
                with col2:
                    # Prepare CSV download
                    if st.button("Prepare CSV Download", on_click=reset_download_state):
                        with st.spinner("Preparing CSV file..."):
                            try:
                                # Check if we have results_df in session_state
                                if 'results_df' in st.session_state and not st.session_state.results_df.empty:
                                    csv = st.session_state.results_df.to_csv(index=False)
                                    st.session_state.csv_data = csv
                                    st.session_state.download_completed = True
                                else:
                                    # Try to recreate the dataframe
                                    results_df = create_results_dataframe(all_pdf_results)
                                    
                                    if not results_df.empty:
                                        csv = results_df.to_csv(index=False)
                                        st.session_state.csv_data = csv
                                        st.session_state.download_completed = True
                                    else:
                                        st.warning("Could not create CSV due to data format issues.")
                            except Exception as e:
                                st.error(f"Error creating CSV: {e}")
                    
                    # Show download button only when data is ready
                    if 'csv_data' in st.session_state and st.session_state.download_completed:
                        st.download_button(
                            label="Download CSV Results",
                            data=st.session_state.csv_data,
                            file_name=f"financial_data_extraction_{timestamp}.csv",
                            mime="text/csv",
                            on_click=reset_download_state
                        )
                
                with col3:
                    # Prepare verification report
                    if st.button("Prepare Verification Report", on_click=reset_download_state):
                        with st.spinner("Preparing verification report..."):
                            # Get documents with fields in low confidence range
                            docs_to_verify = []
                            
                            for filename, counts in confidence_by_document.items():
                                if counts["low"] > 0:
                                    docs_to_verify.append({
                                        "filename": filename,
                                        "low_count": counts["low"]
                                    })
                            
                            if docs_to_verify:
                                verification_data = {
                                    "Document": [doc["filename"] for doc in docs_to_verify],
                                    "Low Confidence Fields (<90%)": [doc["low_count"] for doc in docs_to_verify]
                                }
                                verification_df = pd.DataFrame(verification_data)
                                verification_csv = verification_df.to_csv(index=False)
                                st.session_state.verification_csv = verification_csv
                                st.session_state.download_completed = True
                            else:
                                st.session_state.verification_csv = "No documents require verification"
                                st.session_state.download_completed = True
                    
                    # Show download button only when data is ready
                    if 'verification_csv' in st.session_state and st.session_state.download_completed:
                        if st.session_state.verification_csv != "No documents require verification":
                            st.download_button(
                                label="Download Verification Report",
                                data=st.session_state.verification_csv,
                                file_name=f"verification_report_{timestamp}.csv",
                                mime="text/csv",
                                on_click=reset_download_state
                            )
                        else:
                            st.success("✅ No verification report needed - all fields have high confidence.")
                
                # Add a clear button to remove download data and free memory
                if st.button("Clear Download Data", type="secondary"):
                    if 'text_zip' in st.session_state:
                        del st.session_state.text_zip
                    if 'csv_data' in st.session_state:
                        del st.session_state.csv_data
                    if 'verification_csv' in st.session_state:
                        del st.session_state.verification_csv
                    gc.collect()
                    st.success("Download data cleared from memory.")
            
            # PDF Preview tab
            st.subheader("PDF Previews")
            
            # Allow selection of files to preview to reduce memory usage
            pdf_filenames = [pdf_result["filename"] for pdf_result in all_pdf_results]
            
            selected_pdf_to_preview = st.selectbox(
                "Select PDF to preview",
                pdf_filenames,
                key="preview_pdf_select"
            )
            
            if st.button("Show PDF Preview"):
                # Get the list of files based on the input method
                input_method = "Upload Files" if isinstance(all_pdf_results[0].get("filename", ""), str) else "Azure Blob Storage"
                
                # Filter to just the selected PDF
                selected_pdf_results = [pdf for pdf in all_pdf_results if pdf["filename"] == selected_pdf_to_preview]
                
                # Display PDF preview for just the selected document
                with st.spinner(f"Loading preview for {selected_pdf_to_preview}..."):
                    # We need to load the actual PDF file data, which should be in the original input files
                    # This will need to be adapted based on how you store the original file references
                    if 'original_files' in st.session_state:
                        display_pdf_preview_tab(
                            selected_pdf_results,
                            [f for f in st.session_state.original_files if hasattr(f, 'name') and f.name == selected_pdf_to_preview],
                            input_method
                        )
                    else:
                        st.warning("Original PDF file references not available for preview. Please reprocess the documents.")


# Optional: Upload to Azure Blob Storage 
    if 'all_pdf_results' in st.session_state and st.session_state.all_pdf_results and blob_service_client:
        with st.expander("Upload Results to Azure Blob Storage"):
            result_upload_container = st.text_input(
                "Output Container Name",
                value=azure_storage_container_name,
                help="Container where results will be uploaded (will be created if doesn't exist)"
            )
            
            if st.button("Upload Results to Blob Storage"):
                with st.spinner("Uploading results..."):
                    all_pdf_results = st.session_state.all_pdf_results
                    timestamp = st.session_state.last_processing_timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
                    
                    blob_upload_results = []
                    
                    for pdf_result in all_pdf_results:
                        filename = pdf_result["filename"]
                        base_filename = os.path.splitext(filename)[0]
                        
                        # Create the text content with key-value pairs
                        page_results_text = create_page_results_text(pdf_result)
                        
                        # Create timestamp filename
                        timestamp_filename = f"{base_filename}_{timestamp}"
                        
                        # Upload text file to blob storage
                        text_blob_name = f"{timestamp_filename}.txt"
                        text_success, text_url = upload_to_blob_storage(
                            blob_service_client,
                            result_upload_container,
                            text_blob_name,
                            page_results_text,
                            "text/plain"
                        )
                        
                        # Upload JSON to blob storage
                        json_blob_name = f"{timestamp_filename}.json"
                        pdf_json = json.dumps(pdf_result, ensure_ascii=False, indent=2)
                        json_success, json_url = upload_to_blob_storage(
                            blob_service_client,
                            result_upload_container,
                            json_blob_name,
                            pdf_json,
                            "application/json"
                        )
                        
                        # Store results
                        blob_upload_results.append({
                            "filename": filename,
                            "text_success": text_success,
                            "text_url": text_url if text_success else None,
                            "json_success": json_success,
                            "json_url": json_url if json_success else None
                        })
                    
                    # Display upload results
                    st.subheader("Azure Blob Storage Upload Results")
                    
                    # Create a table to show upload results
                    upload_rows = []
                    for result in blob_upload_results:
                        upload_rows.append({
                            "Filename": result["filename"],
                            "Text File": "✅ Uploaded" if result["text_success"] else "❌ Failed",
                            "JSON File": "✅ Uploaded" if result["json_success"] else "❌ Failed"
                        })
                    
                    upload_df = pd.DataFrame(upload_rows)
                    st.dataframe(upload_df, use_container_width=True)

    # Add a footer with helpful information
    st.markdown("---")
    st.markdown("""
    ### Usage Tips:
    1. **Extract Data**: Upload or select PDF invoices and process them
    2. **Manual Edit**: Correct extraction errors, especially for fields with low confidence (<90%)
    3. **View Results**: Browse extracted data and download in various formats
    
    Memory usage is optimized to handle larger documents. If you encounter memory issues, try processing fewer documents at once.
    """)

if __name__ == "__main__":
    main()