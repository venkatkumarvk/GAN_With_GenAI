# In the Manual Edit tab, in the submitted form handler, update the code:

if submitted:
    try:
        # Apply edits to the dataframe
        edited_df = st.session_state.csv_df.copy()
        
        # Ensure tracking columns exist
        for col in ["Manual_Edit", "Edit_Timestamp", "New_Value", "Old_Value"]:
            if col not in edited_df.columns:
                edited_df[col] = ""  # Add the columns if they don't exist
                
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
                    
                    # Ensure the tracking columns exist and update them
                    if "New_Value" not in edited_df.columns:
                        edited_df["New_Value"] = ""
                    if "Old_Value" not in edited_df.columns:
                        edited_df["Old_Value"] = ""
                        
                    # Append to existing values if there are multiple edits
                    current_new_value = edited_df.at[idx, "New_Value"] if pd.notna(edited_df.at[idx, "New_Value"]) else ""
                    current_old_value = edited_df.at[idx, "Old_Value"] if pd.notna(edited_df.at[idx, "Old_Value"]) else ""
                    
                    if current_new_value:
                        edited_df.at[idx, "New_Value"] = f"{current_new_value}; {field}:{value}"
                        edited_df.at[idx, "Old_Value"] = f"{current_old_value}; {field}:{old_value}"
                    else:
                        edited_df.at[idx, "New_Value"] = f"{field}:{value}"
                        edited_df.at[idx, "Old_Value"] = f"{field}:{old_value}"

        # Rest of the code remains unchanged

  # First, update the code that finds confidence columns in the manual editing section
# In the section where you load the CSV:

if st.session_state.csv_df is None:
    processed_blob = matched_files[selected_file_idx]["processed_blob"]
    st.session_state.csv_df = load_csv_from_blob(blob_service_client, container_name, processed_blob)
    
    # Get fields that can be edited (exclude metadata columns)
    if st.session_state.csv_df is not None:
        exclude_columns = ["Page", "Filename", "Extraction_Timestamp", "Manual_Edit", "Edit_Timestamp", 
                          "New_Value", "Old_Value"]
        
        # Handle different confidence column naming conventions
        confidence_cols = []
        for col in st.session_state.csv_df.columns:
            if col.endswith("Confidence") or col.endswith("_Confidence") or " Confidence" in col:
                confidence_cols.append(col)
        
        # Identify which field columns have corresponding confidence columns
        field_to_confidence = {}
        for conf_col in confidence_cols:
            # Try different patterns
            for field in st.session_state.csv_df.columns:
                if conf_col == f"{field} Confidence" or conf_col == f"{field}_Confidence":
                    field_to_confidence[field] = conf_col
                    break
        
        # Store the mapping in session state
        st.session_state.field_to_confidence = field_to_confidence
        
        # Get editable fields by excluding all metadata and confidence columns
        st.session_state.manual_edit_fields = [col for col in st.session_state.csv_df.columns 
                                            if col not in exclude_columns and col not in confidence_cols]

# In the Manual Edit tab, in the form section:

# Create field label with confidence indicator
confidence_field = None
for conf_pattern in [f"{field} Confidence", f"{field}_Confidence"]:
    if conf_pattern in st.session_state.csv_df.columns:
        confidence_field = conf_pattern
        break

if confidence_field:
    confidence = row.get(confidence_field, 0)
else:
    # If no matching confidence field found
    confidence = 0

# Ensure confidence is a number
try:
    confidence = float(confidence)
except (ValueError, TypeError):
    confidence = 0

confidence_color = "green" if confidence >= 95 else "red"
field_label = f"{field} ({confidence:.1f}%)"


# In the Bulk Operations tab:

st.subheader("Bulk Upload to Final Container")

final_container = config.get("final_output_container", container_name)
final_prefix = config.get("final_output_prefix", "final_output/")

st.write(f"Target Container: {final_container}")
st.write(f"Target Prefix: {final_prefix}")

# Add file selection options
file_selection_mode = st.radio(
    "File Selection Mode:",
    ["Select All Files", "Select Individual Files"]
)

files_to_upload = []
if file_selection_mode == "Select All Files":
    files_to_upload = matched_files
else:
    # Show checkboxes for each file
    st.write("Select files to upload:")
    file_selections = {}
    for i, match in enumerate(matched_files):
        file_selections[i] = st.checkbox(match["base_name"], value=False, key=f"select_file_{i}")
    
    # Get selected files
    files_to_upload = [matched_files[i] for i, selected in file_selections.items() if selected]

# Show how many files are selected
if files_to_upload:
    st.write(f"Selected {len(files_to_upload)} files for upload")
else:
    st.warning("No files selected for upload")

if st.button("Upload Selected Files to Final Container"):
    if not files_to_upload:
        st.warning("Please select at least one file to upload")
    else:
        with st.spinner("Processing bulk upload..."):
            # Rest of your upload code, but use files_to_upload instead of matched_files
            # ...
            
            # Update progress calculation
            for i, match in enumerate(files_to_upload):
                # Update progress
                progress_bar.progress((i + 1) / len(files_to_upload))
                # Rest of the upload code

