# app.py
import streamlit as st
import pandas as pd
import os
import io
import time
from datetime import datetime
import gc
from helper_functions import (
    load_config, get_blob_service_client, list_blobs_with_prefix,
    download_blob_content, upload_blob_content, get_matching_pdf_and_csv,
    render_pdf_preview, convert_pdf_to_base64, display_pdf_viewer,
    parse_csv_content, update_csv_with_edits
)

# Set page configuration
st.set_page_config(
    page_title="Invoice Data Viewer",
    page_icon="📊",
    layout="wide"
)

# Initialize session state variables
if 'config' not in st.session_state:
    st.session_state.config = None
if 'blob_service_client' not in st.session_state:
    st.session_state.blob_service_client = None
if 'edited_data' not in st.session_state:
    st.session_state.edited_data = {}
if 'current_csv_data' not in st.session_state:
    st.session_state.current_csv_data = None
if 'current_pdf_content' not in st.session_state:
    st.session_state.current_pdf_content = None

# Title and introduction
st.title("Invoice Data Viewer and Editor")
st.subheader("View, validate, and edit invoice extraction results")

# Load configuration
@st.cache_data(show_spinner=False)
def initialize_app():
    """Initialize the application with configuration."""
    config = load_config()
    if config:
        blob_service_client = get_blob_service_client(config.get("storage_connection_string", ""))
        return config, blob_service_client
    return None, None

# Initialize app
st.session_state.config, st.session_state.blob_service_client = initialize_app()

# Check if initialization was successful
if not st.session_state.config or not st.session_state.blob_service_client:
    st.error("Application initialization failed. Please check your configuration.")
    st.stop()

# Get configuration values
config = st.session_state.config
container_name = config.get("container_name", "")
high_confidence_source = config.get("high_confidence_source", "")
high_confidence_processed = config.get("high_confidence_processed", "")
low_confidence_source = config.get("low_confidence_source", "")
low_confidence_processed = config.get("low_confidence_processed", "")
output_container = config.get("output_container", "")
final_folder = config.get("final_folder", "")

# Main navigation
st.sidebar.title("Navigation")
app_mode = st.sidebar.radio(
    "Choose a mode",
    ["View Results", "Manual Edit", "Bulk Upload"]
)

# Confidence selection
confidence_selection = st.sidebar.radio(
    "Confidence Level",
    ["High Confidence", "Low Confidence"]
)

# Get the appropriate folders based on confidence selection
if confidence_selection == "High Confidence":
    source_folder = high_confidence_source
    processed_folder = high_confidence_processed
else:
    source_folder = low_confidence_source
    processed_folder = low_confidence_processed

# Load the source and processed files
@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_source_and_processed_files(blob_service_client, container_name, source_folder, processed_folder):
    """Load source PDFs and processed CSVs."""
    source_blobs = list_blobs_with_prefix(blob_service_client, container_name, source_folder)
    processed_blobs = list_blobs_with_prefix(blob_service_client, container_name, processed_folder)
    
    # Filter only PDFs in source and CSVs in processed
    source_pdfs = [blob for blob in source_blobs if blob.name.lower().endswith('.pdf')]
    processed_csvs = [blob for blob in processed_blobs if blob.name.lower().endswith('.csv')]
    
    # Get matching files
    matches = get_matching_pdf_and_csv(source_pdfs, processed_csvs)
    
    return source_pdfs, processed_csvs, matches

# Load files
source_pdfs, processed_csvs, matches = load_source_and_processed_files(
    st.session_state.blob_service_client, container_name, source_folder, processed_folder
)

# Show the number of files found
st.sidebar.write(f"Found {len(source_pdfs)} source PDFs")
st.sidebar.write(f"Found {len(processed_csvs)} processed CSVs")
st.sidebar.write(f"Found {len(matches)} matching pairs")

# Function to handle the refresh button
def refresh_files():
    st.cache_data.clear()
    st.experimental_rerun()

# Add refresh button
if st.sidebar.button("Refresh Files"):
    refresh_files()

