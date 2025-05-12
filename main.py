# main.py
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
    get_pdf_page_count
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
if 'selected_file_idx' not in st.session_state:
    st.session_state.selected_file_idx = 0
if 'pdf_content' not in st.session_state:
    st.session_state.pdf_content = None
if 'csv_df' not in st.session_state:
    st.session_state.csv_df = None
if 'edit_history' not in st.session_state:
    st.session_state.edit_history = {}

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
    st.session_state.validation_results = {} # Clear validation
    st.session_state.pdf_content = None
    st.session_state.csv_df = None
    st.session_state.selected_file_idx = 0
    st.session_state.edit_history = {}

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

# PDF Selector in Sidebar
st.sidebar.markdown("---")
st.sidebar.subheader("File Selection")

if not matched_files:
    st.sidebar.warning("No matched files found.")
else:
    # File selector dropdown in sidebar
    selected_file_idx = st.sidebar.selectbox(
        "Select a file",
        range(len(matched_files)),
        format_func=lambda x: matched_files[x]["base_name"],
        index=st.session_state.selected_file_idx
    )

    # Update the selected file in session state
    if selected_file_idx != st.session_state.selected_file_idx:
        st.session_state.selected_file_idx = selected_file_idx
        st.session_state.pdf_content = None  # Reset PDF content when changing files
        st.session_state.csv_df = None

    # Load PDF and CSV for selected file
    if st.session_state.pdf_content is None:
        source_blob = matched_files[selected_file_idx]["source_blob"]
        st.session_state.pdf_content = download_blob_to_memory(blob_service_client, container_name, source_blob)

    if st.session_state.csv_df is None:
        processed_blob = matched_files[selected_file_idx]["processed_blob"]
        st.session_state.csv_df = load_csv_from_blob(blob_service_client, container_name, processed_blob)

    # Display PDF preview in sidebar
    if st.session_state.pdf_content:
        st.sidebar.markdown("---")
        st.sidebar.subheader("PDF Preview")
        base64_pdf = convert_pdf_to_base64(st.session_state.pdf_content)
        display_pdf_viewer(base64_pdf, height=400)

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

        # Use already selected file from sidebar
        st.write(f"Selected file: {matched_files[st.session_state.selected_file_idx]['base_name']}")

        # Display the CSV results
        if st.session_state.csv_df is not None:
            st.subheader("Extraction Results")
            st.dataframe(st.session_state.csv_df, use_container_width=True)

            # Evaluation metrics
            st.subheader("Confidence Metrics")

            # Calculate average confidence for all fields
            confidence_cols = [col for col in st.session_state.csv_df.columns if col.endswith("Confidence")]
            if confidence_cols:
                avg_confidence = st.session_state.csv_df[confidence_cols].mean().mean()

                # Display metrics
                metrics_cols = st.columns(3)
                metrics_cols[0].metric("Average Confidence", f"{avg_confidence:.2f}%")
                metrics_cols[1].metric("Fields Below 95%", sum((st.session_state.csv_df[confidence_cols] < 95).any(axis=1)))
                metrics_cols[2].metric("Fields Below 80%", sum((st.session_state.csv_df[confidence_cols] < 80).any(axis=1)))

                # Display confidence distribution
                st.subheader("Confidence Distribution")
                st.bar_chart(st.session_state.csv_df[confidence_cols].mean())
        else:
            st.error("Failed to load CSV results")

