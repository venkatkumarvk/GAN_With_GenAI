# Inside the submitted = st.form_submit_button("Save Edits") block
# Replace the blob upload section with this:

# Save to blob storage - ONLY to the final output container
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

# Upload to blob storage (final container only)
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



-----------------------------

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
            status_text.text("Preparing files...")
            
            # Track results
            update_results = []
            prepared_files = []
            
            # Process each file with edits
            file_count = len(st.session_state.edited_data)
            processed_count = 0
            
            for file_name, file_edits in st.session_state.edited_data.items():
                if not file_edits:  # Skip files with no edits
                    continue
                    
                processed_count += 1
                progress_bar.progress(processed_count / file_count)
                status_text.text(f"Preparing {processed_count}/{file_count}: {file_name}")
                
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
                            
                            # Fix potential dtype issues with proper casting
                            # For numeric fields, ensure proper type conversion
                            try:
                                if pd.api.types.is_numeric_dtype(csv_df[field].dtype):
                                    try:
                                        # Try to convert to the appropriate numeric type
                                        if pd.api.types.is_integer_dtype(csv_df[field].dtype):
                                            value = int(float(value)) if value else 0
                                        else:
                                            value = float(value) if value else 0.0
                                    except ValueError:
                                        # If conversion fails, convert column to string type
                                        csv_df[field] = csv_df[field].astype(str)
                                        old_value = str(old_value)
                            except:
                                # If any error occurs, just treat as strings
                                pass
                            
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
                    
                    # Don't save - just prepare the file for the user to download or use in bulk operations
                    prepared_files.append({
                        "filename": file_name,
                        "df": csv_df,
                        "match": file_match
                    })
                    
                    update_results.append({
                        "Filename": file_name,
                        "Status": "✅ Ready",
                        "Message": f"Changes prepared for {len(file_edits)} rows"
                    })
                    
                except Exception as e:
                    update_results.append({
                        "Filename": file_name,
                        "Status": "❌ Failed",
                        "Error": str(e)
                    })
            
            # Store prepared files in session state for bulk operations
            st.session_state.prepared_files = prepared_files
            
            # Show results
            progress_bar.progress(1.0)
            status_text.text("Preparation complete")
            
            st.success("All updates prepared for use in bulk operations. You can now use 'Bulk Upload' or 'Bulk Download' to save these changes.")
            
            st.subheader("Update Status")
            results_df = pd.DataFrame(update_results)
            st.dataframe(results_df, use_container_width=True)
            
            # If the current file was updated, update the session state
            for prepared_file in prepared_files:
                if prepared_file["filename"] == selected_file["base_name"]:
                    st.session_state.csv_df = prepared_file["df"]
                    break
            
    except Exception as e:
        st.error(f"Error preparing updates: {str(e)}")
        import traceback
        st.error(traceback.format_exc())

--------------------

# Before displaying matched_df, modify it to include date and time
if matched_files:
    # Get blob properties for creation time
    for i, match in enumerate(matched_files):
        try:
            # Get blob properties for source blob
            container_client = blob_service_client.get_container_client(container_name)
            blob_client = container_client.get_blob_client(match["source_blob"])
            properties = blob_client.get_blob_properties()
            
            # Extract creation time and convert to local time
            creation_time = properties.creation_time
            if creation_time:
                # Format as date and time strings
                matched_files[i]["creation_date"] = creation_time.strftime("%Y-%m-%d")
                matched_files[i]["creation_time"] = creation_time.strftime("%H:%M:%S")
            else:
                matched_files[i]["creation_date"] = "Unknown"
                matched_files[i]["creation_time"] = "Unknown"
        except Exception as e:
            print(f"Error getting blob properties: {e}")
            matched_files[i]["creation_date"] = "Error"
            matched_files[i]["creation_time"] = "Error"
    
    # Create dataframe with additional columns
    matched_df = pd.DataFrame(matched_files)
    st.write(f"Found {len(matched_files)} matched files")
    st.dataframe(matched_df[["base_name", "source_blob", "processed_blob", "creation_date", "creation_time"]], use_container_width=True)

------------------------------
# Within the "Upload Selected Files to Final Container" button handler
# Replace the file processing with:

