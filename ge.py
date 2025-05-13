# main.py, within the "Save Edits" block

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
                                        current_new_value = edited_df.at[idx, "New_Value"] if 'New_Value' in edited_df.columns else ""
                                        current_old_value = edited_df.at[idx, "Old_Value"] if 'Old_Value' in edited_df.columns else ""

                                        new_value_str = f"{field}:{value}"
                                        old_value_str = f"{field}:{old_value}"

                                        edited_df.at[idx, "New_Value"] = f"{current_new_value}; {new_value_str}" if current_new_value else new_value_str
                                        edited_df.at[idx, "Old_Value"] = f"{current_old_value}; {old_value_str}" if current_old_value else old_value_str

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
                                        edit_text += f"- Page {edit['index']+1}, Field: {edit['field']}, "                                                     f"Changed from '{edit['old_value']}' to '{edit['new_value']}'\n"
                                    st.markdown(edit_text)
                                
                                # Clear edits after successful save
                                st.session_state.edited_data[selected_file["base_name"]] = {}
                                # Update the CSV in session state
                                st.session_state.csv_df = edited_df
                            else:
                                st.error("Failed to save edits")
                        except Exception as e:
                            st.error(f"Error saving edits: {str(e)}")

# main.py, within the Manual Edit tab, in the loop that displays fields:

                            for field in st.session_state.manual_edit_fields:
                                # Get field value and confidence
                                field_value = row.get(field, "")
                                confidence_cols = [col for col in row.index if field in col and "Confidence" in col]
                                confidence = row.get(confidence_cols[0], 0) if confidence_cols else 0

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
                                    st.markdown(f'<div style="height:32px;margin-top:25px;"><span style="color:{confidence_color};font-weight:bold;">{confidence:.1f}%</span></div>',                                               unsafe_allow_html=True)

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

# main.py, in the "Bulk Operations" tab:

    # Tab 3: Bulk Operations
    with tabs[2]:
        st.header("Bulk Operations")

        # Bulk upload to final container
        st.subheader("Bulk Upload to Final Container")

        final_container = config.get("final_output_container", container_name)
        final_prefix = config.get("final_output_prefix", "final_output/")

        st.write(f"Target Container: {final_container}")
        st.write(f"Target Prefix: {final_prefix}")

        upload_option = st.radio("Select Upload Option", ["Upload All Files", "Upload Separate Files"])

        if upload_option == "Upload All Files":
            if st.button("Upload All Files to Final Container"):
                with st.spinner("Processing bulk upload..."):
                    # Create a container to display results
                    result_container = st.container()
                    
                    # Initialize tracking
                    upload_results = []
                    
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

        elif upload_option == "Upload Separate Files":
            # Placeholder for logic to group files
            # grouped_files = group_files_logic(matched_files)  # Implement this function
            st.warning("Separate file upload logic not implemented yet.  You'll need to add the grouping and upload logic here.")

            if st.button("Upload Separate Files"):
                # Implement your logic to group files and upload them separately here
                # For example, you might group by a common prefix or pattern in the filename
                # You'll need to adapt the existing upload logic to handle the grouped files
                pass
