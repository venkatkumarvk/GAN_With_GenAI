import streamlit as st
import pandas as pd
import os
import io
import tempfile
import base64
from datetime import datetime
import gc
from helper_functions import (
    load_config, 
    get_blob_service_client,
    get_openai_client,
    list_blobs_with_prefix,
    download_blob_to_memory,
    convert_pdf_to_base64,
    display_pdf_viewer,
    load_csv_from_blob,
    upload_to_blob_storage,
    get_filename_from_blob_path,
    match_source_and_processed_files,
    apply_edits_to_csv
)

# App title and configuration
st.set_page_config(page_title="PDF Invoice Processor", page_icon="📊", layout="wide")
st.title("PDF Invoice Processor")

# Load configuration from JSON file 
config = load_config()

if not config:
    st.error("Configuration file not found or invalid. Please provide a valid config.json file.")
    st.stop()

# Initialize clients
blob_service_client = get_blob_service_client(config["azure_storage_connection_string"])
openai_client = get_openai_client(config["azure_openai_endpoint"], config["azure_openai_api_key"])

if not blob_service_client or not openai_client:
    st.error("Failed to initialize required clients. Please check your configuration.")
    st.stop()

# Initialize session state
if 'edited_data' not in st.session_state:
    st.session_state.edited_data = {}
if 'current_file_index' not in st.session_state:
    st.session_state.current_file_index = 0
if 'confidence_selection' not in st.session_state:
    st.session_state.confidence_selection = "high_confidence"

# Add sidebar with confidence selection 
st.sidebar.title("Options")
confidence_options = ["high_confidence", "low_confidence"]
confidence_selection = st.sidebar.radio(
    "Select Confidence Level", 
    confidence_options,
    index=confidence_options.index(st.session_state.confidence_selection)
)

# Update session state when selection changes
if confidence_selection != st.session_state.confidence_selection:
    st.session_state.confidence_selection = confidence_selection
    st.session_state.current_file_index = 0  # Reset file index when changing confidence level
    st.session_state.edited_data = {}  # Clear edits

# Set paths based on config and confidence selection
container_name = config["container_name"]
if confidence_selection == "high_confidence":
    source_prefix = config["high_confidence_source_prefix"]
    processed_prefix = config["high_confidence_processed_prefix"]
else:
    source_prefix = config["low_confidence_source_prefix"]
    processed_prefix = config["low_confidence_processed_prefix"]

# Create tabs
tabs = st.tabs(["Results View", "Manual Edit", "Bulk Operations"])

# Tab 1: Results View
with tabs[0]:
    st.header(f"Results - {confidence_selection.replace('_', ' ').title()}")
    
    # List source and processed files
    source_blobs = list_blobs_with_prefix(blob_service_client, container_name, source_prefix)
    processed_blobs = list_blobs_with_prefix(blob_service_client, container_name, processed_prefix)
    
    # Match source PDFs with their processed CSV results
    matched_files = match_source_and_processed_files(source_blobs, processed_blobs)
    
    if not matched_files:
        st.warning("No matched source and processed files found.")
    else:
        # Display matched files in a table
        matched_df = pd.DataFrame(matched_files)
        st.write(f"Found {len(matched_files)} matched files")
        st.dataframe(matched_df[["base_name", "source_blob", "processed_blob"]], use_container_width=True)
        
        # Button to view file details
        selected_file_idx = st.selectbox("Select file to view", 
                                         range(len(matched_files)), 
                                         format_func=lambda x: matched_files[x]["base_name"])
        
        if st.button("View Selected File"):
            source_blob = matched_files[selected_file_idx]["source_blob"]
            processed_blob = matched_files[selected_file_idx]["processed_blob"]
            
            # Display side by side: PDF and CSV results
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("PDF Document")
                pdf_content = download_blob_to_memory(blob_service_client, container_name, source_blob)
                if pdf_content:
                    base64_pdf = convert_pdf_to_base64(pdf_content)
                    display_pdf_viewer(base64_pdf)
                else:
                    st.error("Failed to load PDF")
            
            with col2:
                st.subheader("Extraction Results")
                csv_df = load_csv_from_blob(blob_service_client, container_name, processed_blob)
                if csv_df is not None:
                    st.dataframe(csv_df, use_container_width=True)
                else:
                    st.error("Failed to load CSV results")
            
            # Evaluation metrics
            if csv_df is not None:
                st.subheader("Confidence Metrics")
                
                # Calculate average confidence for all fields
                confidence_cols = [col for col in csv_df.columns if col.endswith("Confidence")]
                if confidence_cols:
                    avg_confidence = csv_df[confidence_cols].mean().mean()
                    
                    # Display metrics
                    metrics_cols = st.columns(3)
                    metrics_cols[0].metric("Average Confidence", f"{avg_confidence:.2f}%")
                    metrics_cols[1].metric("Fields Below 90%", sum((csv_df[confidence_cols] < 90).any(axis=1)))
                    metrics_cols[2].metric("Fields Below 80%", sum((csv_df[confidence_cols] < 80).any(axis=1)))
                    
                    # Display confidence distribution
                    st.subheader("Confidence Distribution")
                    st.bar_chart(csv_df[confidence_cols].mean())