for i, match in enumerate(files_to_upload):
    try:
        # Update progress
        progress_bar.progress((i + 1) / len(files_to_upload))
        status_text.text(f"Processing {i+1}/{len(files_to_upload)}: {match['base_name']}")

        # Check if we have a prepared version of this file
        prepared_file = None
        if 'prepared_files' in st.session_state:
            prepared_file = next((f for f in st.session_state.prepared_files if f["filename"] == match["base_name"]), None)
        
        # Download source PDF
        pdf_content = download_blob_to_memory(blob_service_client, container_name, match["source_blob"])
        
        # Get CSV results - use prepared version if available
        if prepared_file is not None:
            csv_df = prepared_file["df"]
            print(f"Using prepared version of {match['base_name']} with manual edits")
        else:
            # Otherwise load from blob
            csv_df = load_csv_from_blob(blob_service_client, container_name, match["processed_blob"])
            print(f"Using original version of {match['base_name']} from blob")

        result_entry = {
            "Filename": match['base_name'],
            "PDF Status": "❌ Failed",
            "PDF Path": "",
            "CSV Status": "❌ Failed",
            "CSV Path": "",
            "Has Manual Edits": "No"
        }

        if pdf_content and csv_df is not None:
            # Check if there are manual edits
            has_edits = "Manual_Edit" in csv_df.columns and csv_df["Manual_Edit"].eq("Y").any()
            result_entry["Has Manual Edits"] = "Yes" if has_edits else "No"
            
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

            # Fix any potential dtype issues before converting to CSV
            # Convert numeric columns with mixed types to string
            for col in csv_df.columns:
                if pd.api.types.is_numeric_dtype(csv_df[col].dtype):
                    try:
                        # Test if we can convert all values to the appropriate type
                        _ = pd.to_numeric(csv_df[col], errors='raise')
                    except:
                        # If not, convert to string
                        csv_df[col] = csv_df[col].astype(str)
            
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
            "Has Manual Edits": "Unknown",
            "Error": str(e)
        })

------------
def safe_cast_value(value, target_dtype):
    """
    Safely cast a value to the target dtype, returning a string if it fails.
    """
    if pd.isna(value):
        if pd.api.types.is_integer_dtype(target_dtype):
            return 0
        elif pd.api.types.is_float_dtype(target_dtype):
            return 0.0
        else:
            return ""
    
    try:
        if pd.api.types.is_integer_dtype(target_dtype):
            return int(float(value))
        elif pd.api.types.is_float_dtype(target_dtype):
            return float(value)
        else:
            return str(value)
    except (ValueError, TypeError):
        return str(value)

  -------
# Instead of direct assignment like this:
csv_df.at[idx, field] = value

# Do this:
if pd.api.types.is_numeric_dtype(csv_df[field].dtype):
    csv_df.at[idx, field] = safe_cast_value(value, csv_df[field].dtype)
else:
    csv_df.at[idx, field] = value
-------------------------
# Match source and processed files
def match_source_and_processed_files(source_blobs, processed_blobs):
    """Match source PDFs with their processed CSV results."""
    source_filenames = {get_filename_from_blob_path(blob.name).split('.')[0]: blob for blob in source_blobs}
    processed_filenames = {get_filename_from_blob_path(blob.name).split('.')[0]: blob for blob in processed_blobs}

    matched_files = []
    for base_name in set(source_filenames.keys()) & set(processed_filenames.keys()):
        source_blob = source_filenames[base_name]
        processed_blob = processed_filenames[base_name]
        
        # Convert creation time to local time string
        source_date = source_blob.creation_time.strftime("%Y-%m-%d") if hasattr(source_blob, 'creation_time') else "Unknown"
        source_time = source_blob.creation_time.strftime("%H:%M:%S") if hasattr(source_blob, 'creation_time') else "Unknown"
        
        processed_date = processed_blob.creation_time.strftime("%Y-%m-%d") if hasattr(processed_blob, 'creation_time') else "Unknown"
        processed_time = processed_blob.creation_time.strftime("%H:%M:%S") if hasattr(processed_blob, 'creation_time') else "Unknown"
        
        matched_files.append({
            "base_name": base_name,
            "source_blob": source_blob.name,
            "source_date": source_date,
            "source_time": source_time,
            "processed_blob": processed_blob.name,
            "processed_date": processed_date,
            "processed_time": processed_time
        })

    return matched_files
    ---------------
    # In Results View tab, replace the matched files display:
# Display matched files in a table with date/time
matched_display_df = pd.DataFrame(matched_files)[["base_name", "source_date", "source_time", 
                                                 "processed_date", "processed_time"]]
st.write(f"Found {len(matched_files)} matched files")
st.dataframe(matched_display_df, use_container_width=True)

