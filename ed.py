# Apply edits to CSV
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
                                        edit_text += f"- Page {edit['index']+1}, Field: {edit['field']}, "                                                    f"Changed from '{edit['old_value']}' to '{edit['new_value']}'\n"
                                    st.markdown(edit_text)
                                
                                # Clear edits after successful save
                                st.session_state.edited_data[selected_file["base_name"]] = {}
                                # Update the CSV in session state
                                st.session_state.csv_df = edited_df
                            else:
                                st.error("Failed to save edits")
                        except Exception as e:
                            st.error(f"Error saving edits: {str(e)}")
