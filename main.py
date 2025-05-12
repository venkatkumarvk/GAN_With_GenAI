import os
import io
import json
import streamlit as st
import pandas as pd
from datetime import datetime
import gc

from helper_functions import (
    load_config, 
    get_blob_service_client,
    list_folders_in_container,
    list_blobs_in_folder,
    download_blob_to_memory,
    upload_blob,
    read_csv_from_blob,
    render_pdf_preview,
    convert_pdf_to_base64,
    display_pdf_viewer,
    parse_filename_components,
    match_source_and_processed_files,
    update_extraction_data
)

# Page configuration
st.set_page_config(
    page_title="Financial Data Extractor",
    page_icon="📊",
    layout="wide"
)

st.title("Financial Data Extractor")

# Initialize session state for persistent data
if 'config' not in st.session_state:
    st.session_state.config = None
if 'blob_service_client' not in st.session_state:
    st.session_state.blob_service_client = None
if 'confidence_level' not in st.session_state:
    st.session_state.confidence_level = "high_confidence"
if 'selected_source_folder' not in st.session_state:
    st.session_state.selected_source_folder = None
if 'selected_processed_folder' not in st.session_state:
    st.session_state.selected_processed_folder = None
if 'matched_files' not in st.session_state:
    st.session_state.matched_files = []
if 'selected_pdf_file' not in st.session_state:
    st.session_state.selected_pdf_file = None
if 'selected_csv_file' not in st.session_state:
    st.session_state.selected_csv_file = None
if 'csv_data' not in st.session_state:
    st.session_state.csv_data = None
if 'edited_csv_data' not in st.session_state:
    st.session_state.edited_csv_data = None
if 'edit_mode' not in st.session_state:
    st.session_state.edit_mode = False

# Load configuration
if not st.session_state.config:
    config = load_config()
    if config:
        st.session_state.config = config
        # Initialize blob service client
        if 'azure_storage_connection_string' in config:
            st.session_state.blob_service_client = get_blob_service_client(config['azure_storage_connection_string'])
        else:
            st.error("Azure Storage connection string not found in configuration")

# Main navigation sidebar
st.sidebar.title("Navigation")
main_menu = st.sidebar.radio(
    "Menu",
    ["View Results", "Manual Edit", "Bulk Upload"],
    key="main_menu"
)

# Confidence level selector (for View Results and Manual Edit)
if main_menu in ["View Results", "Manual Edit"]:
    confidence_level = st.sidebar.radio(
        "Confidence Level",
        ["High Confidence", "Low Confidence"],
        key="confidence_radio"
    )
    
    # Update session state
    if confidence_level == "High Confidence":
        st.session_state.confidence_level = "high_confidence"
    else:
        st.session_state.confidence_level = "low_confidence"

