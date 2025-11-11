import os
import json
import logging
import datetime
from pathlib import Path

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

def setup_logging(log_dir='logs'):
    """
    Configure logging with run-specific, date and time-based log files
    """
    # Create logs directory if it doesn't exist
    os.makedirs(log_dir, exist_ok=True)
    
    # Generate unique log filename with timestamp
    current_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"document_classification_{current_timestamp}.log"
    log_path = os.path.join(log_dir, log_filename)
    
    # Create a logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Clear any existing handlers to prevent duplicate logging
    logger.handlers.clear()
    
    # File Handler
    file_handler = logging.FileHandler(log_path, mode='w')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')
    console_handler.setFormatter(console_formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return log_path  # Return log file path for potential further use

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

def prepare_directories(cfg, source='local'):
    """
    Prepare necessary directories for processing
    """
    # Create base directories
    directories = [
        cfg['paths']['input_dir'],
        cfg['paths']['output_dir'],
        cfg['paths']['reference_dir'],
        cfg['paths'].get('few_shot_examples', 'few_shot_examples'),
        cfg['paths'].get('log_dir', 'logs')
    ]
    
    for dir_path in directories:
        os.makedirs(dir_path, exist_ok=True)
    
    # Create output subdirectories based on categories
    output_dir = cfg['paths']['output_dir']
    for main_category, subcategories in cfg['categories'].items():
        main_category_dir = os.path.join(output_dir, main_category)
        os.makedirs(main_category_dir, exist_ok=True)
        
        for subcategory in subcategories:
            subcategory_dir = os.path.join(main_category_dir, subcategory)
            os.makedirs(subcategory_dir, exist_ok=True)
    
    # Create unclassified directory
    unclassified_dir = os.path.join(output_dir, 'unclassified')
    os.makedirs(unclassified_dir, exist_ok=True)

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