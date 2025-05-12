import streamlit as st
import pandas as pd
import os
import io
import json
import gc
from datetime import datetime
from helper_functions import (
    load_config, get_blob_service_client, list_blobs_in_folder, 
    download_blob_to_memory, parse_csv_from_blob, get_pdf_preview,
    convert_pdf_to_base64, extract_filename_without_path, 
    update_csv_in_blob, has_high_confidence, create_zip_from_blobs,
    apply_edits_to_csv, get_csv_summary
)

st.set_page_config(
    page_title="PDF Financial Data Extractor",
    page_icon="📊",
    layout="wide"
)

# Initialize session state variables
if 'selected_confidence' not in st.session_state:
    st.session_state.selected_confidence = "High Confidence"
if 'selected_csv' not in st.session_state:
    st.session_state.selected_csv = None
if 'csv_data' not in st.session_state:
    st.session_state.csv_data = None
if 'selected_pdf' not in st.session_state:
    st.session_state.selected_pdf = None
if 'edited_data' not in st.session_state:
    st.session_state.edited_data = {}
if 'download_completed' not in st.session_state:
    st.session_state.download_completed = False

# Load configuration
config = load_config()

if not config:
    st.error("Failed to load configuration from config.json. Please make sure the file exists and is properly formatted.")
    st.stop()

# Extract configuration
azure_storage_connection_string = config.get("azure_storage_connection_string")
container_name = config.get("container_name")
high_confidence_source_folder = config.get("high_confidence_source_folder", "high_confidence/source/")
high_confidence_processed_folder = config.get("high_confidence_processed_folder", "high_confidence/processed/")
low_confidence_source_folder = config.get("low_confidence_source_folder", "low_confidence/source/")
low_confidence_processed_folder = config.get("low_confidence_processed_folder", "low_confidence/processed/")

# Initialize Azure Blob Storage client
blob_service_client = get_blob_service_client(azure_storage_connection_string)

if not blob_service_client:
    st.error("Failed to initialize Azure Blob Storage client. Please check your connection string.")
    st.stop()

def reset_download_state():
    """Reset the download completion state."""
    st.session_state.download_completed = False

def display_pdf_viewer(base64_pdf, height=500):
    """
    Display a PDF viewer in the Streamlit app using base64 encoded PDF.
    """
    if not base64_pdf:
        st.error("No PDF data available to display")
        return
        
    # Create the HTML with PDF.js for better viewing
    pdf_display = f"""
    <iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="{height}" 
    type="application/pdf"></iframe>
    """
    
    # Display the PDF
    st.markdown(pdf_display, unsafe_allow_html=True)

# Title and header
st.title("PDF Financial Data Extractor")
st.header("View and Edit Extraction Results")

# Sidebar for navigation
st.sidebar.title("Navigation")

# Radio button for confidence level selection
st.sidebar.header("Filter by Confidence")
selected_confidence = st.sidebar.radio(
    "Select confidence level:",
    ["High Confidence", "Low Confidence"],
    key="confidence_radio"
)

st.session_state.selected_confidence = selected_confidence

# Get folders based on selection
if selected_confidence == "High Confidence":
    source_folder = high_confidence_source_folder
    processed_folder = high_confidence_processed_folder
else:
    source_folder = low_confidence_source_folder
    processed_folder = low_confidence_processed_folder

# List files in the folders
source_blobs = list_blobs_in_folder(blob_service_client, container_name, source_folder)
processed_blobs = list_blobs_in_folder(blob_service_client, container_name, processed_folder)

# Extract filenames without paths
source_filenames = [extract_filename_without_path(blob) for blob in source_blobs]
processed_filenames = [extract_filename_without_path(blob) for blob in processed_blobs]

# Create a mapping of processed filenames to their full blob paths
processed_mapping = {extract_filename_without_path(blob): blob for blob in processed_blobs}

# Create tabs for different views
tabs = st.tabs(["Results View", "Evaluation", "Manual Edit", "Bulk Upload/Download"])

