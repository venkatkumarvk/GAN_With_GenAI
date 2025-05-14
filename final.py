# Match source and processed files
def match_source_and_processed_files(source_blobs, processed_blobs):
    """Match source PDFs with their processed CSV results."""
    source_filenames = {get_filename_from_blob_path(blob.name).split('.')[0]: blob for blob in source_blobs}
    processed_filenames = {get_filename_from_blob_path(blob.name).split('.')[0]: blob for blob in processed_blobs}

    matched_files = []
    for base_name in set(source_filenames.keys()) & set(processed_filenames.keys()):
        source_blob = source_filenames[base_name]
        processed_blob = processed_filenames[base_name]
        
        # Extract creation time from blob properties
        source_time = source_blob.creation_time if hasattr(source_blob, 'creation_time') else None
        processed_time = processed_blob.creation_time if hasattr(processed_blob, 'creation_time') else None
        
        # Format date and time if available
        date_str = source_time.strftime("%Y-%m-%d") if source_time else "Unknown"
        time_str = source_time.strftime("%H:%M:%S") if source_time else "Unknown"
        
        # Get month and year for filtering
        month = source_time.month if source_time else None
        year = source_time.year if source_time else None
        
        matched_files.append({
            "base_name": base_name,
            "source_blob": source_blob.name,
            "processed_blob": processed_blob.name,
            "date": date_str,
            "time": time_str,
            "month": month,
            "year": year
        })

    return matched_files


----
# Add to the sidebar, right after confidence selection
st.sidebar.markdown("---")
st.sidebar.subheader("Filter by Date")

# Get unique years and months from matched files
years = sorted(list(set(f["year"] for f in matched_files if f["year"] is not None)), reverse=True)
months = list(range(1, 13))  # 1-12 for months

# Default to all if no years available
if not years:
    years = [datetime.now().year]
    
# Set defaults if not in session state
if 'selected_year' not in st.session_state:
    st.session_state.selected_year = years[0] if years else datetime.now().year
if 'selected_month' not in st.session_state:
    st.session_state.selected_month = 0  # 0 means "All months"

# Year selector
selected_year = st.sidebar.selectbox(
    "Select Year",
    [0] + years,  # 0 means "All years"
    format_func=lambda x: "All Years" if x == 0 else str(x),
    index=[0] + years.index(st.session_state.selected_year) + 1 if st.session_state.selected_year in years else 0
)

# Month selector
month_names = ["All Months", "January", "February", "March", "April", "May", "June", 
               "July", "August", "September", "October", "November", "December"]
selected_month = st.sidebar.selectbox(
    "Select Month",
    list(range(13)),  # 0-12, where 0 means "All months"
    format_func=lambda x: month_names[x],
    index=st.session_state.selected_month
)

# Update session state
st.session_state.selected_year = selected_year
st.session_state.selected_month = selected_month

# Filter matched files based on selection
filtered_matched_files = matched_files
if selected_year != 0:  # If not "All Years"
    filtered_matched_files = [f for f in filtered_matched_files if f["year"] == selected_year]
if selected_month != 0:  # If not "All Months"
    filtered_matched_files = [f for f in filtered_matched_files if f["month"] == selected_month]

# Show how many files match the filter
if len(filtered_matched_files) != len(matched_files):
    st.sidebar.info(f"Showing {len(filtered_matched_files)} of {len(matched_files)} files")
else:
    st.sidebar.info(f"Showing all {len(matched_files)} files")

# Reset selected file index if our filters changed the available files
if 'filtered_files_count' not in st.session_state or st.session_state.filtered_files_count != len(filtered_matched_files):
    st.session_state.selected_file_idx = 0
    st.session_state.filtered_files_count = len(filtered_matched_files)

----
# Replace the existing file selector with this
if not filtered_matched_files:
    st.sidebar.warning("No files match the selected filters.")
else:
    # File selector dropdown in sidebar
    selected_file_idx = st.sidebar.selectbox(
        "Select a file",
        range(len(filtered_matched_files)),
        format_func=lambda x: f"{filtered_matched_files[x]['base_name']} ({filtered_matched_files[x]['date']})",
        index=min(st.session_state.selected_file_idx, len(filtered_matched_files)-1)
    )

    # Update the selected file in session state
    if selected_file_idx != st.session_state.selected_file_idx:
        st.session_state.selected_file_idx = selected_file_idx
        st.session_state.pdf_content = None  # Reset PDF content when changing files
        st.session_state.csv_df = None
        st.session_state.manual_edit_fields = []

    # Load PDF and CSV for selected file
    if st.session_state.pdf_content is None:
        source_blob = filtered_matched_files[selected_file_idx]["source_blob"]
        st.session_state.pdf_content = download_blob_to_memory(blob_service_client, container_name, source_blob)

    if st.session_state.csv_df is None:
        processed_blob = filtered_matched_files[selected_file_idx]["processed_blob"]
        st.session_state.csv_df = load_csv_from_blob(blob_service_client, container_name, processed_blob)
        
        # Rest of your existing code...


----
# Find the code where you create matched_df and replace with:
if filtered_matched_files:
    # Display matched files in a table with date and time
    matched_df = pd.DataFrame(filtered_matched_files)
    st.write(f"Found {len(filtered_matched_files)} matched files")
    st.dataframe(matched_df[["base_name", "date", "time", "source_blob", "processed_blob"]], use_container_width=True)
    
    # Use already selected file from sidebar
    selected_file = filtered_matched_files[st.session_state.selected_file_idx]
    st.write(f"Selected file: {selected_file['base_name']} (Date: {selected_file['date']})")
    
    # Rest of the code...

----
# Instead of
selected_file = matched_files[st.session_state.selected_file_idx]

# Use
selected_file = filtered_matched_files[st.session_state.selected_file_idx]
