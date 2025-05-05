import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

from helper import AzureStorageHelper, PDFProcessor
from llm import AzureOpenAIClient

def load_config(config_path):
    """Load configuration from a JSON file."""
    with open(config_path, 'r') as f:
        return json.load(f)

def process_pdf_files(config, api_type, azure_folder):
    """
    Process PDF files from Azure Blob Storage.
    
    Parameters:
    - config: Configuration dictionary
    - api_type: 'batch' or 'general'
    - azure_folder: Folder path in Azure Blob Storage
    """
    # Initialize helpers
    storage_helper = AzureStorageHelper(
        config["azure_storage"]["connection_string"],
        config["azure_storage"]["input_container"],
        config["azure_storage"]["output_container"]
    )
    
    pdf_processor = PDFProcessor(config)
    
    ai_client = AzureOpenAIClient(config)
    
    # List PDF blobs in the specified folder
    pdf_blobs = storage_helper.list_blobs_in_folder(azure_folder)
    
    if not pdf_blobs:
        print(f"No PDF files found in folder: {azure_folder}")
        return
    
    print(f"Found {len(pdf_blobs)} PDF files to process")
    
    # Process each PDF
    for i, blob_name in enumerate(pdf_blobs):
        try:
            print(f"Processing file {i+1}/{len(pdf_blobs)}: {blob_name}")
            
            # Download blob to memory
            blob_content = storage_helper.download_blob_to_memory(blob_name)
            
            if blob_content is None:
                print(f"Could not download blob: {blob_name}")
                continue
            
            # Extract pages as base64 strings
            filename = blob_name.split('/')[-1]
            pages = pdf_processor.extract_pdf_pages(blob_content)
            
            if not pages:
                print(f"No pages extracted from {filename}")
                continue
            
            print(f"Extracted {len(pages)} pages from {filename}")
            
            # Prepare batches for processing
            batch_size = config["processing"]["batch_size"]
            
            all_results = []
            for batch_start in range(0, len(pages), batch_size):
                batch_end = min(batch_start + batch_size, len(pages))
                batch_pages = pages[batch_start:batch_end]
                
                # Split into page numbers and base64 strings
                page_nums = [p[0] for p in batch_pages]
                base64_strings = [p[1] for p in batch_pages]
                
                # Create prompts
                prompts = [pdf_processor.create_extraction_prompt() for _ in range(len(batch_pages))]
                
                print(f"Processing batch of {len(batch_pages)} pages (pages {batch_start+1}-{batch_end})")
                
                # Process batch using specified API type
                if api_type == "batch":
                    raw_results = ai_client.process_batch(base64_strings, prompts)
                else:
                    raw_results = ai_client.process_general(base64_strings, prompts)
                
                # Process the results
                processed_results = pdf_processor.process_batch_results(raw_results, page_nums)
                all_results.extend(processed_results)
                
                print(f"Processed batch {batch_start+1}-{batch_end}")
            
            # Create CSV and determine confidence level
            csv_content, invoice_number, total_amount = pdf_processor.create_csv_for_results(
                all_results, filename
            )
            
            if csv_content:
                # Determine confidence level for folder structure
                is_high_confidence = pdf_processor.has_high_confidence(all_results)
                
                # Determine folder path based on confidence
                if is_high_confidence:
                    folder_path = config["azure_storage"]["high_confidence_folder"]
                    print(f"{filename} has HIGH confidence (≥{config['processing']['confidence_threshold']}%)")
                else:
                    folder_path = config["azure_storage"]["low_confidence_folder"]
                    print(f"{filename} has LOW confidence (<{config['processing']['confidence_threshold']}%)")
                
                # Prepare filenames for upload
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                base_filename = os.path.splitext(filename)[0]
                
                # Upload CSV to blob storage
                csv_blob_name = f"{folder_path}{base_filename}_{invoice_number}_{total_amount}_{timestamp}.csv"
                csv_success, csv_url = storage_helper.upload_to_storage(
                    csv_blob_name,
                    csv_content,
                    "text/csv"
                )
                
                # Upload original PDF to appropriate folder
                source_folder = "source_documents/" + folder_path
                source_blob_name = f"{source_folder}{filename}"
                source_success, source_url = storage_helper.upload_to_storage(
                    source_blob_name,
                    blob_content,
                    "application/pdf"
                )
                
                print(f"CSV upload: {'Success' if csv_success else 'Failed'}")
                print(f"Source PDF upload: {'Success' if source_success else 'Failed'}")
            else:
                print(f"No extractable content found in {filename}")
        
        except Exception as e:
            print(f"Error processing {blob_name}: {str(e)}")
    
    print("Processing complete!")

def main():
    parser = argparse.ArgumentParser(description="Process PDF files using Azure OpenAI")
    parser.add_argument("--apitype", choices=["general", "batch"], required=True, 
                        help="API type to use (general or batch)")
    parser.add_argument("--azure_folder", required=True, 
                        help="Folder path in Azure Blob Storage")
    parser.add_argument("--config", default="config.json", 
                        help="Path to configuration file")
    
    args = parser.parse_args()
    
    try:
        # Load configuration
        config = load_config(args.config)
        
        # Process PDF files
        process_pdf_files(config, args.apitype, args.azure_folder)
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
