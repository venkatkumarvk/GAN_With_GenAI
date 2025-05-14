# Match source and processed files
def match_source_and_processed_files(source_blobs, processed_blobs):
    """Match source PDFs with their processed CSV results."""
    source_filenames = {get_filename_from_blob_path(blob.name).split('.')[0]: blob for blob in source_blobs}
    processed_filenames = {get_filename_from_blob_path(blob.name).split('.')[0]: blob for blob in processed_blobs}

    matched_files = []
    for base_name in set(source_filenames.keys()) & set(processed_filenames.keys()):
        source_blob = source_filenames[base_name]
        processed_blob = processed_filenames[base_name]
        
        # Extract creation time from blobs
        source_creation_time = source_blob.creation_time if hasattr(source_blob, 'creation_time') else None
        processed_creation_time = processed_blob.creation_time if hasattr(processed_blob, 'creation_time') else None
        
        # Format date and time
        source_date = source_creation_time.strftime("%Y-%m-%d") if source_creation_time else "Unknown"
        source_time = source_creation_time.strftime("%H:%M:%S") if source_creation_time else "Unknown"
        
        # Get year and month for filtering
        year = source_creation_time.year if source_creation_time else None
        month = source_creation_time.month if source_creation_time else None
        
        matched_files.append({
            "base_name": base_name,
            "source_blob": source_blob.name,
            "processed_blob": processed_blob.name,
            "creation_date": source_date,
            "creation_time": source_time,
            "year": year,
            "month": month
        })

    return matched_files


---
# PDF Selector in Sidebar
st.sidebar.markdown("---")
st.sidebar.subheader("File Selection")

if not matched_files:
    st.sidebar.warning("No matched files found.")
else:
    # Add date filters
    # Get unique years and months from the data
    years = sorted(list(set([f["year"] for f in matched_files if f["year"] is not None])), reverse=True)
    
    # Add "All" option
    filter_years = ["All"] + years
    
    # Year filter
    selected_year = st.sidebar.selectbox(
        "Filter by Year:", 
        filter_years,
        index=0
    )
    
    # Month filter (only show if year is selected)
    if selected_year != "All":
        # Get months for selected year
        months_in_year = sorted(list(set([f["month"] for f in matched_files 
                                 if f["year"] == selected_year and f["month"] is not None])))
        filter_months = ["All"] + months_in_year
        
        selected_month = st.sidebar.selectbox(
            "Filter by Month:", 
            filter_months,
            index=0
        )
    else:
        selected_month = "All"
    
    # Apply filters
    filtered_files = matched_files
    if selected_year != "All":
        filtered_files = [f for f in filtered_files if f["year"] == selected_year]
        if selected_month != "All":
            filtered_files = [f for f in filtered_files if f["month"] == selected_month]
    
    if not filtered_files:
        st.sidebar.warning(f"No files found for the selected time period.")
    else:
        # File selector dropdown in sidebar
        file_options = [f"{f['base_name']} ({f['creation_date']})" for f in filtered_files]
        
        # Set default index
        default_index = 0
        if 'selected_file_idx' in st.session_state and st.session_state.selected_file_idx < len(filtered_files):
            default_index = st.session_state.selected_file_idx
        
        selected_file_display = st.sidebar.selectbox(
            "Select a file",
            file_options,
            index=default_index
        )
        
        # Find the index of the selected file in filtered_files
        selected_file_idx = file_options.index(selected_file_display)
        
        # Update the selected file in session state
        if 'selected_file_idx' not in st.session_state or selected_file_idx != st.session_state.selected_file_idx:
            st.session_state.selected_file_idx = selected_file_idx
            st.session_state.pdf_content = None  # Reset PDF content when changing files
            st.session_state.csv_df = None
            st.session_state.manual_edit_fields = []

        # Load PDF and CSV for selected file
        if st.session_state.pdf_content is None:
            source_blob = filtered_files[selected_file_idx]["source_blob"]
            st.session_state.pdf_content = download_blob_to_memory(blob_service_client, container_name, source_blob)

        if st.session_state.csv_df is None:
            processed_blob = filtered_files[selected_file_idx]["processed_blob"]
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
                
                # Get editable fields by excluding all metadata and confidence columns
                st.session_state.manual_edit_fields = [col for col in st.session_state.csv_df.columns 
                                                    if col not in exclude_columns and col not in confidence_cols]

        # Display PDF preview in sidebar
        if st.session_state.pdf_content:
            st.sidebar.markdown("---")
            st.sidebar.subheader("PDF Preview")
            base64_pdf = convert_pdf_to_base64(st.session_state.pdf_content)
            display_pdf_viewer(base64_pdf, height=400)


--

# Tab 1: Results View
with tabs[0]:
    st.header(f"Results - {confidence_selection.replace('_', ' ').title()}")

    if not matched_files:
        st.warning("No matched source and processed files found.")
    else:
        # Ensure we're using the filtered_files
        display_files = filtered_files if 'filtered_files' in locals() else matched_files
        
        # Display matched files in a table with date and time
        display_df = pd.DataFrame([{
            "File Name": f["base_name"],
            "Creation Date": f["creation_date"],
            "Creation Time": f["creation_time"],
            "Source Path": f["source_blob"],
            "Results Path": f["processed_blob"]
        } for f in display_files])
        
        st.write(f"Found {len(display_files)} matched files")
        st.dataframe(display_df, use_container_width=True)

        # Use already selected file from sidebar
        st.write(f"Selected file: {display_files[st.session_state.selected_file_idx]['base_name']} " +
                f"(Created: {display_files[st.session_state.selected_file_idx]['creation_date']})")
