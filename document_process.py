import os
import io
import json
import base64
import shutil
import logging
import traceback
import fitz  # PyMuPDF
from PIL import Image
from datetime import datetime

from helper import (
    load_config, 
    setup_logging,
    get_azure_client, 
    prepare_directories,
    calculate_azure_openai_cost,
    download_azure_blobs,
    upload_azure_blobs
)

def preprocess_image_for_classification(image_bytes):
    """
    Preprocess image to ensure compatibility with GPT-4o
    """
    try:
        # Open image from bytes
        img = Image.open(io.BytesIO(image_bytes))
        
        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Resize image
        img = img.resize((800, 600), Image.LANCZOS)
        
        # Compress image
        buffer = io.BytesIO()
        img.save(buffer, format="PNG", optimize=True, quality=85)
        
        # Convert to base64
        base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        return base64_image
    
    except Exception as e:
        logging.error(f"Image preprocessing error: {e}")
        return None

def prepare_reference_prompt(cfg, reference_dir):
    """
    Generate a detailed prompt using reference document metadata
    """
    reference_details = {}
    
    for main_category in os.listdir(reference_dir):
        main_path = os.path.join(reference_dir, main_category)
        if not os.path.isdir(main_path):
            continue
        
        reference_details[main_category] = {}
        
        for subcategory in os.listdir(main_path):
            subcat_path = os.path.join(main_path, subcategory)
            if not os.path.isdir(subcat_path):
                continue
            
            # Count and list reference documents
            reference_docs = [f for f in os.listdir(subcat_path) 
                              if os.path.isfile(os.path.join(subcat_path, f))]
            
            reference_details[main_category][subcategory] = {
                'document_count': len(reference_docs),
                'document_types': list(set(os.path.splitext(doc)[1] for doc in reference_docs))
            }
    
    return reference_details

def extract_page_image(file_path, page_number):
    """
    Extract image for a specific page from various document types
    """
    try:
        # PDF handling
        if file_path.lower().endswith('.pdf'):
            doc = fitz.open(file_path)
            
            # Validate page number
            if page_number < 0 or page_number >= len(doc):
                logging.error(f"Invalid page number {page_number} for {file_path}")
                return _create_blank_image()
            
            page = doc.load_page(page_number)
            pix = page.get_pixmap()
            
            # Validate pixmap
            if not pix or pix.width <= 0 or pix.height <= 0:
                logging.error(f"Invalid page {page_number} in {file_path}")
                return _create_blank_image()
            
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            doc.close()
        
        # Image handling
        elif file_path.lower().endswith(('.jpg', '.jpeg', '.png')):
            img = Image.open(file_path)
        
        else:
            logging.error(f"Unsupported file type: {file_path}")
            return _create_blank_image()
        
        # Resize and convert to bytes
        img = img.resize((800, 600), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    
    except Exception as e:
        logging.error(f"Error extracting page {page_number} from {file_path}: {e}")
        logging.error(traceback.format_exc())
        return _create_blank_image()

def _create_blank_image():
    """
    Create a blank white image for error cases
    """
    img = Image.new('RGB', (800, 600), color='white')
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def classify_page(document_image, client, deployment_name, cfg):
    """
    Enhanced page-level classification with reference-based validation
    """
    try:
        # Validate and preprocess image
        base64_image = preprocess_image_for_classification(document_image)
        
        if not base64_image:
            logging.error("Failed to preprocess image")
            raise ValueError("Image preprocessing failed")

        # Prepare reference details
        reference_dir = cfg['paths']['reference_dir']
        reference_details = prepare_reference_prompt(cfg, reference_dir)

        # Prepare reference categories for prompt
        categories_str = json.dumps(cfg['categories'], indent=2)
        reference_str = json.dumps(reference_details, indent=2)

        # Detailed page classification prompt
        prompt = f"""
        You are an advanced document classifier specializing in precise categorization 
        based on reference document characteristics.

        REFERENCE DOCUMENT OVERVIEW:
        {reference_str}

        CLASSIFICATION GUIDELINES:
        1. Analyze the document page carefully
        2. Compare with available reference documents
        3. Classify ONLY if there is a strong similarity to reference documents
        4. Be extremely strict in classification

        CLASSIFICATION CRITERIA:
        - Require high visual and structural similarity to reference documents
        - Match document layout, content type, and key characteristics
        - If no clear match exists, classify as 'unknown'

        Available Categories:
        {categories_str}

        Provide your classification in this JSON format:
        {{
            "main_category": "exact main category or 'unknown'",
            "subcategory": "exact subcategory or 'unknown'",
            "confidence_score": 0.0-1.0,
            "reasoning": "Detailed explanation of classification decision, emphasizing reference document similarities"
        }}

        CRITICAL INSTRUCTIONS:
        - Only classify if there is SUBSTANTIAL similarity to reference documents
        - Confidence score should reflect the strength of similarity
        - Provide explicit reasoning linking the page to reference documents
        """

        # Make API call with explicit error handling
        try:
            response = client.chat.completions.create(
                model=deployment_name,
                messages=[
                    {
                        "role": "system",
                        "content": prompt
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Please classify this document image based on reference documents."
                            },
                            {
                                "type": "image",
                                "image_base64": base64_image
                            }
                        ]
                    }
                ],
                response_format={"type": "json_object"},
                max_tokens=300  # Limit response length
            )

            # Token usage tracking
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens

            # Calculate cost 
            token_cost = calculate_azure_openai_cost(
                input_tokens, 
                output_tokens, 
                cfg
            )

            # Extract and parse response
            result = json.loads(response.choices[0].message.content)

            # Extract and validate classification
            main_category = result.get('main_category', 'unknown')
            subcategory = result.get('subcategory', 'unknown')
            confidence_score = float(result.get('confidence_score', 0.0))
            reasoning = result.get('reasoning', 'No reasoning provided')

            # Strict validation against reference documents
            if (main_category == 'unknown' or 
                main_category not in cfg['categories'] or 
                subcategory not in cfg['categories'].get(main_category, [])):
                # Fallback to unknown if no clear match
                main_category = 'unknown'
                subcategory = 'unknown'
                confidence_score = 0.0

            # Log detailed classification
            logging.info(f"Classification Details:\n" + json.dumps({
                'main_category': main_category,
                'subcategory': subcategory,
                'confidence_score': confidence_score,
                'reasoning': reasoning
            }, indent=2))

            return main_category, subcategory, confidence_score, reasoning, token_cost

        except Exception as api_error:
            logging.error(f"API Classification Error: {api_error}")
            logging.error(traceback.format_exc())
            
            return 'unknown', 'unknown', 0.0, f"Classification error: {str(api_error)}", None

    except Exception as e:
        logging.error(f"Page classification error: {e}")
        logging.error(traceback.format_exc())
        
        return 'unknown', 'unknown', 0.0, f"Error in page classification: {str(e)}", None