# Clear all data button
if st.sidebar.button("Clear All Data", type="secondary"):
    for key in list(st.session_state.keys()):
        if key not in ['config', 'blob_service_client']:
            del st.session_state[key]
    gc.collect()
    st.sidebar.success("Data cleared!")
    st.rerun()

# View Results Mode
if app_mode == "View Results":
    st.header("View Extraction Results")
    
    # Show files in a table
    if matches:
        # Create a DataFrame for easier display
        match_data = []
        for match in matches:
            source_name = match["source"].name.split('/')[-1]
            processed_name = match["processed"].name.split('/')[-1]
            match_data.append({
                "Source PDF": source_name,
                "Processed CSV": processed_name,
                "Source Path": match["source"].name,
                "Processed Path": match["processed"].name
            })
        
        match_df = pd.DataFrame(match_data)
        st.dataframe(match_df, use_container_width=True)
        
        # Select a file to view
        selected_index = st.selectbox(
            "Select a file to view",
            range(len(matches)),
            format_func=lambda i: f"{match_data[i]['Source PDF']} - {match_data[i]['Processed CSV']}"
        )
        
        if st.button("View Selected File"):
            selected_match = matches[selected_index]
            
            # Download content
            pdf_content = download_blob_content(
                st.session_state.blob_service_client, 
                container_name, 
                selected_match["source"].name
            )
            
            csv_content = download_blob_content(
                st.session_state.blob_service_client, 
                container_name, 
                selected_match["processed"].name
            )
            
            if pdf_content and csv_content:
                # Store in session state for other tabs
                st.session_state.current_pdf_content = pdf_content
                st.session_state.current_csv_data = parse_csv_content(csv_content)
                st.session_state.current_source_path = selected_match["source"].name
                st.session_state.current_processed_path = selected_match["processed"].name
                
                # Create tabs for different views
                tabs = st.tabs(["Data Table", "Evaluation Results", "PDF Preview"])
                
                with tabs[0]:  # Data Table
                    st.subheader("Extracted Data")
                    if st.session_state.current_csv_data is not None:
                        st.dataframe(st.session_state.current_csv_data, use_container_width=True)
                    else:
                        st.warning("No CSV data available.")
                
                with tabs[1]:  # Evaluation Results
                    st.subheader("Confidence Analysis")
                    if st.session_state.current_csv_data is not None:
                        df = st.session_state.current_csv_data
                        
                        # Find confidence columns
                        confidence_cols = [col for col in df.columns if "Confidence" in col]
                        
                        if confidence_cols:
                            # Create metrics for average confidence
                            avg_confidence = df[confidence_cols].mean().mean()
                            
                            # Count fields with confidence above/below threshold
                            high_conf_count = (df[confidence_cols] >= 90).sum().sum()
                            low_conf_count = (df[confidence_cols] < 90).sum().sum()
                            total_fields = len(confidence_cols) * len(df)
                            
                            # Display metrics
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Average Confidence", f"{avg_confidence:.2f}%")
                            with col2:
                                st.metric("High Confidence Fields", f"{high_conf_count} ({high_conf_count/total_fields*100:.2f}%)")
                            with col3:
                                st.metric("Low Confidence Fields", f"{low_conf_count} ({low_conf_count/total_fields*100:.2f}%)")
                            
                            # Show confidence by field
                            st.subheader("Confidence by Field")
                            field_avgs = df[confidence_cols].mean().reset_index()
                            field_avgs.columns = ["Field", "Average Confidence"]
                            st.dataframe(field_avgs, use_container_width=True)
                        else:
                            st.warning("No confidence columns found in the CSV.")
                    else:
                        st.warning("No CSV data available.")
                
                with tabs[2]:  # PDF Preview
                    st.subheader("PDF Preview")
                    if st.session_state.current_pdf_content:
                        base64_pdf = convert_pdf_to_base64(st.session_state.current_pdf_content)
                        display_pdf_viewer(base64_pdf)
                    else:
                        st.warning("No PDF content available.")
                
                # Download options
                st.subheader("Download Options")
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.session_state.current_csv_data is not None:
                        csv_download = st.session_state.current_csv_data.to_csv(index=False)
                        st.download_button(
                            "Download CSV",
                            data=csv_download,
                            file_name=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv"
                        )
                
                with col2:
                    if st.session_state.current_pdf_content:
                        st.download_button(
                            "Download PDF",
                            data=st.session_state.current_pdf_content,
                            file_name=f"source_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                            mime="application/pdf"
                        )
    else:
        st.info(f"No matching files found for {confidence_selection}. Please check your configuration or try refreshing.")

