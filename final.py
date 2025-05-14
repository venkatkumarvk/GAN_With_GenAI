# Match source and processed files with date information
def match_source_and_processed_files(source_blobs, processed_blobs):
    """Match source PDFs with their processed CSV results and add date information."""
    source_filenames = {get_filename_from_blob_path(blob.name).split('.')[0]: blob for blob in source_blobs}
    processed_filenames = {get_filename_from_blob_path(blob.name).split('.')[0]: blob for blob in processed_blobs}

    matched_files = []
    for base_name in set(source_filenames.keys()) & set(processed_filenames.keys()):
        source_blob = source_filenames[base_name]
        processed_blob = processed_filenames[base_name]
        
        # Extract the date and time info from blob properties
        source_last_modified = source_blob.last_modified if hasattr(source_blob, 'last_modified') else None
        processed_last_modified = processed_blob.last_modified if hasattr(processed_blob, 'last_modified') else None
        
        # Format the date and time for display
        source_date = source_last_modified.strftime("%Y-%m-%d") if source_last_modified else "Unknown"
        source_time = source_last_modified.strftime("%H:%M:%S") if source_last_modified else "Unknown"
        processed_date = processed_last_modified.strftime("%Y-%m-%d") if processed_last_modified else "Unknown"
        processed_time = processed_last_modified.strftime("%H:%M:%S") if processed_last_modified else "Unknown"
        
        # Get the year and month for filtering
        year = source_last_modified.year if source_last_modified else 0
        month = source_last_modified.month if source_last_modified else 0
        
        matched_files.append({
            "base_name": base_name,
            "source_blob": source_blob.name,
            "processed_blob": processed_blob.name,
            "source_date": source_date,
            "source_time": source_time,
            "processed_date": processed_date,
            "processed_time": processed_time,
            "year": year,
            "month": month
        })

    return matched_files

----
# Month and Year filtering
st.sidebar.markdown("---")
st.sidebar.subheader("Date Filtering")

# Year selection (2020 onwards)
current_year = datetime.now().year
years = list(range(2020, current_year + 1))
selected_year = st.sidebar.selectbox(
    "Select Year",
    years,
    index=len(years) - 1,  # Default to current year
    key="year_filter"
)

# Month selection (1-12)
months = [
    (1, "January"), (2, "February"), (3, "March"), 
    (4, "April"), (5, "May"), (6, "June"),
    (7, "July"), (8, "August"), (9, "September"),
    (10, "October"), (11, "November"), (12, "December")
]
current_month = datetime.now().month
selected_month = st.sidebar.selectbox(
    "Select Month",
    [m[0] for m in months],
    format_func=lambda x: dict(months)[x],
    index=current_month - 1,  # Default to current month
    key="month_filter"
)

# Option to disable filtering
apply_date_filter = st.sidebar.checkbox("Apply Date Filter", value=False)

---
# Match source PDFs with their processed CSV results
matched_files = match_source_and_processed_files(source_blobs, processed_blobs)

# Apply date filter if selected
if apply_date_filter and matched_files:
    filtered_matched_files = [
        f for f in matched_files 
        if f.get("year") == selected_year and f.get("month") == selected_month
    ]
    
    # Show filter info
    if filtered_matched_files:
        st.sidebar.success(f"Found {len(filtered_matched_files)} files for {dict(months)[selected_month]} {selected_year}")
    else:
        st.sidebar.warning(f"No files found for {dict(months)[selected_month]} {selected_year}")
        # Show some stats on what years/months are available
        available_years = sorted(set(f.get("year") for f in matched_files if f.get("year")))
        st.sidebar.info(f"Available years: {', '.join(map(str, available_years))}")
    
    matched_files = filtered_matched_files

---
# Display matched files in a table with date info
if not matched_files:
    st.warning("No matched source and processed files found.")
else:
    # Create a display dataframe with nicely formatted columns
    display_cols = ["base_name", "source_date", "source_time", "processed_date", "processed_time"]
    display_col_names = {
        "base_name": "Filename",
        "source_date": "Source Date",
        "source_time": "Source Time",
        "processed_date": "Processed Date", 
        "processed_time": "Processed Time"
    }
    
    # If few enough files, show them all
    if len(matched_files) <= 20:
        matched_df = pd.DataFrame(matched_files)[display_cols]
        matched_df = matched_df.rename(columns=display_col_names)
        st.write(f"Found {len(matched_files)} matched files")
        st.dataframe(matched_df, use_container_width=True)
    else:
        # If too many files, show pagination
        items_per_page = 20
        total_pages = (len(matched_files) + items_per_page - 1) // items_per_page
        
        # Add pagination controls
        col1, col2, col3 = st.columns([1, 3, 1])
        with col1:
            if "page_number" not in st.session_state:
                st.session_state.page_number = 0
                
            if st.button("Previous Page", disabled=st.session_state.page_number <= 0):
                st.session_state.page_number -= 1
                
        with col2:
            st.write(f"Page {st.session_state.page_number + 1} of {total_pages}")
            
        with col3:
            if st.button("Next Page", disabled=st.session_state.page_number >= total_pages - 1):
                st.session_state.page_number += 1
        
        # Get the subset of files for this page
        start_idx = st.session_state.page_number * items_per_page
        end_idx = min(start_idx + items_per_page, len(matched_files))
        page_files = matched_files[start_idx:end_idx]
        
        # Show the files for this page
        matched_df = pd.DataFrame(page_files)[display_cols]
        matched_df = matched_df.rename(columns=display_col_names)
        st.write(f"Showing {len(page_files)} of {len(matched_files)} matched files")
        st.dataframe(matched_df, use_container_width=True)

--
# PDF Selector in Sidebar - adjust for empty results
st.sidebar.markdown("---")
st.sidebar.subheader("File Selection")

if not matched_files:
    st.sidebar.warning("No matched files found.")
    if apply_date_filter:
        st.sidebar.info("Try adjusting the date filter")
else:
    # Reset selected file index if it's out of range
    if st.session_state.selected_file_idx >= len(matched_files):
        st.session_state.selected_file_idx = 0
        
    # File selector dropdown in sidebar
    selected_file_idx = st.sidebar.selectbox(
        "Select a file",
        range(len(matched_files)),
        format_func=lambda x: f"{matched_files[x]['base_name']} ({matched_files[x]['source_date']})",
        index=st.session_state.selected_file_idx
    )