# Handle main content based on navigation
if main_menu == "View Results":
    st.header("View Extraction Results")
    
    if st.session_state.blob_service_client and st.session_state.config:
        # Get container names from config
        source_container = st.session_state.config.get('source_container', '')
        processed_container = st.session_state.config.get('processed_container', '')
        
        if not source_container or not processed_container:
            st.error("Source or processed container not specified in configuration")
        else:
            # List folders in containers
            confidence_folder = st.session_state.confidence_level + "/"
            
            # Source container folders
            source_folders = list_folders_in_container(
                st.session_state.blob_service_client,
                source_container,
                confidence_folder
            )
            
            # Processed container folders
            processed_folders = list_folders_in_container(
                st.session_state.blob_service_client,
                processed_container,
                confidence_folder
            )
            
            # Display folder selectors
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Source Folders")
                selected_source_folder = st.selectbox(
                    "Select Source Folder",
                    source_folders,
                    key="source_folder_select"
                )
                
                if selected_source_folder:
                    st.session_state.selected_source_folder = f"{confidence_folder}{selected_source_folder}"
            
            with col2:
                st.subheader("Processed Folders")
                selected_processed_folder = st.selectbox(
                    "Select Processed Folder",
                    processed_folders,
                    key="processed_folder_select"
                )
                
                if selected_processed_folder:
                    st.session_state.selected_processed_folder = f"{confidence_folder}{selected_processed_folder}"
            
            # List files in selected folders
            if st.session_state.selected_source_folder and st.session_state.selected_processed_folder:
                # Get files in source folder
                source_pdfs, _ = list_blobs_in_folder(
                    st.session_state.blob_service_client, 
                    source_container, 
                    st.session_state.selected_source_folder
                )
                
                # Get files in processed folder
                _, processed_csvs = list_blobs_in_folder(
                    st.session_state.blob_service_client, 
                    processed_container, 
                    st.session_state.selected_processed_folder
                )
                
                # Match source PDFs with processed CSVs
                matched_files = match_source_and_processed_files(source_pdfs, processed_csvs)
                st.session_state.matched_files = matched_files
                
                # Display matched files
                st.subheader("Matched Files")
                
                if matched_files:
                    # Create a DataFrame for display
                    display_data = []
                    for match in matched_files:
                        display_data.append({
                            "PDF File": match["pdf_name"],
                            "Matching CSVs": len(match["matching_csvs"]),
                            "Status": "✅ Processed" if match["matching_csvs"] else "❌ Not Processed"
                        })
                    
                    matched_df = pd.DataFrame(display_data)
                    st.dataframe(matched_df, use_container_width=True)
                    
                    # File selection for preview
                    st.subheader("Preview Files")
                    
                    selected_pdf_idx = st.selectbox(
                        "Select PDF to preview",
                        range(len(matched_files)),
                        format_func=lambda x: matched_files[x]["pdf_name"],
                        key="pdf_preview_select"
                    )
                    
                    selected_match = matched_files[selected_pdf_idx]
                    st.session_state.selected_pdf_file = selected_match["pdf_file"]
                    
                    if selected_match["matching_csvs"]:
                        selected_csv_idx = st.selectbox(
                            "Select CSV to preview",
                            range(len(selected_match["matching_csvs"])),
                            format_func=lambda x: os.path.basename(selected_match["matching_csvs"][x]),
                            key="csv_preview_select"
                        )
                        
                        st.session_state.selected_csv_file = selected_match["matching_csvs"][selected_csv_idx]
                    else:
                        st.session_state.selected_csv_file = None
                        st.warning("No matching CSV files found for this PDF")
                    
                    # Preview selected files
                    if st.button("Show Previews"):
                        # Create tabs for PDF and CSV preview
                        preview_tabs = st.tabs(["PDF Preview", "Extraction Results", "Evaluation Results"])
                        
                        with preview_tabs[0]:  # PDF Preview
                            if st.session_state.selected_pdf_file:
                                pdf_content = download_blob_to_memory(
                                    st.session_state.blob_service_client,
                                    source_container,
                                    st.session_state.selected_pdf_file
                                )
                                
                                if pdf_content:
                                    st.write(f"#### Preview of {os.path.basename(st.session_state.selected_pdf_file)}")
                                    base64_pdf = convert_pdf_to_base64(pdf_content)
                                    display_pdf_viewer(base64_pdf)
                                else:
                                    st.error("Could not download PDF file")
                        
                        with preview_tabs[1]:  # Extraction Results
                            if st.session_state.selected_csv_file:
                                csv_data = read_csv_from_blob(
                                    st.session_state.blob_service_client,
                                    processed_container,
                                    st.session_state.selected_csv_file
                                )
                                
                                if csv_data is not None:
                                    st.session_state.csv_data = csv_data
                                    st.write(f"#### Extraction results for {os.path.basename(st.session_state.selected_csv_file)}")
                                    st.dataframe(csv_data, use_container_width=True)
                                    
                                    # Download button for CSV
                                    csv_data_download = csv_data.to_csv(index=False)
                                    st.download_button(
                                        label="Download CSV",
                                        data=csv_data_download,
                                        file_name=os.path.basename(st.session_state.selected_csv_file),
                                        mime="text/csv"
                                    )
                                else:
                                    st.error("Could not read CSV file")
                        
                        with preview_tabs[2]:  # Evaluation Results
                            if st.session_state.csv_data is not None:
                                # Calculate and display confidence metrics
                                st.write("#### Confidence Metrics")
                                
                                # Check which confidence columns are available
                                confidence_cols = [col for col in st.session_state.csv_data.columns if 'Confidence' in col]
                                
                                if confidence_cols:
                                    # Calculate average confidence for each field
                                    confidence_metrics = {}
                                    for col in confidence_cols:
                                        field_name = col.replace(' Confidence', '')
                                        confidence_values = pd.to_numeric(st.session_state.csv_data[col], errors='coerce')
                                        avg_confidence = confidence_values.mean()
                                        confidence_metrics[field_name] = avg_confidence
                                    
                                    # Create metrics DataFrame
                                    metrics_df = pd.DataFrame({
                                        'Field': list(confidence_metrics.keys()),
                                        'Average Confidence (%)': [round(val, 2) for val in confidence_metrics.values()]
                                    })
                                    
                                    # Sort by confidence
                                    metrics_df = metrics_df.sort_values('Average Confidence (%)', ascending=False)
                                    
                                    # Display metrics table
                                    st.dataframe(metrics_df, use_container_width=True)
                                    
                                    # Create a bar chart of confidence scores
                                    st.bar_chart(metrics_df.set_index('Field'))
                                else:
                                    st.warning("No confidence metrics found in the CSV data")
                else:
                    st.info("No matched files found. Please check the source and processed folders.")
            else:
                st.info("Please select both source and processed folders to view files")
    else:
        st.error("Blob service client not initialized. Please check your configuration.")