#Here are the full sections that need to be replaced:
Manual Edit Tab (for issues 1 and 2):

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
            
            # Get fields that can be edited (exclude metadata columns)
            if st.session_state.csv_df is not None:
                exclude_columns = ["Page", "Filename", "Extraction_Timestamp", "Manual_Edit", "Edit_Timestamp", 
                                  "New_Value", "Old_Value"]
                
                # Handle different confidence column naming conventions
                confidence_cols = []
                for col in st.session_state.csv_df.columns:
                    if col.endswith("Confidence") or col.endswith("_Confidence") or " Confidence" in col:
                        confidence_cols.append(col)
                
                # Identify which field columns have corresponding confidence columns
                field_to_confidence = {}
                for conf_col in confidence_cols:
                    # Try different patterns
                    for field in st.session_state.csv_df.columns:
                        if conf_col == f"{field} Confidence" or conf_col == f"{field}_Confidence":
                            field_to_confidence[field] = conf_col
                            break
                
                # Store the mapping in session state
                st.session_state.field_to_confidence = field_to_confidence
                
                # Get editable fields by excluding all metadata and confidence columns
                st.session_state.manual_edit_fields = [col for col in st.session_state.csv_df.columns 
                                                    if col not in exclude_columns and col not in confidence_cols]
                
                # Ensure tracking columns exist
                for col in ["Manual_Edit", "Edit_Timestamp", "New_Value", "Old_Value"]:
                    if col not in st.session_state.csv_df.columns:
                        st.session_state.csv_df[col] = ""

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
                            
                            # Find matching confidence field
                            confidence_field = None
                            if hasattr(st.session_state, 'field_to_confidence') and field in st.session_state.field_to_confidence:
                                confidence_field = st.session_state.field_to_confidence[field]
                            else:
                                # Try common patterns
                                for pattern in [f"{field} Confidence", f"{field}_Confidence"]:
                                    if pattern in st.session_state.csv_df.columns:
                                        confidence_field = pattern
                                        break
                            
                            # Get confidence value
                            if confidence_field and confidence_field in st.session_state.csv_df.columns:
                                confidence = row.get(confidence_field, 0)
                                # Ensure confidence is a number
                                try:
                                    confidence = float(confidence)
                                except (ValueError, TypeError):
                                    confidence = 0
                            else:
                                confidence = 0
                            
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
                        
                        # Ensure tracking columns exist
                        for col in ["Manual_Edit", "Edit_Timestamp", "New_Value", "Old_Value"]:
                            if col not in edited_df.columns:
                                edited_df[col] = ""  # Add the columns if they don't exist
                        
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
                                    current_new_value = edited_df.at[idx, "New_Value"] if pd.notna(edited_df.at[idx, "New_Value"]) else ""
                                    current_old_value = edited_df.at[idx, "Old_Value"] if pd.notna(edited_df.at[idx, "Old_Value"]) else ""
                                    
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
                        # Print detailed error for debugging
                        import traceback
                        st.error(traceback.format_exc())

*----------------
# Tab 3: Bulk Operations
with tabs[2]:
    st.header("Bulk Operations")

    # Bulk upload to final container
    st.subheader("Bulk Upload to Final Container")

    final_container = config.get("final_output_container", container_name)
    final_prefix = config.get("final_output_prefix", "final_output/")

    st.write(f"Target Container: {final_container}")
    st.write(f"Target Prefix: {final_prefix}")

    # Add file selection options
    file_selection_mode = st.radio(
        "File Selection Mode:",
        ["Select All Files", "Select Individual Files"]
    )

    files_to_upload = []
    if file_selection_mode == "Select All Files":
        files_to_upload = matched_files
    else:
        # Show checkboxes for each file
        st.write("Select files to upload:")
        file_selections = {}
        for i, match in enumerate(matched_files):
            file_selections[i] = st.checkbox(match["base_name"], value=False, key=f"select_file_{i}")
        
        # Get selected files
        files_to_upload = [matched_files[i] for i, selected in file_selections.items() if selected]

    # Show how many files are selected
    if files_to_upload:
        st.write(f"Selected {len(files_to_upload)} files for upload")
    else:
        st.warning("No files selected for upload")

    if st.button("Upload Selected Files to Final Container"):
        if not files_to_upload:
            st.warning("Please select at least one file to upload")
        else:
            with st.spinner("Processing bulk upload..."):
                # Create a container to display results
                result_container = st.container()
                
                # Initialize tracking
                upload_results = []
                
                progress_bar = st.progress(0)
                status_text = st.empty()

                for i, match in enumerate(files_to_upload):
                    try:
                        # Update progress
                        progress_bar.progress((i + 1) / len(files_to_upload))
                        status_text.text(f"Processing {i+1}/{len(files_to_upload)}: {match['base_name']}")

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