# Manual Edit Mode
elif app_mode == "Manual Edit":
    st.header("Manual Edit")
    
    if (not hasattr(st.session_state, 'current_csv_data') or 
        st.session_state.current_csv_data is None or 
        not hasattr(st.session_state, 'current_pdf_content') or 
        st.session_state.current_pdf_content is None):
        st.warning("No data loaded. Please select a file in the View Results tab first.")
    else:
        # Display current file info
        st.info(f"Editing file: {st.session_state.current_source_path.split('/')[-1]}")
        
        # Create columns for PDF and data
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("PDF Document")
            base64_pdf = convert_pdf_to_base64(st.session_state.current_pdf_content)
            display_pdf_viewer(base64_pdf)
        
        with col2:
            st.subheader("Edit Data")
            # Get the data
            df = st.session_state.current_csv_data
            
            # Create form for editing
            with st.form("edit_form"):
                edited_df = st.data_editor(
                    df,
                    use_container_width=True,
                    num_rows="dynamic",
                    key="data_editor"
                )
                
                submitted = st.form_submit_button("Save Edits")
                
                if submitted:
                    # Store edited data
                    st.session_state.current_csv_data = edited_df
                    st.success("Edits saved!")
            
            # Add option to upload to final container
            st.subheader("Save to Final Container")
            save_location = st.selectbox(
                "Save Location",
                ["Original Location", "Final Container"]
            )
            
            save_button = st.button("Save Changes")
            
            if save_button:
                try:
                    # Convert DataFrame to CSV
                    csv_data = st.session_state.current_csv_data.to_csv(index=False)
                    
                    # Original file paths
                    source_path = st.session_state.current_source_path
                    processed_path = st.session_state.current_processed_path
                    
                    if save_location == "Original Location":
                        # Save back to original location
                        success, url = upload_blob_content(
                            st.session_state.blob_service_client,
                            container_name,
                            processed_path,
                            csv_data,
                            "text/csv"
                        )
                        
                        if success:
                            st.success(f"Saved to original location: {processed_path}")
                        else:
                            st.error("Failed to save changes.")
                    else:
                        # Save to final container
                        # Create paths in final container
                        confidence_level = "high_confidence" if confidence_selection == "High Confidence" else "low_confidence"
                        final_source_path = f"{final_folder}/{confidence_level}/source/{source_path.split('/')[-1]}"
                        final_processed_path = f"{final_folder}/{confidence_level}/processed/{processed_path.split('/')[-1]}"
                        
                        # Upload PDF to final container
                        pdf_success, pdf_url = upload_blob_content(
                            st.session_state.blob_service_client,
                            output_container,
                            final_source_path,
                            st.session_state.current_pdf_content,
                            "application/pdf"
                        )
                        
                        # Upload CSV to final container
                        csv_success, csv_url = upload_blob_content(
                            st.session_state.blob_service_client,
                            output_container,
                            final_processed_path,
                            csv_data,
                            "text/csv"
                        )
                        
                        if pdf_success and csv_success:
                            st.success(f"Saved to final container: {output_container}")
                            st.info(f"PDF: {final_source_path}")
                            st.info(f"CSV: {final_processed_path}")
                        else:
                            st.error("Failed to save to final container.")
                except Exception as e:
                    st.error(f"Error saving changes: {str(e)}")

