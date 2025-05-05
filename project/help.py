import os
import io
import base64
import json
import tempfile
import fitz  # PyMuPDF
import pandas as pd
from datetime import datetime
from pathlib import Path
from azure.storage.blob import BlobServiceClient, ContentSettings

class AzureStorageHelper:
    def __init__(self, connection_string, input_container, output_container):
        self.connection_string = connection_string
        self.input_container = input_container
        self.output_container = output_container
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    
    def list_blobs_in_folder(self, folder_path=""):
        """List all PDF blobs in the specified folder."""
        pdf_blobs = []
        container_client = self.blob_service_client.get_container_client(self.input_container)
        
        for blob in container_client.list_blobs(name_starts_with=folder_path):
            if blob.name.lower().endswith('.pdf'):
                pdf_blobs.append(blob.name)
        
        return pdf_blobs
    
    def download_blob_to_memory(self, blob_name):
        """Download a blob to memory."""
        try:
            container_client = self.blob_service_client.get_container_client(self.input_container)
            blob_client = container_client.get_blob_client(blob_name)
            
            download_stream = blob_client.download_blob()
            content = download_stream.readall()
            
            print(f"Successfully downloaded: {blob_name}")
            return content
        except Exception as e:
            print(f"Error downloading blob {blob_name}: {e}")
            return None
    
    def upload_to_storage(self, blob_name, data, content_type):
        """Upload data to Azure Blob Storage."""
        try:
            container_client = self.blob_service_client.get_container_client(self.output_container)
            
            # Create the container if it doesn't exist
            if not container_client.exists():
                container_client.create_container()
            
            # Upload blob
            blob_client = container_client.get_blob_client(blob_name)
            
            # Set content settings
            content_settings = ContentSettings(content_type=content_type)
            
            # Upload the file
            blob_client.upload_blob(data, overwrite=True, content_settings=content_settings)
            
            print(f"Successfully uploaded: {blob_name}")
            return True, blob_client.url
        except Exception as e:
            print(f"Error uploading blob {blob_name}: {e}")
            return False, str(e)