# Tab 2: Manual Edit
with tabs[1]:
    st.header(f"Manual Edit - {confidence_selection.replace('_', ' ').title()}")
    
    if not matched_files:
        st.warning("No matched files found to edit.")
    else:
        # File selection for editing
        edit_file_idx = st.selectbox("Select file to edit", 
                                     range(len(matched_files)), 
                                     format_func=lambda x: matched_files[x]["base_name"],
                                     key="edit_file_selector")
        
        # Load the CSV for editing
        source_blob = matched_files[edit_file_idx]["source_blob"]
        processed_blob = matched_files[edit_file_idx]["processed_blob"]
        
        # Display the PDF for reference
        st.subheader("PDF Document Reference")
        pdf_content = download_blob_to_memory(blob_service_client, container_name, source_blob)
        if pdf_content:
            base64_pdf = convert_pdf_to_base64(pdf_content)
            display_pdf_viewer(base64_pdf, height=400)
        
        # Load and display the CSV for editing
        csv_df = load_csv_from_blob(blob_service_client, container_name, processed_blob)
        
        if csv_df is not None:
            st.subheader("Edit Extraction Results")
            
            # Generate a unique key for this dataframe edit session
            edit_key = f"df_edit_{edit_file_idx}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            # Create editable dataframe
            edited_df = st.data_editor(
                csv_df,
                key=edit_key,
                use_container_width=True,
                num_rows="fixed"
            )
            
            # Save edits
            if st.button("Save Edits"):
                # Save edits to the final output blob storage
                output_container = config.get("final_output_container", container_name)
                output_prefix = config.get("final_output_prefix", "final_output/")
                
                # Create output blob name 
                base_name = matched_files[edit_file_idx]["base_name"]
                output_blob_name = f"{output_prefix}{base_name}.csv"
                
                # Convert dataframe to CSV
                csv_buffer = io.StringIO()
                edited_df.to_csv(csv_buffer, index=False)
                
                # Upload to blob storage
                success, url = upload_to_blob_storage(
                    blob_service_client,
                    output_container,
                    output_blob_name,
                    csv_buffer.getvalue(),
                    "text/csv"
                )
                
                if success:
                    st.success(f"Successfully saved edits to {output_blob_name}")
                else:
                    st.error("Failed to save edits")
                
                # Also save source PDF to final output
                if pdf_content:
                    source_output_blob = f"{output_prefix}{base_name}.pdf"
                    upload_to_blob_storage(
                        blob_service_client,
                        output_container,
                        source_output_blob,
                        pdf_content,
                        "application/pdf"
                    )

