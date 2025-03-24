def add_manual_verification_section(all_pdf_results, timestamp, blob_service_client=None, result_upload_container=None):
    """
    Simplified manual verification section that allows editing regardless of confidence score.
    Prevents form submission issues when pressing Enter in text fields.
    """
    st.subheader("4. Manual Verification and Editing")
    
    # Store the session state for edits
    if 'edited_results' not in st.session_state:
        st.session_state.edited_results = all_pdf_results.copy()
        
    # Define the fields we're extracting
    fields = [
        "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
        "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
        "Freight", "Salestax", "Total"
    ]
    
    # Create a single "Update All" button outside of any forms to prevent Enter key issues
    if st.button("Update All Fields", type="primary", key="update_all_button"):
        st.success("All edits have been applied. Scroll down to download or upload updated files.")
        # Continue processing after this point
    
    # Create tabs for each PDF
    if len(all_pdf_results) > 0:
        pdf_tabs = st.tabs([pdf_result["filename"] for pdf_result in all_pdf_results])
        
        for i, tab in enumerate(pdf_tabs):
            with tab:
                pdf_result = all_pdf_results[i]
                filename = pdf_result["filename"]
                
                st.write(f"### Editing: {filename}")
                
                # Create expandable sections for each page
                for page_idx, page in enumerate(pdf_result["pages"]):
                    page_num = page["page"]
                    data = page["data"]
                    
                    with st.expander(f"Page {page_num}", expanded=False):
                        if "error" in data:
                            st.error(f"Error processing this page: {data['error']}")
                            continue
                        
                        # Use columns for a more compact layout
                        cols = st.columns(2)
                        
                        # Create input fields for each field without using st.form
                        for idx, field in enumerate(fields):
                            field_display = ' '.join(field.replace('_', ' ').title().split())
                            
                            # Get current value from session state if exists, otherwise from original data
                            field_data = data.get(field, {})
                            
                            if isinstance(field_data, dict):
                                current_value = field_data.get("value", "")
                            else:
                                current_value = field_data if field_data else ""
                            
                            # Get value from session state to maintain persistence
                            if f"{filename}_{page_num}_{field}" in st.session_state:
                                current_value = st.session_state[f"{filename}_{page_num}_{field}"]
                            
                            # Create input field with appropriate column
                            col_idx = 0 if idx < len(fields)//2 + len(fields)%2 else 1
                            with cols[col_idx]:
                                new_value = st.text_input(
                                    f"{field_display}",
                                    value=current_value,
                                    key=f"{filename}_{page_num}_{field}"
                                )
                                
                                # Update session state immediately when value changes
                                if new_value != current_value or f"{filename}_{page_num}_{field}_changed" not in st.session_state:
                                    # Get original confidence value
                                    original_field_data = data.get(field, {})
                                    original_confidence = 0
                                    
                                    if isinstance(original_field_data, dict) and "confidence" in original_field_data:
                                        original_confidence = original_field_data.get("confidence", 0)
                                    
                                    # Update with edited value but keep original confidence
                                    st.session_state.edited_results[i]["pages"][page_idx]["data"][field] = {
                                        "value": new_value,
                                        "confidence": original_confidence,
                                        "manually_edited": True
                                    }
                                    
                                    # Mark this field as changed
                                    st.session_state[f"{filename}_{page_num}_{field}_changed"] = True
    
    # Create a section for downloading updated files
    st.subheader("Download Updated Files")
    
    # Create updated text files and CSV
    text_zip = create_text_files_zip(st.session_state.edited_results)
    results_df = create_results_dataframe(st.session_state.edited_results)
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Download updated text files as a zip
        st.download_button(
            label="Download Updated Text Files (ZIP)",
            data=text_zip,
            file_name=f"extracted_data_{timestamp}_edited.zip",
            mime="application/zip"
        )
    
    with col2:
        # Download updated CSV
        csv = results_df.to_csv(index=False)
        st.download_button(
            label="Download Updated CSV Results",
            data=csv,
            file_name=f"financial_data_extraction_{timestamp}_edited.csv",
            mime="text/csv"
        )
    
    # Upload to blob storage if available
    if blob_service_client and result_upload_container:
        st.subheader("Upload Updated Files to Blob Storage")
        
        if st.button("Upload All Edited Files", type="primary"):
            with st.spinner("Uploading edited files to blob storage..."):
                upload_results = []
                
                for pdf_result in st.session_state.edited_results:
                    filename = pdf_result["filename"]
                    base_filename = os.path.splitext(filename)[0]
                    
                    # Create the text content with key-value pairs
                    page_results_text = create_page_results_text(pdf_result)
                    
                    # Create timestamp filename with _edited suffix
                    timestamp_filename = f"{base_filename}_{timestamp}_edited"
                    
                    # Upload text file to blob storage
                    text_blob_name = f"{timestamp_filename}.txt"
                    text_success, text_url = upload_to_blob_storage(
                        blob_service_client,
                        result_upload_container,
                        text_blob_name,
                        page_results_text,
                        "text/plain"
                    )
                    
                    # Upload CSV to blob storage (only once for all files)
                    if filename == st.session_state.edited_results[0]["filename"]:
                        csv_blob_name = f"financial_data_extraction_{timestamp}_edited.csv"
                        csv_data = results_df.to_csv(index=False)
                        csv_success, csv_url = upload_to_blob_storage(
                            blob_service_client,
                            result_upload_container,
                            csv_blob_name,
                            csv_data,
                            "text/csv"
                        )
                    
                    # Store results
                    upload_results.append({
                        "filename": filename,
                        "text_success": text_success,
                        "text_url": text_url if text_success else None
                    })
                
                # Display upload results
                upload_rows = []
                for result in upload_results:
                    upload_rows.append({
                        "Filename": result["filename"],
                        "Updated Text File": "✅ Uploaded" if result["text_success"] else "❌ Failed"
                    })
                
                if upload_rows:
                    st.write("### Upload Results")
                    upload_df = pd.DataFrame(upload_rows)
                    st.dataframe(upload_df)
                    
                st.success("All edited files have been uploaded to blob storage.")
    
    # Option to clear memory and restart flow
    st.subheader("Reset Application")
    if st.button("Restart Process (Clear Memory)", type="secondary"):
        # Clear session state to restart flow
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.experimental_rerun()