# Bulk Upload Mode
elif app_mode == "Bulk Upload":
    st.header("Bulk Upload to Final Container")
    
    # Get all matches
    if matches:
        st.write(f"Found {len(matches)} matching pairs of files.")
        
        # Create a table of files
        match_data = []
        for i, match in enumerate(matches):
            source_name = match["source"].name.split('/')[-1]
            processed_name = match["processed"].name.split('/')[-1]
            match_data.append({
                "Index": i,
                "Source PDF": source_name,
                "Processed CSV": processed_name,
                "Source Path": match["source"].name,
                "Processed Path": match["processed"].name,
                "Selected": False
            })
        
        match_df = pd.DataFrame(match_data)
        
        # Let user select files
        st.markdown("### Select files to upload")
        selection = st.data_editor(
            match_df,
            column_config={"Selected": st.column_config.CheckboxColumn("Select", default=False)},
            disabled=["Index", "Source PDF", "Processed CSV", "Source Path", "Processed Path"],
            use_container_width=True,
            key="bulk_selection"
        )
        
        # Get selected files
        selected_indices = selection[selection["Selected"]]["Index"].tolist()
        selected_count = len(selected_indices)
        
        st.write(f"Selected {selected_count} files for upload.")
        
        # Upload button
        if st.button("Upload Selected Files", disabled=selected_count == 0):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            uploaded_count = 0
            for i, idx in enumerate(selected_indices):
                match = matches[idx]
                source_path = match["source"].name
                processed_path = match["processed"].name
                
                status_text.text(f"Processing {i+1}/{selected_count}: {source_path.split('/')[-1]}")
                
                # Download content
                try:
                    pdf_content = download_blob_content(
                        st.session_state.blob_service_client, 
                        container_name, 
                        source_path
                    )
                    
                    csv_content = download_blob_content(
                        st.session_state.blob_service_client, 
                        container_name, 
                        processed_path
                    )
                    
                    if pdf_content and csv_content:
                        # Create paths in final container
                        confidence_level = "high_confidence" if confidence_selection == "High Confidence" else "low_confidence"
                        final_source_path = f"{final_folder}/{confidence_level}/source/{source_path.split('/')[-1]}"
                        final_processed_path = f"{final_folder}/{confidence_level}/processed/{processed_path.split('/')[-1]}"
                        
                        # Upload PDF to final container
                        pdf_success, _ = upload_blob_content(
                            st.session_state.blob_service_client,
                            output_container,
                            final_source_path,
                            pdf_content,
                            "application/pdf"
                        )
                        
                        # Upload CSV to final container
                        csv_success, _ = upload_blob_content(
                            st.session_state.blob_service_client,
                            output_container,
                            final_processed_path,
                            csv_content,
                            "text/csv"
                        )
                        
                        if pdf_success and csv_success:
                            uploaded_count += 1
                except Exception as e:
                    st.error(f"Error processing {source_path.split('/')[-1]}: {str(e)}")
                
                # Update progress
                progress_bar.progress((i + 1) / selected_count)
                time.sleep(0.1)  # Small delay to show progress
            
            progress_bar.progress(1.0)
            status_text.text(f"Upload complete. Successfully uploaded {uploaded_count}/{selected_count} files.")
            
            # Show success message
            if uploaded_count == selected_count:
                st.success(f"All {selected_count} files uploaded successfully!")
            elif uploaded_count > 0:
                st.warning(f"Uploaded {uploaded_count}/{selected_count} files. Some uploads failed.")
            else:
                st.error("Failed to upload any files.")
    else:
        st.info(f"No matching files found for {confidence_selection}. Please check your configuration or try refreshing.")

# Footer
st.markdown("---")
st.markdown("""
### Usage Notes:
1. **View Results:** Browse and analyze extracted data from invoices
2. **Manual Edit:** Correct extraction errors and save changes
3. **Bulk Upload:** Process multiple files to the final container

For questions or issues, please contact your system administrator.
""")