# Tab 2: Manual Edit
with tabs[1]:
    st.header(f"Manual Edit - {confidence_selection.replace('_', ' ').title()}")

    if not matched_files:
        st.warning("No matched files found to edit.")
    else:
        # Use already selected file from sidebar
        selected_file = matched_files[st.session_state.selected_file_idx]
        
        # Load the CSV for editing if not already loaded
        if st.session_state.csv_df is None:
            processed_blob = selected_file["processed_blob"]
            st.session_state.csv_df = load_csv_from_blob(blob_service_client, container_name, processed_blob)

        if st.session_state.csv_df is not None:
            # Create a form-based editor with expanders
            st.subheader("Form-based Edit")
            
            # Get the data fields and corresponding confidence columns
            all_columns = st.session_state.csv_df.columns.tolist()
            data_fields = []
            confidence_fields = {}
            
            for col in all_columns:
                if col.endswith("_Confidence"):
                    # Find the corresponding data field
                    data_field = col.replace("_Confidence", "")
                    if data_field in all_columns:
                        confidence_fields[data_field] = col
                        if data_field not in data_fields:
                            data_fields.append(data_field)
                elif not col.endswith("Confidence") and col not in ["Page", "Filename", "Extraction_Time"]:
                    if col not in data_fields:
                        data_fields.append(col)
            
            # Initialize edit history for this file if not present
            file_key = selected_file["base_name"]
            if file_key not in st.session_state.edit_history:
                st.session_state.edit_history[file_key] = {}
            
            # Create a form for editing
            with st.form(key="edit_form"):
                # Initialize edited_data if not present
                if file_key not in st.session_state.edited_data:
                    st.session_state.edited_data[file_key] = {}
                
                # Use expanders for each row
                for index, row in st.session_state.csv_df.iterrows():
                    page_num = row.get("Page", index + 1)
                    
                    # Create an expander for each page/row
                    with st.expander(f"Row {index + 1}", expanded=index==0):
                        # Create columns for each field
                        for field in data_fields:
                            # Get field value and confidence
                            field_value = row.get(field, "")
                            
                            # Find the confidence value
                            confidence = 0
                            if field in confidence_fields:
                                confidence_field = confidence_fields[field]
                                confidence = row.get(confidence_field, 0)
                            
                            # Get current edited value if available
                            current_value = field_value
                            if file_key in st.session_state.edited_data and \
                               index in st.session_state.edited_data[file_key] and \
                               field in st.session_state.edited_data[file_key][index]:
                                current_value = st.session_state.edited_data[file_key][index][field]
                            
                            # Color code based on confidence
                            confidence_color = "green" if confidence >= 95 else "red"
                            confidence_display = f'<span style="color:{confidence_color}">Confidence: {confidence:.2f}%</span>'
                            st.markdown(confidence_display, unsafe_allow_html=True)
                            
                            # Text input for the field
                            new_value = st.text_input(
                                f"{field}",
                                value=current_value,
                                key=f"edit_{file_key}_{index}_{field}"
                            )
                            
                            # Store the edited value and track history if it changed
                            if new_value != str(field_value):
                                # Initialize nested structure if needed
                                if index not in st.session_state.edited_data[file_key]:
                                    st.session_state.edited_data[file_key][index] = {}
                                
                                # Store the edited value
                                st.session_state.edited_data[file_key][index][field] = new_value
                                
                                # Track edit history
                                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                
                                # Initialize history for this index if needed
                                if index not in st.session_state.edit_history[file_key]:
                                    st.session_state.edit_history[file_key][index] = {}
                                
                                # Record the edit
                                if field not in st.session_state.edit_history[file_key][index]:
                                    st.session_state.edit_history[file_key][index][field] = {
                                        "original_value": field_value,
                                        "edits": []
                                    }
                                
                                # Add this edit to the history
                                st.session_state.edit_history[file_key][index][field]["edits"].append({
                                    "timestamp": current_time,
                                    "new_value": new_value
                                })
                
                # Submit button
                submitted = st.form_submit_button("Save Edits")
                
                if submitted:
                    try:
                        # Apply edits to the dataframe
                        edited_df = st.session_state.csv_df.copy()
                        
                        # Add tracking columns if they don't exist
                        if "Manual_Edit" not in edited_df.columns:
                            edited_df["Manual_Edit"] = "N"
                        if "Manual_Edit_Time" not in edited_df.columns:
                            edited_df["Manual_Edit_Time"] = ""
                        if "Original_Values" not in edited_df.columns:
                            edited_df["Original_Values"] = ""
                        if "New_Values" not in edited_df.columns:
                            edited_df["New_Values"] = ""
                        
                        if file_key in st.session_state.edited_data:
                            for idx, field_edits in st.session_state.edited_data[file_key].items():
                                # Skip if no edits for this row
                                if not field_edits:
                                    continue
                                
                                # Apply edits to each field
                                for field, value in field_edits.items():
                                    edited_df.at[idx, field] = value
                                
                                # Update tracking columns
                                edited_df.at[idx, "Manual_Edit"] = "Y"
                                
                                # Get the latest edit timestamp
                                if idx in st.session_state.edit_history[file_key]:
                                    latest_time = ""
                                    for field, history in st.session_state.edit_history[file_key][idx].items():
                                        if history["edits"]:
                                            edit_time = history["edits"][-1]["timestamp"]
                                            if edit_time > latest_time:
                                                latest_time = edit_time
                                    
                                    if latest_time:
                                        edited_df.at[idx, "Manual_Edit_Time"] = latest_time
                                
                                # Collect original and new values
                                original_values = []
                                new_values = []
                                
                                if idx in st.session_state.edit_history[file_key]:
                                    for field, history in st.session_state.edit_history[file_key][idx].items():
                                        if history["edits"]:
                                            orig = history["original_value"]
                                            new = history["edits"][-1]["new_value"]
                                            original_values.append(f"{field}: {orig}")
                                            new_values.append(f"{field}: {new}")
                                
                                edited_df.at[idx, "Original_Values"] = "; ".join(original_values)
                                edited_df.at[idx, "New_Values"] = "; ".join(new_values)
                        
                        # Save to blob storage
                        output_container = config.get("final_output_container", container_name)
                        output_prefix = config.get("final_output_prefix", "final_output/")
                        
                        # Create output blob names
                        base_name = selected_file["base_name"]
                        pdf_output_blob_name = f"{output_prefix}pdf/{base_name}.pdf"
                        csv_output_blob_name = f"{output_prefix}csv/{base_name}.csv"
                        
                        # Convert dataframe to CSV
                        csv_buffer = io.StringIO()
                        edited_df.to_csv(csv_buffer, index=False)
                        
                        # Upload to blob storage
                        pdf_success, pdf_url = upload_to_blob_storage(
                            blob_service_client,
                            output_container,
                            pdf_output_blob_name,
                            st.session_state.pdf_content,
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
                            # Update the CSV in session state
                            st.session_state.csv_df = edited_df
                        else:
                            st.error("Failed to save edits")
                    except Exception as e:
                        st.error(f"Error saving edits: {str(e)}")
            
            # Display edit history summary
            if file_key in st.session_state.edit_history and st.session_state.edit_history[file_key]:
                st.subheader("Edit History")
                
                # Count total edits
                total_edits = 0
                for idx, fields in st.session_state.edit_history[file_key].items():
                    for field, history in fields.items():
                        total_edits += len(history["edits"])
                
                st.write(f"Total edits made: {total_edits}")
                
                # Build a dataframe to display edit history
                history_rows = []
                for idx, fields in st.session_state.edit_history[file_key].items():
                    for field, history in fields.items():
                        for i, edit in enumerate(history["edits"]):
                            history_rows.append({
                                "Row": idx + 1,
                                "Field": field,
                                "Original Value": history["original_value"] if i == 0 else "",
                                "New Value": edit["new_value"],
                                "Edit Time": edit["timestamp"]
                            })
                
                if history_rows:
                    history_df = pd.DataFrame(history_rows)
                    st.dataframe(history_df, use_container_width=True)
            
            # Add a Validate button
            if st.button("Validate Edits"):
                # Apply current edits to a temporary dataframe for validation
                temp_df = st.session_state.csv_df.copy()
                
                if file_key in st.session_state.edited_data:
                    for idx, field_edits in st.session_state.edited_data[file_key].items():
                        for field, value in field_edits.items():
                            temp_df.at[idx, field] = value
                
                # Perform validation logic
                validation_errors = {}
                for index, row in temp_df.iterrows():
                    for field in data_fields:
                        value = row.get(field, "")
                        if pd.isna(value) or str(value).strip() == "":
                            if index not in validation_errors:
                                validation_errors[index] = []
                            validation_errors[index].append(field)
                
                if validation_errors:
                    error_message = "The following fields have errors:\n"
                    for index, error_cols in validation_errors.items():
                        error_message += f"Row {index + 1}: {', '.join(error_cols)}\n"
                    st.error(error_message)
                    st.session_state.validation_results[file_key] = validation_errors
                else:
                    st.success("All data is valid!")
                    st.session_state.validation_results[file_key] = {}
            
            # Display validation results
            if file_key in st.session_state.validation_results:
                validation_results = st.session_state.validation_results[file_key]
                if validation_results:
                    st.warning("Validation Issues:")
                    for index, error_cols in validation_results.items():
                        st.write(f"Row {index + 1}: {', '.join(error_cols)}")
        else:
            st.error("Failed to load CSV for editing")

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
            # Create a container to display results
            result_container = st.container()
            
            # Initialize tracking
            success_files = []
            error_files = []
            
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
                        pdf_output_blob_name = f"{final_prefix}pdf/{match['base_name']}.pdf"
                        pdf_success, pdf_url = upload_to_blob_storage(
                            blob_service_client,
                            final_container,
                            pdf_output_blob_name,
                            pdf_content,
                            "application/pdf"
                        )

                        # Upload CSV to final container
                        csv_buffer = io.StringIO()
                        csv_df.to_csv(csv_buffer, index=False)
                        
                        csv_output_blob_name = f"{final_prefix}csv/{match['base_name']}.csv"
                        csv_success, csv_url = upload_to_blob_storage(
                            blob_service_client,
                            final_container,
                            csv_output_blob_name,
                            csv_buffer.getvalue(),
                            "text/csv"
                        )

                        if pdf_success and csv_success:
                            success_files.append({
                                "filename": match['base_name'],
                                "pdf_path": pdf_output_blob_name,
                                "csv_path": csv_output_blob_name
                            })
                        else:
                            error_files.append({
                                "filename": match['base_name'],
                                "error": "Failed to upload one or both files"
                            })
                    else:
                        error_files.append({
                            "filename": match['base_name'],
                            "error": "Failed to download source files"
                        })

                except Exception as e:
                    error_files.append({
                        "filename": match['base_name'],
                        "error": str(e)
                    })

            # Final update
            progress_bar.progress(1.0)
            status_text.text("Bulk upload complete")

            # Display detailed results
            with result_container:
                st.success(f"Bulk upload completed. Success: {len(success_files)}, Errors: {len(error_files)}")
                
                # Show successful uploads
                if success_files:
                    st.subheader("Successfully Uploaded Files")
                    success_df = pd.DataFrame(success_files)
                    st.dataframe(success_df, use_container_width=True)
                
                # Show errors
                if error_files:
                    st.subheader("Failed Uploads")
                    error_df = pd.DataFrame(error_files)
                    st.dataframe(error_df, use_container_width=True)

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
                            zip_file.writestr(f"pdf/{match['base_name']}.pdf", pdf_content)

                        # Get CSV
                        csv_df = load_csv_from_blob(blob_service_client, container_name, match["processed_blob"])
                        if csv_df is not None:
                            csv_buffer = io.StringIO()
                            csv_df.to_csv(csv_buffer, index=False)
                            zip_file.writestr(f"csv/{match['base_name']}.csv", csv_buffer.getvalue())
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
    st.rerun()

# Footer with system info
st.sidebar.markdown("---")
st.sidebar.info(
    f"Container: {container_name}\n\n"
    f"Source: {source_prefix}\n\n"
    f"Results: {processed_prefix}\n\n"
    f"Files: {len(matched_files) if 'matched_files' in locals() else 0}"
)
