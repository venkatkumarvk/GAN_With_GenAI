def add_manual_verification_section(all_pdf_results, timestamp, blob_service_client=None, result_upload_container=None):
    """
    Robust manual verification that avoids session state key errors.
    Uses a simple text area approach for editing fields.
    """
    st.subheader("4. Manual Verification and Editing")
    
    # Initialize edited_results in session state if not already present
    if 'edited_results' not in st.session_state:
        # Deep copy to prevent modifying the original
        import copy
        st.session_state.edited_results = copy.deepcopy(all_pdf_results)
    
    # Function to apply edits to session state
    def update_field(pdf_idx, page_idx, field, value):
        try:
            # Get original confidence value
            original_data = all_pdf_results[pdf_idx]["pages"][page_idx]["data"].get(field, {})
            original_confidence = 0
            
            if isinstance(original_data, dict) and "confidence" in original_data:
                original_confidence = original_data.get("confidence", 0)
            
            # Update with edited value but keep original confidence
            st.session_state.edited_results[pdf_idx]["pages"][page_idx]["data"][field] = {
                "value": value,
                "confidence": original_confidence,
                "manually_edited": True
            }
        except Exception as e:
            st.error(f"Error updating field: {e}")
    
    # Flag to track if we need to generate files
    generate_files = st.button("Generate Updated Files", type="primary")
    
    # Create tabs for each PDF
    if len(all_pdf_results) > 0:
        pdf_tabs = st.tabs([pdf_result["filename"] for pdf_result in all_pdf_results])
        
        for pdf_idx, tab in enumerate(pdf_tabs):
            with tab:
                pdf_result = all_pdf_results[pdf_idx]
                filename = pdf_result["filename"]
                
                # Display each page in an expander
                for page_idx, page in enumerate(pdf_result["pages"]):
                    page_num = page["page"]
                    data = page["data"]
                    
                    with st.expander(f"Page {page_num}", expanded=False):
                        if "error" in data:
                            st.error(f"Error processing this page: {data['error']}")
                            continue
                        
                        # Define fields
                        fields = [
                            "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
                            "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
                            "Freight", "Salestax", "Total"
                        ]
                        
                        # Use columns for layout
                        cols = st.columns(2)
                        
                        # Get current values from the session state edited_results
                        for field_idx, field in enumerate(fields):
                            col_idx = 0 if field_idx < (len(fields) // 2 + len(fields) % 2) else 1
                            
                            with cols[col_idx]:
                                # Format display name
                                field_display = ' '.join(field.replace('_', ' ').title().split())
                                
                                # Get current value
                                edited_data = st.session_state.edited_results[pdf_idx]["pages"][page_idx]["data"]
                                field_data = edited_data.get(field, {})
                                
                                if isinstance(field_data, dict):
                                    current_value = field_data.get("value", "")
                                    confidence = field_data.get("confidence", 0)
                                    confidence_text = f" (Confidence: {round(confidence * 100, 2)}%)"
                                else:
                                    current_value = field_data if field_data else ""
                                    confidence_text = ""
                                
                                # Generate a unique key for this field
                                field_key = f"{filename}_{page_num}_{field}_{pdf_idx}_{page_idx}"
                                
                                # Create text input
                                new_value = st.text_input(
                                    f"{field_display}{confidence_text}",
                                    value=current_value,
                                    key=field_key
                                )
                                
                                # Update if value changed
                                if new_value != current_value:
                                    update_field(pdf_idx, page_idx, field, new_value)
    
    # Generate files section
    if generate_files:
        st.subheader("Updated Files")
        
        with st.spinner("Generating updated files..."):
            # Create updated text files
            text_zip = create_text_files_zip(st.session_state.edited_results)
            
            # Create updated CSV
            results_df = create_results_dataframe(st.session_state.edited_results)
            
            # Display download buttons
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
                st.subheader("Upload to Blob Storage")
                
                if st.button("Upload Updated Files to Blob Storage"):
                    with st.spinner("Uploading files to blob storage..."):
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
                            
                            # Only upload CSV once for all files
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
                        if upload_results:
                            st.write("### Upload Results")
                            upload_df = pd.DataFrame(upload_rows)
                            st.dataframe(upload_df)
                        
                        st.success("All files have been uploaded to blob storage!")
    
    # Reset button at the bottom
    if st.button("Restart Process (Clear Memory)", type="secondary"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.experimental_rerun()