--------
# Replace the "Apply All Updates" button code with this:
if st.button("Apply All Updates and Prepare Download"):
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
            
            # Create in-memory zip file for download
            import zipfile
            from io import BytesIO
            
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
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
                        st.warning(f"File not found in matched files: {file_name}")
                        continue
                    
                    # Load the CSV and PDF
                    csv_df = load_csv_from_blob(blob_service_client, container_name, file_match["processed_blob"])
                    pdf_content = download_blob_to_memory(blob_service_client, container_name, file_match["source_blob"])
                    
                    if csv_df is None:
                        st.warning(f"Could not load CSV data for {file_name}")
                        continue
                    
                    if pdf_content is None:
                        st.warning(f"Could not load PDF data for {file_name}")
                    
                    # Apply edits
                    try:
                        # Ensure tracking columns exist
                        for col in ["Manual_Edit", "Edit_Timestamp", "Manually_Edited_Fields", "Original_Values", "New_Values"]:
                            if col not in csv_df.columns:
                                csv_df[col] = ""
                        
                        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        for idx, field_edits in file_edits.items():
                            for field, value in field_edits.items():
                                # Fix for dtype warning - ensure value types match
                                # First determine the column dtype
                                if pd.api.types.is_numeric_dtype(csv_df[field].dtype):
                                    # Convert value to numeric if the column is numeric
                                    try:
                                        value = pd.to_numeric(value)
                                    except ValueError:
                                        # If conversion fails, convert the column to object type
                                        csv_df[field] = csv_df[field].astype(object)
                                
                                # Get old value before replacing
                                old_value = csv_df.at[int(idx), field]
                                
                                # Update the value
                                csv_df.at[int(idx), field] = value
                                
                                # Update tracking columns
                                csv_df.at[int(idx), "Manual_Edit"] = "Y"
                                csv_df.at[int(idx), "Edit_Timestamp"] = current_time
                                
                                # Update edited fields tracking
                                # Handle fields that may have NaN values
                                def safe_get(df, idx, col):
                                    val = df.at[int(idx), col]
                                    return "" if pd.isna(val) else str(val)
                                
                                current_edited_fields = safe_get(csv_df, idx, "Manually_Edited_Fields")
                                current_old_values = safe_get(csv_df, idx, "Original_Values")
                                current_new_values = safe_get(csv_df, idx, "New_Values")
                                
                                # Add/update field in tracking lists
                                field_list = current_edited_fields.split("; ") if current_edited_fields else []
                                if field not in field_list:
                                    field_list.append(field)
                                csv_df.at[int(idx), "Manually_Edited_Fields"] = "; ".join(field_list)
                                
                                # Add old/new values
                                old_values_dict = {}
                                new_values_dict = {}
                                
                                # Parse existing values
                                if current_old_values:
                                    for item in current_old_values.split("; "):
                                        if ":" in item:
                                            key, val = item.split(":", 1)
                                            old_values_dict[key] = val
                                
                                if current_new_values:
                                    for item in current_new_values.split("; "):
                                        if ":" in item:
                                            key, val = item.split(":", 1)
                                            new_values_dict[key] = val
                                
                                # Update values
                                old_values_dict[field] = str(old_value)
                                new_values_dict[field] = str(value)
                                
                                # Convert back to strings
                                csv_df.at[int(idx), "Original_Values"] = "; ".join([f"{k}:{v}" for k, v in old_values_dict.items()])
                                csv_df.at[int(idx), "New_Values"] = "; ".join([f"{k}:{v}" for k, v in new_values_dict.items()])
                        
                        # Add to zip file
                        # Add PDF
                        if pdf_content:
                            zip_file.writestr(f"pdf/{file_name}.pdf", pdf_content)
                        
                        # Add CSV
                        csv_buffer = io.StringIO()
                        csv_df.to_csv(csv_buffer, index=False)
                        zip_file.writestr(f"csv/{file_name}.csv", csv_buffer.getvalue())
                        
                        # Clear edits for this file as they've been applied
                        st.session_state.edited_data[file_name] = {}
                        
                    except Exception as e:
                        st.warning(f"Error processing edits for {file_name}: {str(e)}")
                        import traceback
                        print(traceback.format_exc())
            
            # Reset buffer position
            zip_buffer.seek(0)
            
            # Show download button
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Update progress
            progress_bar.progress(1.0)
            status_text.text("Processing complete! You can now download the results.")
            
            st.download_button(
                label="Download All Edited Files",
                data=zip_buffer,
                file_name=f"edited_invoices_{confidence_selection}_{timestamp}.zip",
                mime="application/zip"
            )
            
            # If the current file was updated, reload it to show changes
            if st.session_state.csv_df is not None:
                st.success("All edits applied and ready for download.")
            
    except Exception as e:
        st.error(f"Error applying updates: {str(e)}")
        import traceback
        st.error(traceback.format_exc())
