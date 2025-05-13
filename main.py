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

# App configuration
st.set_page_config(page_title="MPower Health - Invoice Processor", page_icon="📊", layout="wide")

# Initialize session state variables
if 'app_view' not in st.session_state:
    st.session_state.app_view = "welcome"
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
if 'manual_edit_fields' not in st.session_state:
    st.session_state.manual_edit_fields = []

# Welcome Page
if st.session_state.app_view == "welcome":
    st.title("Welcome to MPower Health")
    st.subheader("Invoice Processing Solution")
    
    # Welcome page content
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("""
        ### Intelligent Invoice Processing
        
        Our platform uses Azure OpenAI to automatically extract key information from invoices.
        
        **Key Features:**
        - Automated data extraction from invoice PDFs
        - AI-powered classification with confidence scoring
        - Manual editing capabilities for verification
        - Secure cloud storage for all processed files
        
        Get started by clicking the button on the right.
        """)
    
    with col2:
        st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/9/9b/MPower_Health_logo.png/320px-MPower_Health_logo.png", 
                 width=300)
        
        # Start button
        if st.button("Start Invoice Processing", type="primary", use_container_width=True):
            st.session_state.app_view = "main"
            st.experimental_rerun()

# Main Application
elif st.session_state.app_view == "main":
    st.title("MPower Health - Invoice Processor")
    
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
        st.session_state.manual_edit_fields = []

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
            st.session_state.manual_edit_fields = []

        # Load PDF and CSV for selected file
        if st.session_state.pdf_content is None:
            source_blob = matched_files[selected_file_idx]["source_blob"]
            st.session_state.pdf_content = download_blob_to_memory(blob_service_client, container_name, source_blob)

        if st.session_state.csv_df is None:
            processed_blob = matched_files[selected_file_idx]["processed_blob"]
            st.session_state.csv_df = load_csv_from_blob(blob_service_client, container_name, processed_blob)
            
            # Get fields that can be edited (exclude metadata columns)
            if st.session_state.csv_df is not None:
                exclude_columns = ["Page", "Filename", "Extraction_Timestamp", "Manual_Edit", "Edit_Timestamp", 
                                  "New_Value", "Old_Value"]
                confidence_cols = [col for col in st.session_state.csv_df.columns if col.endswith("Confidence")]
                st.session_state.manual_edit_fields = [col for col in st.session_state.csv_df.columns 
                                                    if col not in exclude_columns and col not in confidence_cols]

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
            st.write(f"Editing file: {selected_file['base_name']}")

            # Load the CSV for editing if not already loaded
            if st.session_state.csv_df is None:
                processed_blob = selected_file["processed_blob"]
                st.session_state.csv_df = load_csv_from_blob(blob_service_client, container_name, processed_blob)
                
                # Ensure tracking columns exist
                if st.session_state.csv_df is not None and "Manual_Edit" not in st.session_state.csv_df.columns:
                    st.session_state.csv_df["Manual_Edit"] = "N"
                    st.session_state.csv_df["Edit_Timestamp"] = ""
                    st.session_state.csv_df["New_Value"] = ""
                    st.session_state.csv_df["Old_Value"] = ""

            if st.session_state.csv_df is not None and len(st.session_state.manual_edit_fields) > 0:
                # Create a form-based editor
                st.subheader("Form-based Edit")
                
                # Create a form for editing
                with st.form(key="edit_form"):
                    # Initialize edited_data if not present
                    if selected_file["base_name"] not in st.session_state.edited_data:
                        st.session_state.edited_data[selected_file["base_name"]] = {}
                    
                    # List of manually edited fields for tracking
                    manual_edit_tracking = []
                    
                    # Use expanders for each row
                    for index, row in st.session_state.csv_df.iterrows():
                        page_num = row.get("Page", index + 1)
                        
                        # Create an expander for each page
                        with st.expander(f"Page {page_num}", expanded=index==0):
                            # Create columns for fields
                            for field in st.session_state.manual_edit_fields:
                                # Get field value and confidence
                                field_value = row.get(field, "")
                                confidence_field = f"{field} Confidence"
                                confidence = row.get(confidence_field, 0)
                                
                                # Get current edited value if available
                                current_value = field_value
                                if selected_file["base_name"] in st.session_state.edited_data and \
                                   index in st.session_state.edited_data[selected_file["base_name"]] and \
                                   field in st.session_state.edited_data[selected_file["base_name"]][index]:
                                    current_value = st.session_state.edited_data[selected_file["base_name"]][index][field]
                                
                                # Create field label with confidence indicator
                                confidence_color = "green" if confidence >= 95 else "red"
                                field_label = f"{field} ({confidence:.1f}%)"
                                
                                # Text input for the field
                                col1, col2 = st.columns([8, 2])
                                
                                with col1:
                                    new_value = st.text_input(
                                        field_label,
                                        value=current_value,
                                        key=f"edit_{selected_file['base_name']}_{index}_{field}"
                                    )
                                
                                with col2:
                                    # Show confidence indicator
                                    st.markdown(f'<div style="height:32px;margin-top:25px;"><span style="color:{confidence_color};font-weight:bold;">{confidence:.1f}%</span></div>', 
                                              unsafe_allow_html=True)
                                
                                # Store the edited value
                                if new_value != field_value:
                                    if index not in st.session_state.edited_data[selected_file["base_name"]]:
                                        st.session_state.edited_data[selected_file["base_name"]][index] = {}
                                    
                                    # Track the edit
                                    st.session_state.edited_data[selected_file["base_name"]][index][field] = new_value
                                    manual_edit_tracking.append({
                                        "index": index,
                                        "field": field,
                                        "old_value": field_value,
                                        "new_value": new_value
                                    })
                    
                    # Submit button
                    submitted = st.form_submit_button("Save Edits")
                    
                    if submitted:
                        try:
                            # Apply edits to the dataframe
                            edited_df = st.session_state.csv_df.copy()
                            
                            if selected_file["base_name"] in st.session_state.edited_data:
                                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                
                                for idx, field_edits in st.session_state.edited_data[selected_file["base_name"]].items():
                                    for field, value in field_edits.items():
                                        # Get old value before replacing
                                        old_value = edited_df.at[idx, field]
                                        
                                        # Update the value
                                        edited_df.at[idx, field] = value
                                        
                                        # Update tracking columns
                                        edited_df.at[idx, "Manual_Edit"] = "Y"
                                        edited_df.at[idx, "Edit_Timestamp"] = current_time
                                        
                                        # Append to existing values if there are multiple edits
                                        current_new_value = edited_df.at[idx, "New_Value"]
                                        current_old_value = edited_df.at[idx, "Old_Value"]
                                        
                                        if current_new_value:
                                            edited_df.at[idx, "New_Value"] = f"{current_new_value}; {field}:{value}"
                                            edited_df.at[idx, "Old_Value"] = f"{current_old_value}; {field}:{old_value}"
                                        else:
                                            edited_df.at[idx, "New_Value"] = f"{field}:{value}"
                                            edited_df.at[idx, "Old_Value"] = f"{field}:{old_value}"
                            
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
                                
                                # List the edited fields
                                if manual_edit_tracking:
                                    st.subheader("Fields Edited:")
                                    edit_text = ""
                                    for edit in manual_edit_tracking:
                                        edit_text += f"- Page {edit['index']+1}, Field: {edit['field']}, "\
                                                    f"Changed from '{edit['old_value']}' to '{edit['new_value']}'\n"
                                    st.markdown(edit_text)
                                
                                # Clear edits after successful save
                                st.session_state.edited_data[selected_file["base_name"]] = {}
                                # Update the CSV in session state
                                st.session_state.csv_df = edited_df
                            else:
                                st.error("Failed to save edits")
                        except Exception as e:
                            st.error(f"Error saving edits: {str(e)}")
                
                # Add a Validate button
                if st.button("Validate Edits"):
                    # Apply current edits to a temporary dataframe for validation
                    temp_df = st.session_state.csv_df.copy()
                    
                    if selected_file["base_name"] in st.session_state.edited_data:
                        for idx, field_edits in st.session_state.edited_data[selected_file["base_name"]].items():
                            for field, value in field_edits.items():
                                temp_df.at[idx, field] = value
                    
                   # main.py (continued)
                                temp_df.at[idx, field] = value
                    
                    # Perform validation logic
                    validation_errors = {}
                    for index, row in temp_df.iterrows():
                        for field in st.session_state.manual_edit_fields:
                            value = row.get(field, "")
                            if pd.isna(value) or str(value).strip() == "":
                                if index not in validation_errors:
                                    validation_errors[index] = []
                                validation_errors[index].append(field)
                    
                    if validation_errors:
                        error_message = "The following fields have errors:\n"
                        for index, error_cols in validation_errors.items():
                            page_num = temp_df.at[index, "Page"] if "Page" in temp_df.columns else index + 1
                            error_message += f"Page {page_num}: {', '.join(error_cols)}\n"
                        st.error(error_message)
                        st.session_state.validation_results[selected_file["base_name"]] = validation_errors
                    else:
                        st.success("All data is valid!")
                        st.session_state.validation_results[selected_file["base_name"]] = {}
                
                # Display validation results
                if selected_file["base_name"] in st.session_state.validation_results:
                    validation_results = st.session_state.validation_results[selected_file["base_name"]]
                    if validation_results:
                        st.warning("Validation Issues:")
                        for index, error_cols in validation_results.items():
                            page_num = st.session_state.csv_df.at[index, "Page"] if "Page" in st.session_state.csv_df.columns else index + 1
                            st.write(f"Page {page_num}: {', '.join(error_cols)}")
                
                # Display list of all manual edits across all files
                st.subheader("Manual Edit Tracking")
                
                all_edits = []
                for filename, file_edits in st.session_state.edited_data.items():
                    for idx, field_edits in file_edits.items():
                        for field, new_value in field_edits.items():
                            # Get the corresponding dataframe if it's the current file
                            if filename == selected_file["base_name"] and st.session_state.csv_df is not None:
                                old_value = st.session_state.csv_df.at[idx, field] if idx < len(st.session_state.csv_df) else "Unknown"
                                page = st.session_state.csv_df.at[idx, "Page"] if "Page" in st.session_state.csv_df.columns else idx + 1
                            else:
                                old_value = "Unknown"
                                page = idx + 1
                                
                            all_edits.append({
                                "Filename": filename,
                                "Page": page,
                                "Field": field,
                                "Old Value": old_value,
                                "New Value": new_value,
                                "Edit Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                
                if all_edits:
                    edit_df = pd.DataFrame(all_edits)
                    st.dataframe(edit_df, use_container_width=True)
                else:
                    st.info("No pending edits to display")
            else:
                st.error("Failed to load CSV for editing")

    # Tab 3: Bulk Operations
    with tabs[2]:
        st.header("Bulk Operations")

        # Bulk file selection
        if matched_files:
            st.subheader("Select Files for Processing")
            
            # Option to select all files
            select_all = st.checkbox("Select All Files", value=False)
            
            if select_all:
                st.session_state.selected_files_for_bulk = list(range(len(matched_files)))
            else:
                # Multiselect widget for selecting specific files
                selected_indices = st.multiselect(
                    "Select Files to Process",
                    options=list(range(len(matched_files))),
                    format_func=lambda x: matched_files[x]["base_name"],
                    default=st.session_state.selected_files_for_bulk
                )
                st.session_state.selected_files_for_bulk = selected_indices
            
            # Display selected files
            if st.session_state.selected_files_for_bulk:
                st.write("Selected Files:")
                selected_files_df = pd.DataFrame([matched_files[i] for i in st.session_state.selected_files_for_bulk])
                st.dataframe(selected_files_df[["base_name"]], use_container_width=True)
            else:
                st.info("No files selected for bulk processing")

        # Bulk upload to final container
        st.subheader("Bulk Upload to Final Container")

        final_container = config.get("final_output_container", container_name)
        final_prefix = config.get("final_output_prefix", "final_output/")

        st.write(f"Target Container: {final_container}")
        st.write(f"Target Prefix: {final_prefix}")

        # Only enable upload if files are selected
        upload_button_disabled = len(st.session_state.selected_files_for_bulk) == 0
        
        if st.button("Upload Selected Files to Final Container", disabled=upload_button_disabled):
            with st.spinner("Processing bulk upload..."):
                # Create a container to display results
                result_container = st.container()
                
                # Initialize tracking
                upload_results = []
                
                # List of files to process
                files_to_process = [matched_files[i] for i in st.session_state.selected_files_for_bulk]
                
                progress_bar = st.progress(0)
                status_text = st.empty()

                for i, match in enumerate(files_to_process):
                    try:
                        # Update progress
                        progress_bar.progress((i + 1) / len(files_to_process))
                        status_text.text(f"Processing {i+1}/{len(files_to_process)}: {match['base_name']}")

                        # Download source PDF
                        pdf_content = download_blob_to_memory(blob_service_client, container_name, match["source_blob"])
                        # Download CSV results
                        csv_df = load_csv_from_blob(blob_service_client, container_name, match["processed_blob"])

                        result_entry = {
                            "Filename": match['base_name'],
                            "PDF Status": "❌ Failed",
                            "PDF Path": "",
                            "CSV Status": "❌ Failed",
                            "CSV Path": ""
                        }

                        if pdf_content and csv_df is not None:
                            # Initialize tracking columns if needed
                            csv_df = initialize_tracking_columns(csv_df)
                            
                            # Upload PDF to final container
                            pdf_output_blob_name = f"{final_prefix}pdf/{match['base_name']}.pdf"
                            pdf_success, pdf_url = upload_to_blob_storage(
                                blob_service_client,
                                final_container,
                                pdf_output_blob_name,
                                pdf_content,
                                "application/pdf"
                            )

                            # Update PDF status
                            if pdf_success:
                                result_entry["PDF Status"] = "✅ Success"
                                result_entry["PDF Path"] = pdf_output_blob_name

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

                            # Update CSV status
                            if csv_success:
                                result_entry["CSV Status"] = "✅ Success"
                                result_entry["CSV Path"] = csv_output_blob_name

                        # Add to results regardless of success/failure
                        upload_results.append(result_entry)

                    except Exception as e:
                        # Add error entry
                        upload_results.append({
                            "Filename": match['base_name'],
                            "PDF Status": "❌ Error",
                            "PDF Path": "",
                            "CSV Status": "❌ Error",
                            "CSV Path": "",
                            "Error": str(e)
                        })

                # Final update
                progress_bar.progress(1.0)
                status_text.text("Bulk upload complete")

                # Count successes and failures
                pdf_success_count = sum(1 for r in upload_results if r["PDF Status"] == "✅ Success")
                csv_success_count = sum(1 for r in upload_results if r["CSV Status"] == "✅ Success")
                total_files = len(upload_results)

                # Display detailed results
                with result_container:
                    st.success(f"Bulk upload completed.")
                    
                    # Display metrics
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Total Files", total_files)
                    col2.metric("PDF Success", f"{pdf_success_count}/{total_files}")
                    col3.metric("CSV Success", f"{csv_success_count}/{total_files}")
                    
                    # Show detailed results
                    st.subheader("Upload Results")
                    results_df = pd.DataFrame(upload_results)
                    st.dataframe(results_df, use_container_width=True)

        # Bulk download
        st.subheader("Bulk Download")

        if st.button("Download Selected Files", disabled=upload_button_disabled):
            with st.spinner("Preparing download..."):
                # Create in-memory zip file
                import zipfile
                from io import BytesIO

                zip_buffer = BytesIO()
                
                # List of files to download
                files_to_download = [matched_files[i] for i in st.session_state.selected_files_for_bulk]
                
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    # Add each matching file to the zip
                    for match in files_to_download:
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
            if key != "app_view":  # Keep app_view to stay in the main app
                del st.session_state[key]

        # Force garbage collection
        gc.collect()

        st.sidebar.success("Memory cleared!")
        st.rerun()
    
    # Go back to welcome page
    if st.sidebar.button("Back to Welcome Page"):
        st.session_state.app_view = "welcome"
        st.rerun()

    # Footer with system info
    st.sidebar.markdown("---")
    st.sidebar.info(
        f"Container: {container_name}\n\n"
        f"Source: {source_prefix}\n\n"
        f"Results: {processed_prefix}\n\n"
        f"Files: {len(matched_files) if 'matched_files' in locals() else 0}"
    )
