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
    apply_edits_to_csv,
    render_pdf_preview
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
if 'validation_results' not in st.session_state:
    st.session_state.validation_results = {}
if 'selected_pdf_blob' not in st.session_state:
    st.session_state.selected_pdf_blob = None
if 'pdf_content' not in st.session_state:
    st.session_state.pdf_content = None

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
    st.session_state.validation_results = {}  # Clear validation
    st.session_state.selected_pdf_blob = None  # Clear selected PDF
    st.session_state.pdf_content = None  # Clear PDF content

# Set paths based on config and confidence selection
container_name = config["container_name"]
if confidence_selection == "high_confidence":
    source_prefix = config["high_confidence_source_prefix"]
    processed_prefix = config["high_confidence_processed_prefix"]
else:
    source_prefix = config["low_confidence_source_prefix"]
    processed_prefix = config["low_confidence_processed_prefix"]

# List source and processed files
source_blobs = list_blobs_with_prefix(blob_service_client, container_name, source_prefix)
processed_blobs = list_blobs_with_prefix(blob_service_client, container_name, processed_prefix)

# Match source PDFs with their processed CSV results
matched_files = match_source_and_processed_files(source_blobs, processed_blobs)

# PDF Preview Sidebar
st.sidebar.header("PDF Preview")
if matched_files:
    # Create a selectbox for PDF selection in the sidebar
    pdf_options = [match["base_name"] for match in matched_files]
    selected_pdf_idx = st.sidebar.selectbox(
        "Select PDF to preview",
        range(len(pdf_options)),
        format_func=lambda i: pdf_options[i],
        key="sidebar_pdf_selector"
    )
    
    # Load the selected PDF for preview
    if selected_pdf_idx is not None:
        selected_pdf_blob = matched_files[selected_pdf_idx]["source_blob"]
        
        # Only reload the PDF if it's different from the currently selected one
        if selected_pdf_blob != st.session_state.selected_pdf_blob:
            st.session_state.selected_pdf_blob = selected_pdf_blob
            st.session_state.pdf_content = download_blob_to_memory(
                blob_service_client, container_name, selected_pdf_blob
            )
        
        # Display the PDF preview in the sidebar
        if st.session_state.pdf_content:
            render_pdf_preview(st.session_state.pdf_content, height=400)
else:
    st.sidebar.info("No PDF files available for preview")

# Create tabs
tabs = st.tabs(["Results View", "Manual Edit", "Bulk Operations"])