def process_documents(source='local', config_path='config.json'):
    """
    Comprehensive document processing pipeline
    """
    try:
        # Setup logging
        setup_logging()
        
        # Load configuration
        cfg = load_config(config_path)
        
        # Prepare directories
        prepare_directories(cfg)
        
        # If source is Azure, download input files
        if source == 'azure':
            download_azure_blobs(
                cfg, 
                cfg['azure_storage']['input_container'], 
                cfg['paths']['input_dir']
            )
        
        # Initialize Azure client
        client, deployment = get_azure_client(cfg)
        
        # Processing statistics
        stats = {
            'total_documents': 0,
            'total_pages': 0,
            'classified_pages': 0,
            'unclassified_pages': 0,
            'total_token_cost': 0.0,
            'total_input_tokens': 0,
            'total_output_tokens': 0
        }
        
        # Input directory
        input_dir = cfg['paths']['input_dir']
        
        # Process each document
        for fname in os.listdir(input_dir):
            fpath = os.path.join(input_dir, fname)
            
            # Skip directories and hidden files
            if not os.path.isfile(fpath) or fname.startswith('.'):
                continue

            # Determine file type
            file_type = os.path.splitext(fname)[1].lower()
            
            # Skip non-processable file types
            if file_type not in ['.pdf', '.jpg', '.jpeg', '.png']:
                logging.warning(f"Unsupported file type: {fname}")
                continue

            # Count total documents
            stats['total_documents'] += 1

            # Determine total pages
            total_pages = 1 if file_type != '.pdf' else len(fitz.open(fpath))
            stats['total_pages'] += total_pages

            # Classification tracking
            classified_pages = []
            unclassified_pages = list(range(total_pages))

            # Process each page
            for page_num in range(total_pages):
                # Extract page image
                page_image = extract_page_image(fpath, page_num)
                
                # Classify page
                main_cat, sub_cat, confidence, reasoning, token_cost = classify_page(
                    page_image, client, deployment, cfg
                )

                # Update token cost tracking
                if token_cost:
                    stats['total_token_cost'] += token_cost['total_cost']
                    stats['total_input_tokens'] += token_cost['input_tokens']
                    stats['total_output_tokens'] += token_cost['output_tokens']

                # Check classification confidence
                if confidence >= cfg['classification'].get('confidence_threshold', 0.5):
                    classified_pages.append({
                        'page_num': page_num,
                        'main_category': main_cat,
                        'subcategory': sub_cat,
                        'confidence': confidence
                    })
                    
                    # Remove from unclassified pages
                    unclassified_pages.remove(page_num)
                    stats['classified_pages'] += 1

            # Log processing results
            logging.info(f"Document {fname} Processing Summary:")
            logging.info(f"Total Pages: {total_pages}")
            logging.info(f"Classified Pages: {len(classified_pages)}")
            logging.info(f"Unclassified Pages: {len(unclassified_pages)}")

        # Log overall processing statistics
        logging.info("Processing Session Statistics:")
        logging.info(json.dumps(stats, indent=2))

        # If source is Azure, upload processed files
        if source == 'azure':
            upload_azure_blobs(
                cfg, 
                cfg['paths']['output_dir'], 
                cfg['azure_storage']['output_container']
            )

        print("✅ Document Processing Complete")
        print(f"📊 Total Token Cost: ${stats['total_token_cost']:.4f}")
        print(f"📈 Total Input Tokens: {stats['total_input_tokens']}")
        print(f"📉 Total Output Tokens: {stats['total_output_tokens']}")

    except Exception as e:
        logging.critical(f"Critical processing error: {e}")
        logging.critical(traceback.format_exc())
        print(f"❌ Document Processing Failed: {e}")