elif main_menu == "Manual Edit":
    st.header("Manual Edit Extraction Results")
    
    if st.session_state.blob_service_client and st.session_state.config:
        # Get container names from config
        source_container = st.session_state.config.get('source_container', '')
        processed_container = st.session_state.config.get('processed_container', '')
        
        if not source_container or not processed_container:
            st.error("Source or processed container not specified in configuration")
        else:
            # List folders in containers
            confidence_folder = st.session_state.confidence_level + "/"
            
            # Source container folders
            source_folders = list_folders_in_container(
                st.session_state.blob_service_client,
                source_container,
                confidence_folder
            )
            
            # Processed container folders
            processed_folders = list_folders_in_container(
                st.session_state.blob_service_client,
                processed_container,
                confidence_folder
            )
            
            # Display folder selectors
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Source Folders")
                selected_source_folder = st.selectbox(
                    "Select Source Folder",
                    source_folders,
                    key="edit_source_folder_select"
                )
                
                if selected_source_folder:
                    st.session_state.selected_source_folder = f"{confidence_folder}{selected_source_folder}"
            
            with col2:
                st.subheader("Processed Folders")
                selected_processed_folder = st.selectbox(
                    "Select Processed Folder",
                    processed_folders,
                    key="edit_processed_folder_select"
                )
                
                if selected_processed_folder:
                    st.session_state.selected_processed_folder = f"{confidence_folder}{selected_processed_folder}"
            
            # List files in selected folders
            if st.session_state.selected_source_folder and st.session_state.selected_processed_folder:
                # Get files in source folder
                source_pdfs, _ = list_blobs_in_folder(
                    st.session_state.blob_service_client, 
                    source_container, 
                    st.session_state.selected_source_folder
                )
                
                # Get files in processed folder
                _, processed_csvs = list_blobs_in_folder(
                    st.session_state.blob_service_client, 
                    processed_container, 
                    st.session_state.selected_processed_folder
                )
                
                # Match source PDFs with processed CSVs
                matched_files = match_source_and_processed_files(source_pdfs, processed_csvs)
                st.session_state.matched_files = matched_files
                
                # Display matched files
                st.subheader("Select File to Edit")
                
                if matched_files:
                    # Create a DataFrame for display
                    display_data = []
                    for match in matched_files:
                        display_data.append({
                            "PDF File": match["pdf_name"],
                            "Matching CSVs": len(match["matching_csvs"]),
                            "Status": "✅ Processed" if match["matching_csvs"] else "❌ Not Processed"
                        })
                    
                    matched_df = pd.DataFrame(display_data)
                    st.dataframe(matched_df, use_container_width=True)
                    
                    # File selection for editing
                    selected_pdf_idx = st.selectbox(
                        "Select PDF",
                        range(len(matched_files)),
                        format_func=lambda x: matched_files[x]["pdf_name"],
                        key="pdf_edit_select"
                    )
                    
                    selected_match = matched_files[selected_pdf_idx]
                    st.session_state.selected_pdf_file = selected_match["pdf_file"]
                    
                    if selected_match["matching_csvs"]:
                        selected_csv_idx = st.selectbox(
                            "Select CSV",
                            range(len(selected_match["matching_csvs"])),
                            format_func=lambda x: os.path.basename(selected_match["matching_csvs"][x]),
                            key="csv_edit_select"
                        )
                        
                        st.session_state.selected_csv_file = selected_match["matching_csvs"][selected_csv_idx]
                        
                        # Load the CSV data for editing
                        if st.button("Load for Editing"):
                            # Load the PDF for reference
                            pdf_content = download_blob_to_memory(
                                st.session_state.blob_service_client,
                                source_container,
                                st.session_state.selected_pdf_file
                            )
                            
                            # Load the CSV data
                            csv_data = read_csv_from_blob(
                                st.session_state.blob_service_client,
                                processed_container,
                                st.session_state.selected_csv_file
                            )
                            
                            if csv_data is not None and pdf_content is not None:
                                st.session_state.csv_data = csv_data
                                st.session_state.edited_csv_data = csv_data.copy()
                                st.session_state.edit_mode = True
                                st.success("Data loaded for editing")
                            else:
                                st.error("Could not load data for editing")
                    else:
                        st.warning("No matching CSV files found for this PDF")
                else:
                    st.info("No matched files found. Please check the source and processed folders.")
            
            # Display editing interface if data is loaded
            if st.session_state.edit_mode and st.session_state.edited_csv_data is not None:
                st.subheader("Edit Extraction Results")
                
                # Create tabs for the editing view
                edit_tabs = st.tabs(["PDF Reference", "Editing Interface"])
                
                with edit_tabs[0]:  # PDF Reference
                    pdf_content = download_blob_to_memory(
                        st.session_state.blob_service_client,
                        source_container,
                        st.session_state.selected_pdf_file
                    )
                    
                    if pdf_content:
                        st.write(f"#### Reference: {os.path.basename(st.session_state.selected_pdf_file)}")
                        base64_pdf = convert_pdf_to_base64(pdf_content)
                        display_pdf_viewer(base64_pdf)
                
                with edit_tabs[1]:  # Editing Interface
                    st.write(f"#### Editing: {os.path.basename(st.session_state.selected_csv_file)}")
                    
                    # Get available pages
                    if 'Page' in st.session_state.edited_csv_data.columns:
                        pages = st.session_state.edited_csv_data['Page'].unique()
                        
                        # Page selector
                        # Page selector
                        selected_page = st.selectbox(
                            "Select Page to Edit",
                            pages,
                            key="edit_page_select"
                        )
                        
                        # Get the row for the selected page
                        page_data = st.session_state.edited_csv_data[st.session_state.edited_csv_data['Page'] == selected_page]
                        
                        if not page_data.empty:
                            # Display current data for this page
                            st.write("#### Current Data:")
                            st.dataframe(page_data, use_container_width=True)
                            
                            # Create the editing form
                            with st.form(key=f"edit_form_{selected_page}"):
                                # Define the fields we want to be editable
                                editable_fields = [
                                    "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
                                    "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
                                    "Freight", "Salestax", "Total"
                                ]
                                
                                # Create form fields for each editable field
                                form_values = {}
                                for field in editable_fields:
                                    if field in page_data.columns:
                                        # Get current value and confidence
                                        current_value = page_data[field].iloc[0]
                                        confidence_col = f"{field} Confidence"
                                        confidence = page_data[confidence_col].iloc[0] if confidence_col in page_data.columns else "N/A"
                                        
                                        # Highlight fields with low confidence
                                        field_label = field
                                        if confidence != "N/A" and float(confidence) < 90:
                                            field_label = f"{field} ⚠️ ({confidence}% confidence)"
                                        
                                        # Create text input for editing
                                        form_values[field] = st.text_input(
                                            field_label,
                                            value=current_value,
                                            key=f"edit_{field}_{selected_page}"
                                        )
                                
                                # Submit button
                                submit = st.form_submit_button("Save Changes")
                                
                                if submit:
                                    # Apply changes to the dataframe
                                    changes_made = False
                                    for field, value in form_values.items():
                                        # Check if the value changed
                                        if str(page_data[field].iloc[0]) != str(value):
                                            # Update the value in the dataframe
                                            if update_extraction_data(
                                                st.session_state.edited_csv_data,
                                                field,
                                                selected_page,
                                                value
                                            ):
                                                changes_made = True
                                    
                                    if changes_made:
                                        st.success("Changes saved")
                                    else:
                                        st.info("No changes made")
                        else:
                            st.warning(f"No data found for page {selected_page}")
                    else:
                        st.error("Page column not found in the data")
                    
                    # Save all changes to blob storage
                    final_container = st.session_state.config.get('final_container', '')
                    if final_container:
                        st.subheader("Save Edited Data")
                        
                        save_col1, save_col2 = st.columns(2)
                        
                        with save_col1:
                            # Option to specify a folder in the final container
                            final_folder = st.text_input(
                                "Final Folder (optional)",
                                value=st.session_state.confidence_level,
                                key="final_folder_input"
                            )
                            
                            if not final_folder.endswith('/') and final_folder:
                                final_folder += '/'
                        
                        with save_col2:
                            # Option to add a suffix to the filename
                            filename_suffix = st.text_input(
                                "Filename Suffix (optional)",
                                value="_edited",
                                key="filename_suffix_input"
                            )
                        
                        # Button to save changes
                        if st.button("Save to Final Container", type="primary"):
                            try:
                                # Get the original filename
                                original_csv_name = os.path.basename(st.session_state.selected_csv_file)
                                
                                # Create the new filename with suffix
                                base_name, ext = os.path.splitext(original_csv_name)
                                new_csv_name = f"{base_name}{filename_suffix}{ext}"
                                
                                # Create the full blob path
                                new_blob_path = f"{final_folder}{new_csv_name}"
                                
                                # Convert the edited dataframe to CSV
                                csv_data = st.session_state.edited_csv_data.to_csv(index=False)
                                
                                # Upload to the final container
                                success, url = upload_blob(
                                    st.session_state.blob_service_client,
                                    final_container,
                                    new_blob_path,
                                    csv_data,
                                    "text/csv"
                                )
                                
                                if success:
                                    st.success(f"Successfully saved to {new_blob_path} in {final_container}")
                                    
                                    # Also copy the PDF to the final container
                                    pdf_content = download_blob_to_memory(
                                        st.session_state.blob_service_client,
                                        source_container,
                                        st.session_state.selected_pdf_file
                                    )
                                    
                                    if pdf_content:
                                        # Get the original PDF filename
                                        original_pdf_name = os.path.basename(st.session_state.selected_pdf_file)
                                        
                                        # Create the full blob path for the PDF
                                        new_pdf_path = f"{final_folder}{original_pdf_name}"
                                        
                                        # Upload the PDF
                                        pdf_success, pdf_url = upload_blob(
                                            st.session_state.blob_service_client,
                                            final_container,
                                            new_pdf_path,
                                            pdf_content,
                                            "application/pdf"
                                        )
                                        
                                        if pdf_success:
                                            st.success(f"Successfully copied PDF to {new_pdf_path} in {final_container}")
                                        else:
                                            st.error("Failed to copy PDF to final container")
                                else:
                                    st.error("Failed to save edited data")
                            except Exception as e:
                                st.error(f"Error saving edited data: {str(e)}")
                    else:
                        st.warning("Final container not specified in configuration")
                    
                    # Reset button
                    if st.button("Cancel Editing", type="secondary"):
                        st.session_state.edit_mode = False
                        st.session_state.csv_data = None
                        st.session_state.edited_csv_data = None
                        st.experimental_rerun()
    else:
        st.error("Blob service client not initialized. Please check your configuration.")

