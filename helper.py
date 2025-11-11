import os
import json
import logging
import hashlib
from openai import AzureOpenAI
from azure.storage.blob import BlobServiceClient

def load_config(config_path="config.json"):
    """
    Load configuration from JSON file
    """
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
        return cfg
    except FileNotFoundError:
        logging.error(f"Config file not found: {config_path}")
        raise
    except json.JSONDecodeError:
        logging.error(f"Invalid JSON in config file: {config_path}")
        raise

def setup_logging(log_file='document_processing.log'):
    """
    Configure logging with both console and file handlers
    """
    # Configure logging
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s: %(message)s',
        handlers=[
            logging.FileHandler(log_file, mode='a'),
            logging.StreamHandler()
        ]
    )

def calculate_azure_openai_cost(input_tokens, output_tokens, cfg, model='gpt-4o', use_cached=False):
    """
    Calculate the cost of Azure OpenAI API usage
    """
    try:
        pricing = cfg['token_pricing'].get(model, cfg['token_pricing']['gpt-4o'])
        
        # Calculate input token cost
        input_cost = (input_tokens / 1_000_000) * (
            pricing['cached_input']['price_per_million'] if use_cached 
            else pricing['input']['price_per_million']
        )
        
        # Calculate output token cost
        output_cost = (output_tokens / 1_000_000) * pricing['output']['price_per_million']
        
        # Total cost
        total_cost = input_cost + output_cost
        
        return {
            'model': model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'input_cost': round(input_cost, 4),
            'output_cost': round(output_cost, 4),
            'total_cost': round(total_cost, 4),
            'use_cached': use_cached
        }
    except Exception as e:
        logging.error(f"Token cost calculation error: {e}")
        return {
            'model': model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'input_cost': 0,
            'output_cost': 0,
            'total_cost': 0,
            'error': str(e)
        }

def get_azure_client(cfg):
    """
    Initialize Azure OpenAI client 
    """
    try:
        client = AzureOpenAI(
            api_key=cfg["azure_openai"]["api_key"],
            api_version=cfg["azure_openai"]["api_version"],
            azure_endpoint=cfg["azure_openai"]["endpoint"]
        )
        return client, cfg["azure_openai"]["deployment_name"]
    except Exception as e:
        logging.critical(f"Azure client initialization error: {e}")
        raise

def prepare_directories(cfg):
    """
    Prepare necessary directories for processing
    """
    directories = [
        cfg['paths']['input_dir'],
        cfg['paths']['output_dir'],
        cfg['paths']['reference_dir'],
        os.path.join(cfg['paths']['output_dir'], 'source'),
        os.path.join(cfg['paths']['output_dir'], 'classified'),
        os.path.join(cfg['paths']['output_dir'], 'unclassified')
    ]
    
    for dir_path in directories:
        os.makedirs(dir_path, exist_ok=True)

def download_azure_blobs(cfg, container_name, local_dir):
    """
    Download blobs from an Azure Storage container to local directory
    """
    try:
        blob_service_client = BlobServiceClient.from_connection_string(
            cfg['azure_storage']['connection_string']
        )
        container_client = blob_service_client.get_container_client(container_name)
        
        # Ensure local directory exists
        os.makedirs(local_dir, exist_ok=True)
        
        # List and download blobs
        for blob in container_client.list_blobs():
            blob_client = container_client.get_blob_client(blob.name)
            local_file_path = os.path.join(local_dir, blob.name)
            
            # Create subdirectories if needed
            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
            
            # Download blob
            with open(local_file_path, "wb") as download_file:
                download_file.write(blob_client.download_blob().readall())
            
            logging.info(f"Downloaded: {blob.name}")
    
    except Exception as e:
        logging.error(f"Azure Blob download error: {e}")
        raise

def upload_azure_blobs(cfg, local_dir, container_name):
    """
    Upload files from local directory to Azure Storage container
    """
    try:
        blob_service_client = BlobServiceClient.from_connection_string(
            cfg['azure_storage']['connection_string']
        )
        container_client = blob_service_client.get_container_client(container_name)
        
        # Walk through local directory
        for root, _, files in os.walk(local_dir):
            for file in files:
                local_path = os.path.join(root, file)
                
                # Create blob path (preserve directory structure)
                relative_path = os.path.relpath(local_path, local_dir)
                blob_name = relative_path
                
                # Upload blob
                blob_client = container_client.get_blob_client(blob_name)
                with open(local_path, "rb") as data:
                    blob_client.upload_blob(data, overwrite=True)
                
                logging.info(f"Uploaded: {blob_name}")
    
    except Exception as e:
        logging.error(f"Azure Blob upload error: {e}")
        raise
