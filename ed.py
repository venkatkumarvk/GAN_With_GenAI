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
                                  "Manually_Edited_Fields", "Original_Values", "New_Values"]
                
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
                for col in ["Manual_Edit", "Edit_Timestamp", "Manually_Edited_Fields", "Original_Values", "New_Values"]:
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
                
                # Track manual edits for this session
                current_manual_edits = []
                
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
                            
                            # Store the edited value if changed
                            if new_value != field_value:
                                if index not in st.session_state.edited_data[selected_file["base_name"]]:
                                    st.session_state.edited_data[selected_file["base_name"]][index] = {}
                                
                                # Track the edit
                                st.session_state.edited_data[selected_file["base_name"]][index][field] = new_value
                                current_manual_edits.append({
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
                        for col in ["Manual_Edit", "Edit_Timestamp", "Manually_Edited_Fields", "Original_Values", "New_Values"]:
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
                                    
                                    # Update the lists of edited fields, old values, and new values
                                    # First get the current values (if they exist)
                                    current_edited_fields = edited_df.at[idx, "Manually_Edited_Fields"] if pd.notna(edited_df.at[idx, "Manually_Edited_Fields"]) else ""
                                    current_old_values = edited_df.at[idx, "Original_Values"] if pd.notna(edited_df.at[idx, "Original_Values"]) else ""
                                    current_new_values = edited_df.at[idx, "New_Values"] if pd.notna(edited_df.at[idx, "New_Values"]) else ""
                                    
                                    # If the field is already in the edited fields list, we don't add it again
                                    if field not in current_edited_fields:
                                        # Append to existing values if there are multiple edits
                                        delimiter = "; " if current_edited_fields else ""
                                        edited_df.at[idx, "Manually_Edited_Fields"] = f"{current_edited_fields}{delimiter}{field}"
                                        
                                        # Add old value
                                        delimiter = "; " if current_old_values else ""
                                        edited_df.at[idx, "Original_Values"] = f"{current_old_values}{delimiter}{field}:{old_value}"
                                        
                                        # Add new value
                                        delimiter = "; " if current_new_values else ""
                                        edited_df.at[idx, "New_Values"] = f"{current_new_values}{delimiter}{field}:{value}"
                                    else:
                                        # Replace existing values
                                        # Parse existing values
                                        old_values_dict = {}
                                        new_values_dict = {}
                                        
                                        # Parse old values
                                        if current_old_values:
                                            for item in current_old_values.split("; "):
                                                if ":" in item:
                                                    key, val = item.split(":", 1)
                                                    old_values_dict[key] = val
                                        
                                        # Parse new values
                                        if current_new_values:
                                            for item in current_new_values.split("; "):
                                                if ":" in item:
                                                    key, val = item.split(":", 1)
                                                    new_values_dict[key] = val
                                        
                                        # Update dictionaries
                                        old_values_dict[field] = old_value
                                        new_values_dict[field] = value
                                        
                                        # Convert back to strings
                                        edited_df.at[idx, "Original_Values"] = "; ".join([f"{k}:{v}" for k, v in old_values_dict.items()])
                                        edited_df.at[idx, "New_Values"] = "; ".join([f"{k}:{v}" for k, v in new_values_dict.items()])
                        
                        # Save to final output container
                        output_container = config.get("final_output_container", container_name)
                        output_prefix = config.get("final_output_prefix", "final_output/")
                        
                        # Create output blob names
                        base_name = selected_file["base_name"]
                        pdf_output_blob_name = f"{output_prefix}pdf/{base_name}.pdf"
                        csv_output_blob_name = f"{output_prefix}csv/{base_name}.csv"
                        
                        # Convert dataframe to CSV
                        csv_buffer = io.StringIO()
                        edited_df.to_csv(csv_buffer, index=False)
                        csv_data = csv_buffer.getvalue()
                        
                        # Upload to final output container only
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
                            csv_data,
                            "text/csv"
                        )
                        
                        if pdf_success and csv_success:
                            st.success(f"Successfully saved edits to {output_container}")
                            
                            # List the edited fields
                            if current_manual_edits:
                                st.subheader("Fields Edited:")
                                edit_text = ""
                                for edit in current_manual_edits:
                                    edit_text += f"- Page {edit['index']+1}, Field: {edit['field']}, "\
                                                f"Changed from '{edit['old_value']}' to '{edit['new_value']}'\n"
                                st.markdown(edit_text)
                            
                            # Update the CSV in session state
                            st.session_state.csv_df = edited_df
                        else:
                            st.error("Failed to save edits")
                    except Exception as e:
                        st.error(f"Error saving edits: {str(e)}")
                        # Print detailed error for debugging
                        import traceback
                        st.error(traceback.format_exc())
            
            # Add button to apply all updates
            if st.button("Apply All Updates"):
                try:
                    # Check if we have edits for any file
                    has_edits = False
                    for file_edits in st.session_state.edited_data.values():
                        if file_edits:
                            has_edits = True
                            break
                    
                    if not has_edits:
                        st.info("No pending edits to apply.")
                    else:
                        # Create a progress indicator
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        status_text.text("Processing files...")
                        
                        # Track results
                        update_results = []
                        
                        # Process each file with edits
                        file_count = len(st.session_state.edited_data)
                        processed_count = 0
                        
                        for file_name, file_edits in st.session_state.edited_data.items():
                            if not file_edits:  # Skip files with no edits
                                continue
                                
                            processed_count += 1
                            progress_bar.progress(processed_count / file_count)
                            status_text.text(f"Processing {processed_count}/{file_count}: {file_name}")
                            
                            # Find the file in matched_files
                            file_match = next((m for m in matched_files if m["base_name"] == file_name), None)
                            
                            if not file_match:
                                update_results.append({
                                    "Filename": file_name,
                                    "Status": "❌ Failed",
                                    "Error": "File not found in matched files"
                                })
                                continue
                            
                            # Load the CSV
                            csv_df = load_csv_from_blob(blob_service_client, container_name, file_match["processed_blob"])
                            
                            if csv_df is None:
                                update_results.append({
                                    "Filename": file_name,
                                    "Status": "❌ Failed",
                                    "Error": "Could not load CSV data"
                                })
                                continue
                            
                            # Apply edits
                            try:
                                # Ensure tracking columns exist
                                for col in ["Manual_Edit", "Edit_Timestamp", "Manually_Edited_Fields", "Original_Values", "New_Values"]:
                                    if col not in csv_df.columns:
                                        csv_df[col] = ""
                                
                                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                
                                for idx, field_edits in file_edits.items():
                                    for field, value in field_edits.items():
                                        # Get old value before replacing
                                        old_value = csv_df.at[idx, field]
                                        
                                        # Update the value
                                        csv_df.at[idx, field] = value
                                        
                                        # Update tracking columns
                                        csv_df.at[idx, "Manual_Edit"] = "Y"
                                        csv_df.at[idx, "Edit_Timestamp"] = current_time
                                        
                                        # Update the lists of edited fields, old values, and new values
                                        current_edited_fields = csv_df.at[idx, "Manually_Edited_Fields"] if pd.notna(csv_df.at[idx, "Manually_Edited_Fields"]) else ""
                                        current_old_values = csv_df.at[idx, "Original_Values"] if pd.notna(csv_df.at[idx, "Original_Values"]) else ""
                                        current_new_values = csv_df.at[idx, "New_Values"] if pd.notna(csv_df.at[idx, "New_Values"]) else ""
                                        
                                        # If the field is already in the edited fields list, we don't add it again
                                        if field not in current_edited_fields:
                                            # Append to existing values if there are multiple edits
                                            delimiter = "; " if current_edited_fields else ""
                                            csv_df.at[idx, "Manually_Edited_Fields"] = f"{current_edited_fields}{delimiter}{field}"
                                            
                                            # Add old value
                                            delimiter = "; " if current_old_values else ""
                                            csv_df.at[idx, "Original_Values"] = f"{current_old_values}{delimiter}{field}:{old_value}"
                                            
                                            # Add new value
                                            delimiter = "; " if current_new_values else ""
                                            csv_df.at[idx, "New_Values"] = f"{current_new_values}{delimiter}{field}:{value}"
                                        else:
                                            # Replace existing values
                                            # Parse existing values
                                            old_values_dict = {}
                                            new_values_dict = {}
                                            
                                            # Parse old values
                                            if current_old_values:
                                                for item in current_old_values.split("; "):
                                                    if ":" in item:
                                                        key, val = item.split(":", 1)
                                                        old_values_dict[key] = val
                                            
                                            # Parse new values
                                            if current_new_values:
                                                for item in current_new_values.split("; "):
                                                    if ":" in item:
                                                        key, val = item.split(":", 1)
                                                        new_values_dict[key] = val
                                            
                                            # Update dictionaries
                                            old_values_dict[field] = old_value
                                            new_values_dict[field] = value
                                            
                                            # Convert back to strings
                                            csv_df.at[idx, "Original_Values"] = "; ".join([f"{k}:{v}" for k, v in old_values_dict.items()])
                                            csv_df.at[idx, "New_Values"] = "; ".join([f"{k}:{v}" for k, v in new_values_dict.items()])
                                
                                # Save to final container only
                                output_container = config.get("final_output_container", container_name)
                                output_prefix = config.get("final_output_prefix", "final_output/")
                                csv_output_blob_name = f"{output_prefix}csv/{file_name}.csv"
                                
                                # Convert dataframe to CSV
                                csv_buffer = io.StringIO()
                                csv_df.to_csv(csv_buffer, index=False)
                                csv_data = csv_buffer.getvalue()
                                
                                # Save to final container
                                final_success, _ = upload_to_blob_storage(
                                    blob_service_client,
                                    output_container,
                                    csv_output_blob_name,
                                    csv_data,
                                    "text/csv"
                                )
                                
                                if final_success:
                                    update_results.append({
                                        "Filename": file_name,
                                        "Status": "✅ Success",
                                        "Message": "Updated final container successfully"
                                    })
                                    
                                    # Clear edits for this file
                                    st.session_state.edited_data[file_name] = {}
                                else:
                                    update_results.append({
                                        "Filename": file_name,
                                        "Status": "❌ Failed",
                                        "Message": "Failed to update final container"
                                    })
                                    
                            except Exception as e:
                                update_results.append({
                                    "Filename": file_name,
                                    "Status": "❌ Failed",
                                    "Error": str(e)
                                })
                        
                        # Show results
                        progress_bar.progress(1.0)
                        status_text.text("Processing complete")
                        
                        st.subheader("Update Results")
                        results_df = pd.DataFrame(update_results)
                        st.dataframe(results_df, use_container_width=True)
                        
                        # If the current file was updated, reload it
                        if st.session_state.csv_df is not None and selected_file["base_name"] in st.session_state.edited_data and not st.session_state.edited_data[selected_file["base_name"]]:
                            # We're not updating the input blob, so no need to reload
                            st.success("All updates applied successfully to final output container.")
                    
                except Exception as e:
                    st.error(f"Error applying updates: {str(e)}")
                    import traceback
                    st.error(traceback.format_exc())