elif main_menu == "Bulk Upload":
    st.header("Bulk Upload to Final Container")
    
    if st.session_state.blob_service_client and st.session_state.config:
        # Get container names from config
        source_container = st.session_state.config.get('source_container', '')
        processed_container = st.session_state.config.get('processed_container', '')
        final_container = st.session_state.config.get('final_container', '')
        
        if not source_container or not processed_container or not final_container:
            st.error("Source, processed, or final container not specified in configuration")
        else:
            # Display confidence options
            confidence_option = st.radio(
                "Select Confidence Level to Upload",
                ["High Confidence Only", "Low Confidence Only", "Both High and Low Confidence"],
                key="bulk_confidence_radio"
            )
            
            # Define the folders to upload based on selection
            folders_to_upload = []
            if confidence_option == "High Confidence Only":
                folders_to_upload.append("high_confidence")
            elif confidence_option == "Low Confidence Only":
                folders_to_upload.append("low_confidence")
            else:
                folders_to_upload.extend(["high_confidence", "low_confidence"])
            
            # Display information about what will be uploaded
            st.write("### Files to be Uploaded")
            st.write(f"This will upload files from the following containers and folders:")
            
            for folder in folders_to_upload:
                st.write(f"- {folder}/")
                
                # List subfolders in this confidence folder
                source_subfolders = list_folders_in_container(
                    st.session_state.blob_service_client,
                    source_container,
                    folder + "/"
                )
                
                processed_subfolders = list_folders_in_container(
                    st.session_state.blob_service_client,
                    processed_container,
                    folder + "/"
                )
                
                # Find common subfolders
                common_subfolders = set(source_subfolders).intersection(set(processed_subfolders))
                
                if common_subfolders:
                    st.write("  Subfolders:")
                    for subfolder in common_subfolders:
                        st.write(f"  - {subfolder}/")
                else:
                    st.write("  No common subfolders found")
            
            # Option to specify a prefix for the final container
            final_prefix = st.text_input(
                "Final Container Prefix (optional)",
                value="",
                key="final_prefix_input",
                help="Optional prefix to add to folders in the final container"
            )
            
            # Confirmation checkbox
            confirm_upload = st.checkbox(
                "I confirm that I want to upload these files to the final container",
                key="confirm_upload_checkbox"
            )
            
            # Upload button
            if st.button("Start Bulk Upload", type="primary", disabled=not confirm_upload):
                if confirm_upload:
                    # Start the upload process
                    with st.spinner("Processing bulk upload..."):
                        uploaded_files = []
                        errors = []
                        
                        for confidence_folder in folders_to_upload:
                            # Get subfolders
                            source_subfolders = list_folders_in_container(
                                st.session_state.blob_service_client,
                                source_container,
                                confidence_folder + "/"
                            )
                            
                            processed_subfolders = list_folders_in_container(
                                st.session_state.blob_service_client,
                                processed_container,
                                confidence_folder + "/"
                            )
                            
                            # Find common subfolders
                            common_subfolders = set(source_subfolders).intersection(set(processed_subfolders))
                            
                            for subfolder in common_subfolders:
                                subfolder_path = f"{confidence_folder}/{subfolder}/"
                                
                                # Get files in source folder
                                source_pdfs, _ = list_blobs_in_folder(
                                    st.session_state.blob_service_client, 
                                    source_container, 
                                    subfolder_path
                                )
                                
                                # Get files in processed folder
                                _, processed_csvs = list_blobs_in_folder(
                                    st.session_state.blob_service_client, 
                                    processed_container, 
                                    subfolder_path
                                )
                                
                                # Match source PDFs with processed CSVs
                                matched_files = match_source_and_processed_files(source_pdfs, processed_csvs)
                                
                                # Create the final folder path
                                final_folder_path = f"{final_prefix}{subfolder_path}" if final_prefix else subfolder_path
                                
                                # Upload matched files
                                for match in matched_files:
                                    try:
                                        # Upload the PDF
                                        pdf_path = match["pdf_file"]
                                        pdf_content = download_blob_to_memory(
                                            st.session_state.blob_service_client,
                                            source_container,
                                            pdf_path
                                        )
                                        
                                        if pdf_content:
                                            # Get just the filename part
                                            pdf_filename = os.path.basename(pdf_path)
                                            
                                            # Create the final blob path
                                            final_pdf_path = f"{final_folder_path}{pdf_filename}"
                                            
                                            # Upload to final container
                                            pdf_success, _ = upload_blob(
                                                st.session_state.blob_service_client,
                                                final_container,
                                                final_pdf_path,
                                                pdf_content,
                                                "application/pdf"
                                            )
                                            
                                            if pdf_success:
                                                uploaded_files.append(f"PDF: {final_pdf_path}")
                                            else:
                                                errors.append(f"Failed to upload PDF: {pdf_path}")
                                        
                                        # Upload matching CSVs
                                        for csv_path in match["matching_csvs"]:
                                            csv_content = download_blob_to_memory(
                                                st.session_state.blob_service_client,
                                                processed_container,
                                                csv_path
                                            )
                                            
                                            if csv_content:
                                                # Get just the filename part
                                                csv_filename = os.path.basename(csv_path)
                                                
                                                # Create the final blob path
                                                final_csv_path = f"{final_folder_path}{csv_filename}"
                                                
                                                # Upload to final container
                                                csv_success, _ = upload_blob(
                                                    st.session_state.blob_service_client,
                                                    final_container,
                                                    final_csv_path,
                                                    csv_content,
                                                    "text/csv"
                                                )
                                                
                                                if csv_success:
                                                    uploaded_files.append(f"CSV: {final_csv_path}")
                                                else:
                                                    errors.append(f"Failed to upload CSV: {csv_path}")
                                    except Exception as e:
                                        errors.append(f"Error processing {match['pdf_name']}: {str(e)}")
                        
                        # Display results
                        st.success(f"Bulk upload completed. {len(uploaded_files)} files uploaded.")
                        
                        if uploaded_files:
                            with st.expander("Uploaded Files"):
                                for file in uploaded_files:
                                    st.write(file)
                        
                        if errors:
                            with st.expander("Errors"):
                                for error in errors:
                                    st.error(error)
                else:
                    st.warning("Please confirm the upload by checking the confirmation box")
    else:
        st.error("Blob service client not initialized. Please check your configuration.")

# Add a footer
st.markdown("---")
st.markdown("### Financial Data Extractor - Powered by Azure OpenAI")

# Add a sidebar option to clear session state for debugging
if st.sidebar.button("Clear Session State", type="secondary"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.sidebar.success("Session state cleared!")
    st.experimental_rerun()
