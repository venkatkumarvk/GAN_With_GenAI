def add_manual_verification_section(all_pdf_results, timestamp, blob_service_client=None, result_upload_container=None):
    """
    Drastically simplified manual verification approach using text areas and a single save button.
    """
    st.subheader("4. Manual Verification and Editing")
    
    # Initialize session state for edited data if it doesn't exist
    if 'edited_data_initialized' not in st.session_state:
        st.session_state.edited_data = {}
        # Pre-fill with original values
        for pdf_idx, pdf_result in enumerate(all_pdf_results):
            filename = pdf_result["filename"]
            for page_idx, page in enumerate(pdf_result["pages"]):
                page_num = page["page"]
                data = page["data"]
                
                if "error" in data:
                    continue
                    
                # Define the fields we're extracting
                fields = [
                    "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
                    "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
                    "Freight", "Salestax", "Total"
                ]
                
                for field in fields:
                    field_data = data.get(field, {})
                    
                    if isinstance(field_data, dict):
                        current_value = field_data.get("value", "")
                    else:
                        current_value = field_data if field_data else ""
                    
                    key = f"{filename}_{page_num}_{field}"
                    st.session_state.edited_data[key] = current_value
        
        st.session_state.edited_data_initialized = True
    
    # Function to apply all edits and create updated files
    def apply_all_edits():
        # Create a deep copy of the original results
        import copy
        edited_results = copy.deepcopy(all_pdf_results)
        
        # Apply edits from session state
        for pdf_idx, pdf_result in enumerate(edited_results):
            filename = pdf_result["filename"]
            for page_idx, page in enumerate(pdf_result["pages"]):
                page_num = page["page"]
                data = page["data"]
                
                if "error" in data:
                    continue
                
                # Define the fields we're extracting
                fields = [
                    "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
                    "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
                    "Freight", "Salestax", "Total"
                ]
                
                for field in fields:
                    key = f"{filename}_{page_num}_{field}"
                    if key in st.session_state.edited_data:
                        # Get original confidence value
                        field_data = data.get(field, {})
                        original_confidence = 0
                        
                        if isinstance(field_data, dict) and "confidence" in field_data:
                            original_confidence = field_data.get("confidence", 0)
                        
                        # Update with edited value but keep original confidence
                        edited_results[pdf_idx]["pages"][page_idx]["data"][field] = {
                            "value": st.session_state.edited_data[key],
                            "confidence": original_confidence,
                            "manually_edited": True
                        }
        
        return edited_results
    
    # Display large warning box for instructions
    st.warning("""
    **Manual Verification Instructions:**
    1. Edit any field values as needed below
    2. Click 'Save All Changes & Generate Files' when done
    3. Download the updated files from the section that appears after saving
    """)
    
    # Display tabbed interface for each PDF
    if len(all_pdf_results) > 0:
        pdf_tabs = st.tabs([pdf_result["filename"] for pdf_result in all_pdf_results])
        
        for i, tab in enumerate(pdf_tabs):
            with tab:
                pdf_result = all_pdf_results[i]
                filename = pdf_result["filename"]
                
                # Create expandable sections for each page
                for page_idx, page in enumerate(pdf_result["pages"]):
                    page_num = page["page"]
                    data = page["data"]
                    
                    if "error" in data:
                        continue
                    
                    with st.expander(f"Page {page_num}", expanded=False):
                        # Display each field as a text input
                        fields = [
                            "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
                            "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
                            "Freight", "Salestax", "Total"
                        ]
                        
                        # Use two columns for layout
                        cols = st.columns(2)
                        
                        for field_idx, field in enumerate(fields):
                            # Format field name for display
                            field_display = ' '.join(field.replace('_', ' ').title().split())
                            
                            # Get confidence for display
                            field_data = data.get(field, {})
                            confidence_text = ""
                            if isinstance(field_data, dict) and "confidence" in field_data:
                                confidence = field_data.get("confidence", 0)
                                confidence_text = f" (Confidence: {round(confidence * 100, 2)}%)"
                            
                            # Decide which column to use
                            col_idx = 0 if field_idx < len(fields)//2 + len(fields)%2 else 1
                            
                            # Create key for this field
                            key = f"{filename}_{page_num}_{field}"
                            
                            # Add text input in appropriate column
                            with cols[col_idx]:
                                st.text_input(
                                    f"{field_display}{confidence_text}",
                                    key=key,
                                    on_change=lambda k=key, v=st.session_state[key]: 
                                        setattr(st.session_state, 'edited_data', 
                                                {**st.session_state.edited_data, k: v})
                                )
    
    # Single button to save all changes and generate files
    if st.button("Save All Changes & Generate Files", type="primary", key="save_all_button"):
        with st.spinner("Applying edits and generating files..."):
            # Apply all edits and get updated results
            edited_results = apply_all_edits()
            
            # Store in session state for access later
            st.session_state.final_edited_results = edited_results
            
            # Set flag to show files section
            st.session_state.show_files_section = True
            
            st.success("All changes have been applied! Scroll down to download updated files.")
            st.experimental_rerun()  # Rerun to show files section
    
    # Check if we should show files section
    if 'show_files_section' in st.session_state and st.session_state.show_files_section:
        st.subheader("Updated Files")
        
        # Create files from edited results
        edited_results = st.session_state.final_edited_results
        
        # Create updated text files
        text_zip = create_text_files_zip(edited_results)
        
        # Create updated CSV
        results_df = create_results_dataframe(edited_results)
        
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
                    
                    for pdf_result in edited_results:
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
                        if filename == edited_results[0]["filename"]:
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
                        upload_df = pd.DataFrame(upload_results)
                        st.dataframe(upload_df)
                    
                    st.success("All files have been uploaded to blob storage!")
    
    # Reset button at the bottom
    if st.button("Restart Process (Clear Memory)", type="secondary"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.experimental_rerun()