class PDFProcessor:
    def __init__(self, config):
        self.config = config
        self.extraction_fields = config["processing"]["extraction_fields"]
        self.confidence_threshold = config["processing"]["confidence_threshold"]
        self.zoom_factor = config["processing"]["zoom_factor"]
    
    def image_to_base64(self, image_bytes):
        """Convert image bytes to base64 string."""
        return base64.b64encode(image_bytes).decode('utf-8')
    
    def extract_pdf_pages(self, pdf_content):
        """
        Extract pages from PDF content as base64 encoded images.
        Returns: List of tuples (page_num, base64_string)
        """
        pages = []
        
        # Create a BytesIO object from content
        pdf_io = io.BytesIO(pdf_content)
        
        # Open the PDF directly from memory
        with fitz.open(stream=pdf_io, filetype="pdf") as doc:
            page_count = len(doc)
            print(f"PDF has {page_count} pages")
            
            # Extract all pages
            for page_num in range(page_count):
                try:
                    # Load page and convert to image
                    page = doc.load_page(page_num)
                    pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom_factor, self.zoom_factor))
                    
                    # Convert to base64
                    image_bytes = pix.tobytes()
                    base64_string = base64.b64encode(image_bytes).decode('utf-8')
                    
                    # Add to pages
                    pages.append((page_num, base64_string))
                    
                    # Clean memory immediately
                    del image_bytes
                    del pix
                    
                except Exception as e:
                    print(f"Error extracting page {page_num+1}: {e}")
        
        return pages
    
    def create_extraction_prompt(self):
        """Create the prompt for classification and extraction."""
        return """First, classify this document into one of these categories:
- Terms & Conditions
- General Terms and Conditions
- Sale Order
- Delivery
- Price and Payment
- Warranty
- Other

If and ONLY if the document is in the "Other" category, extract the following information:
1) Vendor name
2) Invoice number
3) Invoice date
4) Customer name
5) Purchase order number
6) Stock code
7) Unit price
8) Invoice amount
9) Freight cost
10) Sales tax
11) Total amount

Format your response as a JSON object with these fields:
{
  "category": "the category name",
  "shouldExtract": true/false,
  "extractedData": {
    // Only include if shouldExtract is true
    "VendorName": {"value": "value", "confidence": 0.95},
    "InvoiceNumber": {"value": "value", "confidence": 0.95},
    ...and so on for all fields
  }
}"""
    
    def process_batch_results(self, results, page_numbers):
        """
        Process results from batch API.
        Returns: List of (page_num, category, extracted_info) tuples
        """
        processed_results = []
        
        for raw_response in results:
            try:
                json_response = json.loads(raw_response)
                
                # Extract the request ID to identify the page
                request_id = json_response.get("custom_id", "")
                if request_id.startswith("request-"):
                    idx = int(request_id.split("-")[1]) - 1
                    if idx < len(page_numbers):
                        page_num = page_numbers[idx]
                    else:
                        page_num = -1
                else:
                    page_num = -1
                
                # Process the actual content
                if "response" in json_response and "body" in json_response["response"]:
                    content = json_response["response"]["body"]
                    if isinstance(content, str):
                        content = json.loads(content)
                    
                    if "choices" in content and len(content["choices"]) > 0:
                        message_content = content["choices"][0]["message"]["content"]
                        result = json.loads(message_content)
                        
                        category = result.get("category", "Unknown")
                        
                        if category == "Other" and result.get("shouldExtract", False):
                            extracted_info = result.get("extractedData", {})
                            processed_results.append((page_num, category, extracted_info))
                        else:
                            processed_results.append((page_num, category, None))
            except Exception as e:
                print(f"Error processing result: {str(e)}")
                processed_results.append((page_num, "Error", None))
        
        return processed_results
    
    def has_high_confidence(self, extracted_results, threshold=None):
        """
        Determine if all fields have high confidence.
        
        Parameters:
        - extracted_results: List of (page_num, category, data) tuples
        - threshold: Confidence threshold (default: use config value)
        
        Returns:
        - True if all fields have confidence above threshold
        """
        if threshold is None:
            threshold = self.confidence_threshold
        
        for _, category, data in extracted_results:
            if category != "Other" or data is None:
                continue
                
            # Check each field's confidence
            for field_name, field_data in data.items():
                if field_name not in self.extraction_fields:
                    continue
                    
                if isinstance(field_data, dict) and "confidence" in field_data:
                    confidence = field_data["confidence"] * 100
                    if confidence < threshold:
                        return False
        
        return True
    
    def create_csv_for_results(self, extracted_results, filename):
        """
        Create a CSV file from extraction results.
        
        Parameters:
        - extracted_results: List of (page_num, category, data) tuples
        - filename: Original filename for metadata
        
        Returns:
        - CSV content as string
        - Invoice number from data (or "unknown")
        - Total amount from data (or "unknown")
        """
        # Extract fields for CSV
        pdf_rows = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Variables to store invoice number and total
        invoice_number = "unknown"
        total_amount = "unknown"
        
        for page_num, category, data in extracted_results:
            if category != "Other" or data is None:
                continue
                
            # Initialize row data
            row_data = {
                "Filename": filename,
                "Page": page_num + 1,
                "Extraction_Timestamp": timestamp
            }
            
            # Process each field
            for field in self.extraction_fields:
                field_data = data.get(field, {})
                
                if isinstance(field_data, dict):
                    value = field_data.get("value", "N/A")
                    confidence = field_data.get("confidence", 0)
                else:
                    value = field_data if field_data else "N/A"
                    confidence = 0
                
                # Add to row data
                row_data[field] = value
                row_data[f"{field} Confidence"] = round(confidence * 100, 2)
                
                # Capture invoice number and total for filename
                if field == "InvoiceNumber" and value != "N/A":
                    invoice_number = value
                elif field == "Total" and value != "N/A":
                    total_amount = value
            
            # No manual edits in automated version
            row_data["Manually_Edited_Fields"] = ""
            row_data["Manual_Edit"] = "N"
            
            pdf_rows.append(row_data)
        
        # Create DataFrame and CSV
        if pdf_rows:
            pdf_df = pd.DataFrame(pdf_rows, dtype=str)
            pdf_csv = pdf_df.to_csv(index=False)
            
            # Clean values for filename use
            safe_invoice_number = ''.join(c for c in str(invoice_number) if c.isalnum() or c in '-_.')
            safe_total_amount = ''.join(c for c in str(total_amount) if c.isalnum() or c in '-_.')
            
            return pdf_csv, safe_invoice_number, safe_total_amount
        
        return None, "unknown", "unknown"
