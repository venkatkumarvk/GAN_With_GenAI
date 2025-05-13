1. Modify the "Apply All Updates" button code in the Manual Edit tab:

# Modify this part in the "Apply All Updates" button code
# Remove the update to source container, only update the final container

# Find and replace this section in the "Apply All Updates" button handler:
                                # Update in source container
                                source_success, _ = upload_to_blob_storage(
                                    blob_service_client,
                                    container_name,
                                    file_match["processed_blob"],
                                    csv_data,
                                    "text/csv"
                                )
                                
                                # Save to final container as well
                                output_container = config.get("final_output_container", container_name)
                                output_prefix = config.get("final_output_prefix", "final_output/")
                                csv_output_blob_name = f"{output_prefix}csv/{file_name}.csv"
                                
                                final_success, _ = upload_to_blob_storage(
                                    blob_service_client,
                                    output_container,
                                    csv_output_blob_name,
                                    csv_data,
                                    "text/csv"
                                )
                                
                                if source_success and final_success:
                                    update_results.append({
                                        "Filename": file_name,
                                        "Status": "✅ Success",
                                        "Message": "Updated both source and final containers"
                                    })
                                    
                                    # Clear edits for this file
                                    st.session_state.edited_data[file_name] = {}
                                else:
                                    update_results.append({
                                        "Filename": file_name,
                                        "Status": "⚠️ Partial Success",
                                        "Message": f"Source: {'✅' if source_success else '❌'}, Final: {'✅' if final_success else '❌'}"
                                    })

# Replace with this code:
                                # Save only to final container
                                output_container = config.get("final_output_container", container_name)
                                output_prefix = config.get("final_output_prefix", "final_output/")
                                csv_output_blob_name = f"{output_prefix}csv/{file_name}.csv"
                                
                                success, _ = upload_to_blob_storage(
                                    blob_service_client,
                                    output_container,
                                    csv_output_blob_name,
                                    csv_data,
                                    "text/csv"
                                )
                                
                                if success:
                                    update_results.append({
                                        "Filename": file_name,
                                        "Status": "✅ Success",
                                        "Message": "Updated final container"
                                    })
                                    
                                    # Clear edits for this file
                                    st.session_state.edited_data[file_name] = {}
                                else:
                                    update_results.append({
                                        "Filename": file_name,
                                        "Status": "❌ Failed",
                                        "Message": "Failed to update final container"
                                    })


                                2. Fix the same issue in the form submit handler

                                # In the form submit handler, also remove the update to the source container
# Find and replace this block:
                        # IMPORTANT: Also update the processed CSV in the source container
                        # This ensures bulk operations will use the updated CSV
                        processed_blob = selected_file["processed_blob"]
                        update_success, _ = upload_to_blob_storage(
                            blob_service_client,
                            container_name,
                            processed_blob,
                            csv_data,
                            "text/csv"
                        )
                        
                        if pdf_success and csv_success and update_success:
                            st.success(f"Successfully saved edits to {output_container} and updated source data")

# With this:
                        if pdf_success and csv_success:
                            st.success(f"Successfully saved edits to {output_container}")


                          3. Fix the pandas dtype incompatibility warning
To fix the dtype warning, we need to explicitly cast values to the correct types when updating dataframe values. Here's the fix:

# In both the "Save Edits" and "Apply All Updates" handlers, find where you update dataframe values
# Replace code like this:
                                        # Update the value
                                        csv_df.at[idx, field] = value

# With code like this:
                                        # Handle dtype compatibility
                                        try:
                                            # Get the original column dtype
                                            col_dtype = csv_df[field].dtype
                                            
                                            # If it's a numeric column, try to convert the value
                                            if pd.api.types.is_numeric_dtype(col_dtype):
                                                try:
                                                    # Try to convert to the appropriate numeric type
                                                    if pd.api.types.is_integer_dtype(col_dtype):
                                                        typed_value = int(value)
                                                    elif pd.api.types.is_float_dtype(col_dtype):
                                                        typed_value = float(value)
                                                    else:
                                                        typed_value = value
                                                except (ValueError, TypeError):
                                                    # If conversion fails, use the string value
                                                    typed_value = value
                                            else:
                                                # For non-numeric columns, use the string value
                                                typed_value = value
                                                
                                            # Update the value with the appropriate type
                                            csv_df.at[idx, field] = typed_value
                                            
                                        except Exception as e:
                                            # If any error occurs, fall back to string conversion
                                            print(f"Warning: Type conversion failed for {field}. Error: {str(e)}")
                                            csv_df.at[idx, field] = str(value)

                                            Replace all instances where you directly set dataframe.at[idx, field] = value with the updated code above. This will handle type conversions properly.

                                            # In the bulk operations tab, for the "Upload Selected Files to Final Container" button handler
# Make sure it's using the data from the session state if available:

for i, match in enumerate(files_to_upload):
    try:
        # Update progress
        progress_bar.progress((i + 1) / len(files_to_upload))
        status_text.text(f"Processing {i+1}/{len(files_to_upload)}: {match['base_name']}")

        # Check if we have this file in session state
        if match['base_name'] == selected_file["base_name"] and st.session_state.csv_df is not None:
            # Use the in-memory version that might have edits
            csv_df = st.session_state.csv_df.copy()
            st.info(f"Using in-memory version of {match['base_name']} with latest edits")
        else:
            # Download CSV results
            csv_df = load_csv_from_blob(blob_service_client, container_name, match["processed_blob"])
            
            # Apply any pending edits from session state
            if match['base_name'] in st.session_state.edited_data and st.session_state.edited_data[match['base_name']]:
                st.info(f"Applying pending edits to {match['base_name']}")
                
                # Apply edits
                for idx, field_edits in st.session_state.edited_data[match['base_name']].items():
                    for field, value in field_edits.items():
                        # Handle dtype compatibility with the code from above
                        try:
                            # Get the original column dtype
                            col_dtype = csv_df[field].dtype
                            
                            # If it's a numeric column, try to convert the value
                            if pd.api.types.is_numeric_dtype(col_dtype):
                                try:
                                    # Try to convert to the appropriate numeric type
                                    if pd.api.types.is_integer_dtype(col_dtype):
                                        typed_value = int(value)
                                    elif pd.api.types.is_float_dtype(col_dtype):
                                        typed_value = float(value)
                                    else:
                                        typed_value = value
                                except (ValueError, TypeError):
                                    # If conversion fails, use the string value
                                    typed_value = value
                            else:
                                # For non-numeric columns, use the string value
                                typed_value = value
                                
                            # Update the value with the appropriate type
                            csv_df.at[idx, field] = typed_value
                            
                        except Exception as e:
                            # If any error occurs, fall back to string conversion
                            print(f"Warning: Type conversion failed for {field}. Error: {str(e)}")
                            csv_df.at[idx, field] = str(value)

        # Rest of the code remains the same...