# Results View Tab
with tabs[0]:
    st.subheader(f"{selected_confidence} Results")
    
    # Filter for CSV files in the processed folder
    csv_blobs = [blob for blob in processed_blobs if blob.lower().endswith('.csv')]
    
    if not csv_blobs:
        st.warning(f"No CSV files found in the {selected_confidence} folder.")
    else:
        # Create a dataframe with the filenames
        blob_df = pd.DataFrame({
            'Filename': [extract_filename_without_path(blob) for blob in csv_blobs],
            'Full Path': csv_blobs
        })
        
        # Display the CSV files
        st.write(f"Found {len(csv_blobs)} CSV result files:")
        st.dataframe(blob_df[['Filename']], use_container_width=True)
        
        # Select a CSV to view
        selected_csv_filename = st.selectbox(
            "Select a CSV file to view:",
            options=blob_df['Filename'].tolist(),
            key="csv_select"
        )
        
        if selected_csv_filename:
            # Get the full blob path
            selected_csv_path = blob_df[blob_df['Filename'] == selected_csv_filename]['Full Path'].iloc[0]
            st.session_state.selected_csv = selected_csv_path
            
            # Parse the CSV file
            csv_data = parse_csv_from_blob(blob_service_client, container_name, selected_csv_path)
            st.session_state.csv_data = csv_data
            
            if csv_data is not None:
                # Show the CSV data
                st.write(f"Data from {selected_csv_filename}:")
                st.dataframe(csv_data, use_container_width=True)
                
                # Try to find corresponding PDF in source folder
                pdf_filename = selected_csv_filename.replace('.csv', '.pdf')
                pdf_blob_path = None
                
                for source_blob in source_blobs:
                    if extract_filename_without_path(source_blob) == pdf_filename:
                        pdf_blob_path = source_blob
                        break
                
                if pdf_blob_path:
                    st.session_state.selected_pdf = pdf_blob_path
                    
                    # Add a button to show the PDF preview
                    if st.button("Show PDF Preview"):
                        with st.spinner(f"Loading PDF preview for {pdf_filename}..."):
                            base64_pdf = convert_pdf_to_base64(blob_service_client, container_name, pdf_blob_path)
                            
                            if base64_pdf:
                                st.write(f"### Preview of {pdf_filename}")
                                display_pdf_viewer(base64_pdf)
                            else:
                                st.error(f"Could not load PDF preview for {pdf_filename}")
                else:
                    st.warning(f"Could not find corresponding PDF file for {selected_csv_filename}")
            else:
                st.error(f"Could not parse CSV file {selected_csv_filename}")

# Evaluation Tab
with tabs[1]:
    st.subheader("Extraction Quality Evaluation")
    
    # Select a CSV to evaluate
    if 'csv_data' in st.session_state and st.session_state.csv_data is not None:
        csv_data = st.session_state.csv_data
        
        # Get summary statistics
        summary = get_csv_summary(csv_data)
        
        if summary:
            # Display basic info
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Rows", summary['num_rows'])
            with col2:
                st.metric("Manually Edited Rows", summary['edited_rows'])
            with col3:
                confidence_level = "High Confidence" if has_high_confidence(csv_data, 95.0) else "Low Confidence"
                st.metric("Confidence Level", confidence_level)
            
            # Display confidence statistics
            st.subheader("Field Confidence Statistics")
            
            # Create a DataFrame for confidence stats
            conf_stats = []
            for field, stats in summary['confidence_stats'].items():
                conf_stats.append({
                    'Field': field,
                    'Average Confidence': f"{stats['avg']:.2f}%",
                    'Minimum Confidence': f"{stats['min']:.2f}%",
                    'Maximum Confidence': f"{stats['max']:.2f}%"
                })
            
            conf_stats_df = pd.DataFrame(conf_stats)
            st.dataframe(conf_stats_df, use_container_width=True)
            
            # Create a bar chart of average confidences
            st.subheader("Average Confidence by Field")
            chart_data = pd.DataFrame({
                'Field': [field for field in summary['confidence_stats'].keys()],
                'Confidence': [stats['avg'] for stats in summary['confidence_stats'].values()]
            })
            st.bar_chart(chart_data, x='Field', y='Confidence')
        else:
            st.warning("Could not generate evaluation for the selected CSV file.")
    else:
        st.info("Please select a CSV file in the Results View tab first.")

