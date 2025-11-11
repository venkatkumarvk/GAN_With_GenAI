import os
import io
import json
import base64
import logging
import traceback
from pathlib import Path
from datetime import datetime

import cv2
import numpy as np
import pdf2image

from helper import (
    load_config, 
    setup_logging,
    get_azure_client, 
    prepare_directories,
    calculate_azure_openai_cost
)

class DocumentClassifier:
    def __init__(self, cfg):
        """
        Initialize document classifier with configuration
        """
        self.cfg = cfg
        self.client, self.deployment = self._initialize_client()
        self.setup_logging()
        
        # Dynamic category management
        self.all_categories = self._flatten_categories()
        self.reference_docs = self._load_reference_documents()
        self.few_shot_examples = self._prepare_few_shot_examples()

    def _flatten_categories(self):
        """
        Flatten nested categories into a single list
        """
        flattened = ['unclassified']
        for main_category, subcategories in self.cfg['categories'].items():
            flattened.extend(subcategories)
        return flattened

    def _initialize_client(self):
        """
        Initialize Azure OpenAI client
        """
        return get_azure_client(self.cfg)

    def setup_logging(self):
        """
        Configure logging
        """
        setup_logging()
        self.log_file = self.cfg.get('paths', {}).get('log_file', 'document_classification.log')

    def _load_reference_documents(self):
        """
        Load reference documents from reference directory
        Dynamically handles all categories
        """
        reference_docs = {cat: [] for cat in self.all_categories}
        reference_dir = self.cfg['paths']['reference_dir']
        
        # Check if reference directory exists
        if not os.path.exists(reference_dir):
            logging.warning(f"Reference directory not found: {reference_dir}")
            return reference_docs

        for category_group, subcategories in self.cfg['categories'].items():
            for subcategory in subcategories:
                subcategory_path = os.path.join(reference_dir, category_group, subcategory)
                
                if not os.path.exists(subcategory_path):
                    logging.warning(f"No reference documents for category: {subcategory}")
                    continue
                
                # Load documents
                for doc_name in os.listdir(subcategory_path):
                    doc_path = os.path.join(subcategory_path, doc_name)
                    
                    # Support PDF and image files
                    if doc_name.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg')):
                        reference_docs[subcategory].append(doc_path)
        
        return reference_docs

    def _prepare_few_shot_examples(self):
        """
        Prepare few-shot learning examples
        Converts PDFs to images if needed
        """
        few_shot_examples = {cat: [] for cat in self.all_categories}
        
        for category, docs in self.reference_docs.items():
            for doc_path in docs:
                # Convert PDF to images or use existing images
                if doc_path.lower().endswith('.pdf'):
                    pdf_images = pdf2image.convert_from_path(doc_path)
                    for img in pdf_images[:2]:  # Use first two pages as examples
                        temp_img_path = f"temp_{category}_example.png"
                        img.save(temp_img_path)
                        few_shot_examples[category].append(temp_img_path)
                else:
                    few_shot_examples[category].append(doc_path)
        
        return few_shot_examples

    def encode_image(self, image_path):
        """
        Encode image to base64
        """
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def preprocess_image(self, image_path):
        """
        Advanced image preprocessing
        """
        try:
            # Read image with OpenCV
            img = cv2.imread(image_path)
            
            # Preprocessing techniques using OpenCV
            preprocessed_images = []
            
            # Original image
            preprocessed_images.append(('original', img))
            
            # Grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            preprocessed_images.append(('grayscale', gray))
            
            # Contrast Enhancement
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            contrast_enhanced = clahe.apply(gray)
            preprocessed_images.append(('contrast_enhanced', contrast_enhanced))
            
            # Encode preprocessed images
            base64_images = []
            for name, preprocessed_img in preprocessed_images:
                _, buffer = cv2.imencode('.png', preprocessed_img)
                base64_img = base64.b64encode(buffer).decode('utf-8')
                base64_images.append({
                    'type': name,
                    'image': base64_img
                })
            
            return base64_images
        
        except Exception as e:
            logging.error(f"Image preprocessing error: {e}")
            return None

    def classify_page(self, image_path):
        """
        Dynamic few-shot learning based document classification
        """
        try:
            # Preprocess images
            preprocessed_images = self.preprocess_image(image_path)
            
            if not preprocessed_images:
                logging.error("Failed to preprocess image")
                return 'unclassified', 0.0, 'Preprocessing failed'

            # Prepare messages for few-shot learning
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an advanced document classifier. "
                        "Classify the input image precisely based on reference documents. "
                        f"Categories: {', '.join(self.all_categories)}"
                    )
                }
            ]

            # Add few-shot examples
            for category, example_paths in self.few_shot_examples.items():
                if not example_paths:
                    continue
                
                for example_path in example_paths[:2]:  # Limit to 2 examples per category
                    messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Example of {category}"},
                            {"type": "image", "image_base64": self.encode_image(example_path)}
                        ]
                    })
                    messages.append({
                        "role": "assistant",
                        "content": json.dumps({
                            "label": category, 
                            "confidence": 95, 
                            "reasoning": f"Typical {category} document structure"
                        })
                    })

            # Add target page with multiple preprocessed images
            user_content = [
                {"type": "text", "text": "Classify this page. Compare across different preprocessings:"}
            ]
            
            for prep_img in preprocessed_images:
                user_content.append({
                    "type": "image",
                    "image_base64": prep_img['image'],
                    "description": f"Preprocessed image: {prep_img['type']}"
                })
            
            messages.append({"role": "user", "content": user_content})

            # Make API call
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=300
            )

            # Parse response
            result_text = response.choices[0].message.content.strip()
            result = json.loads(result_text)

            # Extract details
            label = result.get('label', 'unclassified').lower()
            confidence = float(result.get('confidence', 0))
            reasoning = result.get('reasoning', 'No detailed reasoning')

            # Validate label
            if label not in self.all_categories:
                label = 'unclassified'
                confidence = 0.0

            # Logging
            logging.info(json.dumps({
                'image': os.path.basename(image_path),
                'label': label,
                'confidence': confidence,
                'reasoning': reasoning
            }, indent=2))

            return label, confidence, reasoning

        except Exception as e:
            logging.error(f"Classification error for {image_path}: {e}")
            logging.error(traceback.format_exc())
            return 'unclassified', 0.0, str(e)

    def process_pdf(self, pdf_path):
        """
        Process entire PDF file
        """
        try:
            pdf_name = Path(pdf_path).stem
            output_dir = self.cfg['paths']['output_dir']

            # Convert PDF to images
            pages = pdf2image.convert_from_path(pdf_path, dpi=300)

            # Tracking statistics
            stats = {
                'total_pages': len(pages),
                'classified_pages': 0,
                'unclassified_pages': 0,
                'page_classifications': {}
            }

            # Process each page
            for page_no, page_image in enumerate(pages, start=1):
                # Save temporary page image
                temp_image = f"temp_page_{page_no}.png"
                page_image.save(temp_image, "PNG")

                # Classify page
                label, confidence, reasoning = self.classify_page(temp_image)

                # Determine main category
                main_category = next(
                    (cat for cat, subcats in self.cfg['categories'].items() 
                     if label in subcats), 
                    'unclassified'
                )

                # Update stats
                if label not in stats['page_classifications']:
                    stats['page_classifications'][label] = 0
                stats['page_classifications'][label] += 1

                if label == 'unclassified':
                    stats['unclassified_pages'] += 1
                else:
                    stats['classified_pages'] += 1

                # Determine output folder
                output_folder = os.path.join(output_dir, main_category, label)
                os.makedirs(output_folder, exist_ok=True)

                # Save classified page
                output_pdf_path = os.path.join(
                    output_folder, 
                    f"{pdf_name}_page_{page_no}_{label}.pdf"
                )
                page_image.save(output_pdf_path, "PDF")

                # Log classification
                self.log_classification(pdf_name, page_no, label, confidence, reasoning)

                # Clean up temporary image
                os.remove(temp_image)

            # Log processing summary
            logging.info(f"PDF Processing Summary: {pdf_name}")
            logging.info(json.dumps(stats, indent=2))

            return stats

        except Exception as e:
            logging.error(f"Error processing PDF {pdf_path}: {e}")
            logging.error(traceback.format_exc())
            return None

    def log_classification(self, pdf_name, page_no, label, confidence, reasoning):
        """
        Log detailed classification results
        """
        with open(self.log_file, 'a') as f:
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'pdf_name': pdf_name,
                'page_no': page_no,
                'label': label,
                'confidence': confidence,
                'reasoning': reasoning
            }
            f.write(json.dumps(log_entry) + '\n')

def process_documents(source='local', config_path='config.json'):
    """
    Main document processing function
    """
    try:
        # Load configuration
        cfg = load_config(config_path)
        
        # Prepare directories
        prepare_directories(cfg)
        
        # Initialize classifier
        classifier = DocumentClassifier(cfg)
        
        # Input directory
        input_dir = cfg['paths']['input_dir']
        
        # Process PDFs
        for filename in os.listdir(input_dir):
            if filename.lower().endswith('.pdf'):
                pdf_path = os.path.join(input_dir, filename)
                classifier.process_pdf(pdf_path)

        print("✅ Document Processing Complete")

    except Exception as e:
        logging.critical(f"Document processing error: {e}")
        print(f"❌ Document Processing Failed: {e}")

if __name__ == "__main__":
    process_documents()