# Tab 3: Bulk Operations
with tabs[3]:
    st.header("Bulk Operations")
    
    # Bulk upload to final container
    st.subheader("Bulk Upload to Final Container")
    
    final_container = config.get("final_output_container", container_name)
    final_prefix = config.get("final_output_prefix", "final_output/")
    
    st.write(f"Target Container: {final_container}")
    st.write(f"Target Prefix: {final_prefix}")
    
    if st.button("Upload All Files to Final Container"):
        with st.spinner("Processing bulk upload..."):
            success_count = 0
            error_count = 0
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i, match in enumerate(matched_files):
                try:
                    # Update progress
                    progress_bar.progress((i + 1) / len(matched_files))
                    status_text.text(f"Processing {i+1}/{len(matched_files)}: {match['base_name']}")
                    
                    # Download source PDF
                    pdf_content = download_blob_to_memory(blob_service_client, container_name, match["source_blob"])
                    
                    # Download CSV results
                    csv_df = load_csv_from_blob(blob_service_client, container_name, match["processed_blob"])
                    
                    if pdf_content and csv_df is not None:
                        # Upload PDF to final container
                        pdf_success, _ = upload_to_blob_storage(
                            blob_service_client,
                            final_container,
                            f"{final_prefix}{match['base_name']}.pdf",
                            pdf_content,
                            "application/pdf"
                        )
                        
                        # Upload CSV to final container
                        csv_buffer = io.StringIO()
                        csv_df.to_csv(csv_buffer, index=False)
                        
                        csv_success, _ = upload_to_blob_storage(
                            blob_service_client,
                            final_container,
                            f"{final_prefix}{match['base_name']}.csv",
                            csv_buffer.getvalue(),
                            "text/csv"
                        )
                        
                        if pdf_success and csv_success:
                            success_count += 1
                        else:
                            error_count += 1
                    else:
                        error_count += 1
                        
                except Exception as e:
                    st.error(f"Error processing {match['base_name']}: {str(e)}")
                    error_count += 1
            
            # Final update
            progress_bar.progress(1.0)
            status_text.text("Bulk upload complete")
            
            st.success(f"Bulk upload completed. Success: {success_count}, Errors: {error_count}")
    
    # Bulk download
    st.subheader("Bulk Download")
    
    if st.button("Download All Results"):
        with st.spinner("Preparing download..."):
            # Create in-memory zip file
            import zipfile
            from io import BytesIO
            
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                # Add each matching file to the zip
                for match in matched_files:
                    try:
                        # Get PDF
                        pdf_content = download_blob_to_memory(blob_service_client, container_name, match["source_blob"])
                        if pdf_content:
                            zip_file.writestr(f"{match['base_name']}.pdf", pdf_content)
                        
                        # Get CSV
                        csv_df = load_csv_from_blob(blob_service_client, container_name, match["processed_blob"])
                        if csv_df is not None:
                            csv_buffer = io.StringIO()
                            csv_df.to_csv(csv_buffer, index=False)
                            zip_file.writestr(f"{match['base_name']}.csv", csv_buffer.getvalue())
                    except Exception as e:
                        st.error(f"Error adding {match['base_name']} to zip: {str(e)}")
            
            # Reset buffer position
            zip_buffer.seek(0)
            
            # Create download button
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button(
                label="Download ZIP File",
                data=zip_buffer,
                file_name=f"invoice_results_{confidence_selection}_{timestamp}.zip",
                mime="application/zip"
            )

# Clear memory button in sidebar
if st.sidebar.button("Clear Memory"):
    # Clear session state
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    
    # Force garbage collection
    gc.collect()
    
    st.sidebar.success("Memory cleared!")
    st.experimental_rerun()

# Footer with system info
st.sidebar.markdown("---")
st.sidebar.info(
    f"Container: {container_name}\n\n"
    f"Source: {source_prefix}\n\n"
    f"Results: {processed_prefix}\n\n"
    f"Files: {len(matched_files) if 'matched_files' in locals() else 0}"
)
