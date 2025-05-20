# PDF Selector in Sidebar
st.sidebar.markdown("---")
st.sidebar.subheader("File Selection")

if not matched_files:
    st.sidebar.warning("No matched files found.")
else:
    # File selector dropdown in sidebar
    def on_file_change():
        # Reset the PDF and CSV data when file changes
        st.session_state.pdf_content = None
        st.session_state.csv_df = None
        st.session_state.manual_edit_fields = []
        # This ensures the new file is loaded immediately
        
    selected_file_idx = st.sidebar.selectbox(
        "Select a file",
        range(len(matched_files)),
        format_func=lambda x: matched_files[x]["base_name"],
        index=st.session_state.selected_file_idx,
        on_change=on_file_change,
        key="file_selector"
    )
    
    # Update the selected file in session state
    st.session_state.selected_file_idx = selected_file_idx
    
    # Force load PDF content after selection
    if st.session_state.pdf_content is None:
        source_blob = matched_files[selected_file_idx]["source_blob"]
        debug_print(f"Loading PDF: {source_blob}")
        st.session_state.pdf_content = download_blob_to_memory(blob_service_client, container_name, source_blob)
        
        # If we successfully loaded the PDF, also load the CSV
        if st.session_state.pdf_content:
            processed_blob = matched_files[selected_file_idx]["processed_blob"]
            debug_print(f"Loading CSV: {processed_blob}")
            st.session_state.csv_df = load_csv_from_blob(blob_service_client, container_name, processed_blob)
            
            # Get fields that can be edited
            if st.session_state.csv_df is not None:
                exclude_columns = ["Page", "Filename", "Extraction_Timestamp", "Manual_Edit", "Edit_Timestamp", 
                                  "Manually_Edited_Fields", "Original_Values", "New_Values"]
                confidence_cols = [col for col in st.session_state.csv_df.columns if col.endswith("Confidence")]
                st.session_state.manual_edit_fields = [col for col in st.session_state.csv_df.columns 
                                                if col not in exclude_columns and col not in confidence_cols]
        
    # Display PDF preview in sidebar
    if st.session_state.pdf_content:
        st.sidebar.markdown("---")
        st.sidebar.subheader("PDF Preview")
        
        # Add a loading indicator
        with st.sidebar.spinner("Loading PDF preview..."):
            base64_pdf = convert_pdf_to_base64(st.session_state.pdf_content)
            if base64_pdf:
                display_pdf_viewer(base64_pdf, height=400)
            else:
                st.sidebar.error("Failed to generate PDF preview")
    else:
        st.sidebar.warning("Could not load PDF preview")


#####
