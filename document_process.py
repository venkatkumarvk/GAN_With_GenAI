import os
import argparse
from document_process import process_documents

def parse_arguments():
    """
    Parse command-line arguments for document processing
    """
    parser = argparse.ArgumentParser(description='Document Classification Pipeline')
    parser.add_argument(
        '--input', 
        required=True,
        help='Path to input PDF file or directory'
    )
    parser.add_argument(
        '--output', 
        default='./output', 
        help='Path to output directory'
    )
    parser.add_argument(
        '--config', 
        default='config.json', 
        help='Path to configuration file'
    )
    parser.add_argument(
        '--confidence', 
        type=float, 
        default=0.6, 
        help='Confidence threshold for classification'
    )
    return parser.parse_args()

def main():
    """
    Main entry point for document processing
    """
    # Parse command-line arguments
    args = parse_arguments()
    
    # Ensure input and output directories exist
    os.makedirs(args.output, exist_ok=True)
    
    # Process documents in input directory or single file
    if os.path.isdir(args.input):
        # Process all PDFs in directory
        for filename in os.listdir(args.input):
            if filename.lower().endswith(('.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png')):
                input_path = os.path.join(args.input, filename)
                print(f"Processing document: {filename}")
                process_documents(
                    input_path, 
                    args.output, 
                    args.config, 
                    confidence_threshold=args.confidence
                )
    else:
        # Process single file
        process_documents(
            args.input, 
            args.output, 
            args.config, 
            confidence_threshold=args.confidence
        )

if __name__ == "__main__":
    main()