# Tab 1: Results View
with tabs[0]:
    st.header(f"Results - {confidence_selection.replace('_', ' ').title()}")

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

        # Load the CSV data
        csv_df = load_csv_from_blob(blob_service_client, container_name, processed_blob)

        if csv_df is not None:
            # Create a page selector if there are multiple pages
            pages = csv_df["Page"].unique() if "Page" in csv_df.columns else [1]
            
            if len(pages) > 1:
                selected_page = st.selectbox(
                    "Select Page to Edit", 
                    pages,
                    key=f"page_selector_{edit_file_idx}"
                )
                page_df = csv_df[csv_df["Page"] == selected_page]
            else:
                selected_page = pages[0]
                page_df = csv_df

            # Create a form for editing
            with st.form(key=f"edit_form_{edit_file_idx}_{selected_page}"):
                st.subheader(f"Edit Page {selected_page}")
                
                # Define the fields to edit
                edit_fields = [
                    "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName",
                    "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount",
                    "Freight", "Salestax", "Total"
                ]
                
                # Find which fields exist in the DataFrame
                available_fields = [field for field in edit_fields if field in page_df.columns]
                
                # Create a dictionary to store edits
                edits = {}
                
                # Create form fields for each editable field
                for field in available_fields:
                    # Get current value from first row
                    current_value = page_df[field].iloc[0] if not page_df.empty else ""
                    
                    # Check if confidence column exists
                    confidence_col = f"{field} Confidence"
                    has_low_confidence = False
                    
                    if confidence_col in page_df.columns:
                        confidence = page_df[confidence_col].iloc[0] if not page_df.empty else 100
                        has_low_confidence = confidence < 90
                    
                    # Create columns for field and confidence
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        # Add visual indicator for low confidence
                        field_label = f"{field} ⚠️" if has_low_confidence else field
                        edits[field] = st.text_input(
                            field_label,
                            value=str(current_value) if pd.notna(current_value) else "",
                            key=f"field_{edit_file_idx}_{selected_page}_{field}"
                        )
                    
                    with col2:
                        if confidence_col in page_df.columns:
                            confidence_color = "red" if has_low_confidence else "green"
                            st.markdown(
                                f"<p style='color:{confidence_color};'>Confidence: {confidence:.1f}%</p>", 
                                unsafe_allow_html=True
                            )
                
                # Submit button
                submit_button = st.form_submit_button("Save Edits")
                
                if submit_button:
                    # Save edits to the DataFrame
                    for field, value in edits.items():
                        # Update the DataFrame for the selected page
                        if field in page_df.columns:
                            page_indices = page_df.index
                            for idx in page_indices:
                                csv_df.at[idx, field] = value
                    
                    # Save the edited DataFrame to blob storage
                    output_container = config.get("final_output_container", container_name)
                    output_prefix = config.get("final_output_prefix", "final_output/")
                    
                    # Create output blob name
                    base_name = matched_files[edit_file_idx]["base_name"]
                    pdf_output_blob_name = f"{output_prefix}pdf/{base_name}.pdf"
                    csv_output_blob_name = f"{output_prefix}csv/{base_name}.csv"
                    
                    # Get PDF content if not already loaded
                    if st.session_state.selected_pdf_blob == source_blob and st.session_state.pdf_content:
                        pdf_content = st.session_state.pdf_content
                    else:
                        pdf_content = download_blob_to_memory(blob_service_client, container_name, source_blob)
                    
                    # Upload to blob storage
                    csv_buffer = io.StringIO()
                    csv_df.to_csv(csv_buffer, index=False)
                    
                    pdf_success, pdf_url = upload_to_blob_storage(
                        blob_service_client,
                        output_container,
                        pdf_output_blob_name,
                        pdf_content,
                        "application/pdf"
                    )
                    
                    csv_success, csv_url = upload_to_blob_storage(
                        blob_service_client,
                        output_container,
                        csv_output_blob_name,
                        csv_buffer.getvalue(),
                        "text/csv"
                    )
                    
                    if pdf_success and csv_success:
                        st.success(f"Successfully saved edits to {output_container}")
                        
                        # Store edit in session state
                        if edit_file_idx not in st.session_state.edited_data:
                            st.session_state.edited_data[edit_file_idx] = {}
                        
                        st.session_state.edited_data[edit_file_idx][selected_page] = edits
                    else:
                        st.error("Failed to save edits")

            # Add a Validate button outside the form
            if st.button("Validate", key=f"validate_{edit_file_idx}_{selected_page}"):
                # Perform validation logic
                validation_errors = {}
                
                # For each field, check if value is empty
                for field in available_fields:
                    current_value = page_df[field].iloc[0] if not page_df.empty else ""
                    if pd.isna(current_value) or str(current_value).strip() == "":
                        if selected_page not in validation_errors:
                            validation_errors[selected_page] = []
                        validation_errors[selected_page].append(field)
                
                if validation_errors:
                    error_message = "The following fields have errors:\n"
                    for page, error_fields in validation_errors.items():
                        error_message += f"Page {page}: {', '.join(error_fields)}\n"
                    st.error(error_message)
                    
                    # Store validation results
                    if edit_file_idx not in st.session_state.validation_results:
                        st.session_state.validation_results[edit_file_idx] = {}
                    
                    st.session_state.validation_results[edit_file_idx][selected_page] = error_fields
                else:
                    st.success("All data is valid!")
                    
                    # Clear validation errors
                    if (edit_file_idx in st.session_state.validation_results and 
                        selected_page in st.session_state.validation_results[edit_file_idx]):
                        del st.session_state.validation_results[edit_file_idx][selected_page]

            # Display validation results if available
            if (edit_file_idx in st.session_state.validation_results and 
                selected_page in st.session_state.validation_results.get(edit_file_idx, {})):
                error_fields = st.session_state.validation_results[edit_file_idx][selected_page]
                st.warning(f"Validation Issues for Page {selected_page}: {', '.join(error_fields)}")

# Tab 3: Bulk Operations
with tabs[2]:
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
                            f"{final_prefix}pdf/{match['base_name']}.pdf",  # Store PDF in 'pdf' subfolder
                            pdf_content,
                            "application/pdf"
                        )

                        # Upload CSV to final container
                        csv_buffer = io.StringIO()
                        csv_df.to_csv(csv_buffer, index=False)

                        csv_success, _ = upload_to_blob_storage(
                            blob_service_client,
                            final_container,
                            f"{final_prefix}csv/{match['base_name']}.csv",  # Store CSV in 'csv' subfolder
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
                            zip_file.writestr(f"pdf/{match['base_name']}.pdf", pdf_content)  # added pdf/ prefix

                        # Get CSV
                        csv_df = load_csv_from_blob(blob_service_client, container_name, match["processed_blob"])
                        if csv_df is not None:
                            csv_buffer = io.StringIO()
                            csv_df.to_csv(csv_buffer, index=False)
                            zip_file.writestr(f"csv/{match['base_name']}.csv", csv_buffer.getvalue())  # added csv/ prefix
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