# Manual Edit Tab
with tabs[2]:
    st.subheader("Manual Editing")
    
    if 'csv_data' in st.session_state and st.session_state.csv_data is not None:
        csv_data = st.session_state.csv_data
        
        # Select a row to edit
        if not csv_data.empty:
            row_indices = csv_data.index.tolist()
            selected_row = st.selectbox("Select a row to edit:", row_indices)
            
            if selected_row is not None:
                # Get the row data
                row_data = csv_data.loc[selected_row]
                
                # Create a form for editing
                with st.form(key=f"edit_form_{selected_row}"):
                    st.write(f"### Editing Row {selected_row}")
                    
                    # Create input fields for each column that's not a confidence column
                    edited_values = {}
                    for column in csv_data.columns:
                        if "Confidence" not in column and column != "Manual_Edit":
                            # Get current value
                            current_value = row_data[column]
                            
                            # Check if there's a confidence column
                            confidence = None
                            confidence_col = f"{column} Confidence"
                            if confidence_col in csv_data.columns:
                                confidence = row_data[confidence_col]
                            
                            # Display the field with confidence if available
                            if confidence is not None:
                                col1, col2 = st.columns([3, 1])
                                with col1:
                                    # Add visual indicator for low confidence
                                    field_label = column
                                    if confidence < 90:
                                        field_label = f"{column} ⚠️"
                                    
                                    # Text input for the field
                                    new_value = st.text_input(
                                        field_label,
                                        value=str(current_value) if pd.notna(current_value) else "",
                                        key=f"field_{selected_row}_{column}"
                                    )
                                with col2:
                                    confidence_color = "green" if confidence >= 90 else "red"
                                    st.markdown(f"<p style='color:{confidence_color};'>Confidence: {confidence:.1f}%</p>", unsafe_allow_html=True)
                            else:
                                # Simple text input without confidence
                                new_value = st.text_input(
                                    column,
                                    value=str(current_value) if pd.notna(current_value) else "",
                                    key=f"field_{selected_row}_{column}"
                                )
                            
                            # Store edited value if changed
                            if new_value != str(current_value):
                                edited_values[column] = new_value
                    
                    # Submit button
                    submit_button = st.form_submit_button("Save Changes")
                    
                    if submit_button:
                        # Store edits in session state
                        if selected_row not in st.session_state.edited_data:
                            st.session_state.edited_data[selected_row] = {}
                        
                        for column, value in edited_values.items():
                            st.session_state.edited_data[selected_row][column] = value
                        
                        st.success(f"Changes saved for row {selected_row}")
                
                # Show a summary of edits
                if selected_row in st.session_state.edited_data:
                    st.write("### Pending Changes")
                    for column, value in st.session_state.edited_data[selected_row].items():
                        st.write(f"**{column}**: '{row_data[column]}' → '{value}'")
            
            # Apply edits button
            if st.session_state.edited_data and st.button("Apply All Edits"):
                with st.spinner("Applying edits..."):
                    # Apply edits to the DataFrame
                    updated_df = apply_edits_to_csv(csv_data, st.session_state.edited_data)
                    
                    # Update the CSV in blob storage
                    if st.session_state.selected_csv:
                        success = update_csv_in_blob(blob_service_client, container_name, st.session_state.selected_csv, updated_df)
                        
                        if success:
                            st.success("Edits successfully applied and saved to blob storage")
                            
                            # Update the session state
                            st.session_state.csv_data = updated_df
                            st.session_state.edited_data = {}
                            
                            # Refresh the page
                            st.experimental_rerun()
                        else:
                            st.error("Failed to save edits to blob storage")
        else:
            st.warning("The selected CSV file is empty.")
    else:
        st.info("Please select a CSV file in the Results View tab first.")

# Bulk Upload/Download Tab
with tabs[3]:
    st.subheader("Bulk Upload and Download")
    
    # Bulk Download section
    st.write("### Bulk Download")
    download_type = st.radio(
        "Select download type:",
        ["CSV Results", "Source PDFs", "Both Results and PDFs"]
    )
    
    if st.button("Prepare Download"):
        with st.spinner("Preparing files for download..."):
            blobs_to_download = []
            
            if download_type in ["CSV Results", "Both Results and PDFs"]:
                blobs_to_download.extend(processed_blobs)
            
            if download_type in ["Source PDFs", "Both Results and PDFs"]:
                blobs_to_download.extend(source_blobs)
            
            if blobs_to_download:
                # Create a ZIP file
                zip_buffer = create_zip_from_blobs(blob_service_client, container_name, blobs_to_download)
                
                if zip_buffer:
                    # Store in session state
                    st.session_state.download_zip = zip_buffer
                    st.session_state.download_completed = True
                    st.success(f"Ready to download {len(blobs_to_download)} files")
                else:
                    st.error("Failed to prepare files for download")
            else:
                st.warning("No files to download")
    
    # Show download button when data is ready
    if 'download_zip' in st.session_state and st.session_state.download_completed:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        confidence_label = "high" if selected_confidence == "High Confidence" else "low"
        
        st.download_button(
            label="Download ZIP File",
            data=st.session_state.download_zip,
            file_name=f"{confidence_label}_confidence_files_{timestamp}.zip",
            mime="application/zip",
            on_click=reset_download_state
        )
    
    # Add a clear button to remove download data and free memory
    if 'download_zip' in st.session_state and st.button("Clear Download Data", type="secondary"):
        if 'download_zip' in st.session_state:
            del st.session_state.download_zip
        st.session_state.download_completed = False
        gc.collect()
        st.success("Download data cleared from memory")

# Sidebar cleanup button
if st.sidebar.button("Clear Memory", type="secondary"):
    # Clear all session state variables
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    
    # Force garbage collection
    gc.collect()
    
    # Show success message
    st.sidebar.success("Memory cleared successfully!")
    
    # Rerun the app
    st.experimental_rerun()
