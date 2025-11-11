import argparse
from document_process import process_documents

def parse_arguments():
    """
    Parse command-line arguments for document processing
    """
    parser = argparse.ArgumentParser(description='Document Processing Pipeline')
    parser.add_argument(
        '--source', 
        choices=['local', 'azure'], 
        default='local', 
        help='Source of documents to process (local filesystem or Azure Blob Storage)'
    )
    parser.add_argument(
        '--config', 
        default='config.json', 
        help='Path to configuration file'
    )
    return parser.parse_args()

def main():
    """
    Main entry point for document processing
    """
    # Parse command-line arguments
    args = parse_arguments()
    
    # Process documents with specified source and configuration
    process_documents(source=args.source, config_path=args.config)

if __name__ == "__main__":
    main()