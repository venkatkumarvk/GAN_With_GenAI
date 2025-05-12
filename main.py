import streamlit as st
import pandas as pd
import os
import io
from datetime import datetime
from helper_functions import (
    load_config, get_blob_service_client, list_blobs_by_folder, create_blob_dataframe,
    download_blob_to_memory, render_pdf_preview, convert_pdf_to_base64, display_pdf_viewer,
    load_csv_from_blob, update_edited_data, apply_edits_to_csv, create_bulk_upload_csv,
    upload_edited_results
)

# Set page configuration
st.set_page_config(
    page_title="PDF Financial Data Viewer",
    page_icon="📊",
    layout="wide"
)

# Initialize session state for persistence
if 'edited_data' not in st.session_state:
    st.session_state.edited_data = {}
if 'edit_timestamps' not in st.session_state:
    st.session_state.edit_timestamps = {}
if 'high_confidence_df' not in st.session_state:
    st.session_state.high_confidence_df = None
if 'low_confidence_df' not in st.session_state:
    st.session_state.low_confidence_df = None
if 'selected_confidence' not in st.session_state:
    st.session_state.selected_confidence = "High"
if 'currently_editing_file' not in st.session_state:
    st.session_state.currently_editing_file = None

# Load configuration
config = load_config()

# Get blob service client
blob_service_client = get_blob_service_client(config)

# Main title
st.title("PDF Financial Data Viewer")

# Sidebar with confidence selection
st.sidebar.title("Options")
confidence_level = st.sidebar.radio(
    "Select Confidence Level",
    ["High", "Low"],
    key="confidence_selector"
)

st.session_state.selected_confidence = confidence_level

# Get container names from config
source_container = config.get("source_container", "pdf-extraction-source")
results_container = config.get("results_container", "pdf-extraction-results")

# Get folder prefixes from config
source_folder = config.get("source_folder", "source/")
processed_folder = config.get(f"{confidence_level.lower()}_confidence_folder", f"{confidence_level.lower()}_confidence/")

# Main navigation tabs
tabs = st.tabs(["Results", "Evaluation", "Manual Edit", "Bulk Upload", "Download"])

# Tab 1: Results
with tabs[0]:
    st.header(f"{confidence_level} Confidence Results")
    
    # List blobs in the source and processed folders
    source_blobs = list_blobs_by_folder(blob_service_client, source_container, source_folder)
    processed_blobs = list_blobs_by_folder(blob_service_client, results_container, processed_folder)
    
    # Create DataFrames
    source_df = create_blob_dataframe(source_blobs, source_folder)
    processed_df = create_blob_dataframe(processed_blobs, processed_folder)
    
    # Create two columns for display
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Source Files")
        st.dataframe(source_df, use_container_width=True)
    
    with col2:
        st.subheader("Processed Results")
        st.dataframe(processed_df, use_container_width=True)
    
    # Select a file to preview
    st.subheader("Preview Files")
    
    # Find matching filenames between source and processed
    matching_files = []
    for source_file in source_df["Filename"]:
        for processed_file in processed_df["Filename"]:
            if source_file in processed_file or processed_file in source_file:
                matching_files.append((source_file, processed_file))
    
    if matching_files:
        # Select a file pair to view
        selected_pair = st.selectbox(
            "Select File Pair to Preview",
            options=matching_files,
            format_func=lambda x: f"Source: {x[0]} | Processed: {x[1]}"
        )
        
        if selected_pair:
            source_file, processed_file = selected_pair
            
            # Get the full paths
            source_path = source_folder + source_file
            processed_path = processed_folder + processed_file
            
            # Create two columns for preview
            prev_col1, prev_col2 = st.columns(2)
            
            with prev_col1:
                st.write(f"### Source: {source_file}")
                
                # Download and display PDF
                source_content = download_blob_to_memory(
                    blob_service_client, 
                    source_container, 
                    source_path
                )
                
                if source_content:
                    source_base64 = convert_pdf_to_base64(source_content)
                    display_pdf_viewer(source_base64, height=400)
            
            with prev_col2:
                st.write(f"### Processed: {processed_file}")
                
                # Load and display CSV
                df = load_csv_from_blob(
                    blob_service_client,
                    results_container,
                    processed_path
                )
                
                if df is not None:
                    st.dataframe(df, use_container_width=True)
                    
                    # Store in session state for later use
                    if confidence_level == "High":
                        st.session_state.high_confidence_df = df
                    else:
                        st.session_state.low_confidence_df = df
    else:
        st.info("No matching files found between source and processed folders")

# Tab 2: Evaluation
with tabs[1]:
    st.header("Evaluation Results")
    
    # Load DataFrame from session state
    df = st.session_state.high_confidence_df if confidence_level == "High" else st.session_state.low_confidence_df
    
    if df is not None and not df.empty:
        # Check if DataFrame has confidence scores
        if any(col.endswith(' Confidence') for col in df.columns):
            # Analyze confidence scores
            confidence_cols = [col for col in df.columns if col.endswith(' Confidence')]
            
            # Calculate average confidence by field
            field_confidences = {}
            for col in confidence_cols:
                field_name = col.replace(' Confidence', '')
                avg_confidence = df[col].mean()
                field_confidences[field_name] = avg_confidence
            
            # Display field confidence scores
            st.subheader("Average Confidence by Field")
            
            # Create a DataFrame for field confidences
            field_conf_df = pd.DataFrame({
                "Field": list(field_confidences.keys()),
                "Average Confidence (%)": [round(conf, 2) for conf in field_confidences.values()]
            })
            
            # Sort by confidence
            field_conf_df = field_conf_df.sort_values("Average Confidence (%)", ascending=False)
            
            # Display as table
            st.dataframe(field_conf_df, use_container_width=True)
            
            # Create a bar chart
            st.bar_chart(field_conf_df.set_index("Field"))
            
            # Show files with low confidence fields
            st.subheader("Files with Low Confidence Fields")
            
            # Identify rows with any field below threshold
            threshold = 90 if confidence_level == "High" else 75
            low_confidence_mask = pd.Series(False, index=df.index)
            
            for col in confidence_cols:
                low_confidence_mask = low_confidence_mask | (df[col] < threshold)
            
            low_confidence_rows = df[low_confidence_mask]
            
            if not low_confidence_rows.empty:
                st.dataframe(low_confidence_rows[["Filename", "Page"] + confidence_cols], use_container_width=True)
            else:
                st.success(f"No fields with confidence below {threshold}%")
        else:
            st.warning("No confidence score columns found in the data")
    else:
        st.info("No data available for evaluation. Please select a file pair in the Results tab.")

# Tab 3: Manual Edit
with tabs[2]:
    st.header("Manual Editing")
    
    # Load DataFrame from session state
    df = st.session_state.high_confidence_df if confidence_level == "High" else st.session_state.low_confidence_df
    
    if df is not None and not df.empty:
        # Get unique filenames
        filenames = df["Filename"].unique()
        
        # Select a file to edit
        selected_file = st.selectbox(
            "Select File to Edit",
            options=filenames
        )
        
        if selected_file:
            # Store currently editing file
            st.session_state.currently_editing_file = selected_file
            
            # Filter to just this file
            file_df = df[df["Filename"] == selected_file].copy()
            
            # Get pages for this file
            pages = file_df["Page"].unique()
            
            # Select a page to edit
            selected_page = st.selectbox(
                "Select Page to Edit",
                options=pages
            )
            
            if selected_page is not None:
                # Get the row for this page
                page_data = file_df[file_df["Page"] == selected_page].iloc[0]
                
                # Define the fields we can edit
                editable_fields = [
                    "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
                    "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
                    "Freight", "Salestax", "Total"
                ]
                
                # Only include fields that exist in the DataFrame
                editable_fields = [f for f in editable_fields if f in file_df.columns]
                
                # Create an editing form
                with st.form(key=f"edit_form_{selected_file}_{selected_page}"):
                    st.write(f"### Editing {selected_file} - Page {selected_page}")
                    
                    # Create columns for field and confidence
                    edited_values = {}
                    
                    for field in editable_fields:
                        col1, col2 = st.columns([3, 1])
                        
                        # Get current value and confidence
                        current_value = page_data.get(field, "")
                        confidence_col = f"{field} Confidence"
                        confidence = page_data.get(confidence_col, 0) if confidence_col in page_data else 0
                        
                        # Check if we have an edited value
                        edited_value = None
                        if (selected_file in st.session_state.edited_data and 
                            str(selected_page) in st.session_state.edited_data[selected_file] and
                            field in st.session_state.edited_data[selected_file][str(selected_page)]):
                            edited_value = st.session_state.edited_data[selected_file][str(selected_page)][field]
                        
                        # Display the field input
                        with col1:
                            # Add visual indicator for low confidence
                            field_label = field
                            if confidence < 90:
                                field_label = f"{field} ⚠️"
                            
                            # Use the edited value if available, otherwise the current value
                            value_to_show = edited_value if edited_value is not None else current_value
                            
                            # Text input for the field
                            new_value = st.text_input(
                                field_label,
                                value=value_to_show,
                                key=f"field_{selected_file}_{selected_page}_{field}"
                            )
                            
                            # Store for later
                            edited_values[field] = new_value
                        
                        # Display confidence
                        with col2:
                            confidence_color = "green" if confidence >= 90 else "red"
                            st.markdown(f"<p style='color:{confidence_color};'>Confidence: {confidence:.1f}%</p>", unsafe_allow_html=True)
                    
                    # Submit button
                    submit_button = st.form_submit_button("Save Edits")
                    
                    if submit_button:
                        # Check which fields were changed
                        for field, new_value in edited_values.items():
                            current_value = page_data.get(field, "")
                            if new_value != current_value:
                                # Update edited data in session state
                                update_edited_data(selected_file, str(selected_page), field, new_value)
                        
                        st.success(f"Edits saved for {selected_file} - Page {selected_page}")
                
                # Show status of edited fields
                if (selected_file in st.session_state.edited_data and 
                    str(selected_page) in st.session_state.edited_data[selected_file]):
                    st.info(f"You have edited {len(st.session_state.edited_data[selected_file][str(selected_page)])} fields on this page.")
            
            # Button to apply edits to DataFrame
            if st.button("Apply Edits to Results"):
                # Get edited data for this file
                if selected_file in st.session_state.edited_data:
                    # Apply edits to DataFrame
                    edited_df = apply_edits_to_csv(
                        df,
                        {selected_file: st.session_state.edited_data[selected_file]},
                        st.session_state.edit_timestamps
                    )
                    
                    # Update session state
                    if confidence_level == "High":
                        st.session_state.high_confidence_df = edited_df
                    else:
                        st.session_state.low_confidence_df = edited_df
                    
                    st.success("Edits applied to results successfully!")
                    
                    # Option to upload to final container
                    if st.button("Upload Edited Results to Final Container"):
                        success, result = upload_edited_results(
                            blob_service_client,
                            config,
                            edited_df,
                            confidence_level
                        )
                        
                        if success:
                            st.success(f"Edited results uploaded successfully to final container")
                        else:
                            st.error(f"Error uploading edited results: {result}")
                else:
                    st.warning("No edits found for this file")
    else:
        st.info("No data available for editing. Please select a file pair in the Results tab.")

# Tab 4: Bulk Upload
with tabs[3]:
    st.header("Bulk Upload")
    
    # Get DataFrames from session state
    high_df = st.session_state.high_confidence_df
    low_df = st.session_state.low_confidence_df
    
    if high_df is not None or low_df is not None:
        # Check if we have edits
        has_edits = len(st.session_state.edited_data) > 0
        
        if has_edits:
            # Apply edits to both DataFrames
            if high_df is not None:
                high_df = apply_edits_to_csv(
                    high_df,
                    st.session_state.edited_data,
                    st.session_state.edit_timestamps
                )
            
            if low_df is not None:
                low_df = apply_edits_to_csv(
                    low_df,
                    st.session_state.edited_data,
                    st.session_state.edit_timestamps
                )
            
            st.success("Edits have been applied to the combined data")
        
        # Combine for bulk upload
        combined_df = create_bulk_upload_csv(high_df, low_df)
        
        # Show preview
        st.subheader("Combined Data Preview")
        st.dataframe(combined_df, use_container_width=True)
        
        # Create CSV for download
        csv = combined_df.to_csv(index=False)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Download button
        st.download_button(
            label="Download Combined CSV",
            data=csv,
            file_name=f"combined_data_{timestamp}.csv",
            mime="text/csv"
        )
        
        # Upload to final container
        st.subheader("Upload to Final Container")
        final_container = config.get("final_container", "pdf-extraction-final")
        
        st.write(f"Final Container: {final_container}")
        
        if st.button("Upload Combined Data to Final Container"):
            try:
                # Prepare CSV data
                csv_data = combined_df.to_csv(index=False)
                
                # Generate blob name
                blob_name = f"combined_data_{timestamp}.csv"
                
                # Upload to blob storage
                success, url = upload_to_blob_storage(
                    blob_service_client,
                    final_container,
                    blob_name,
                    csv_data.encode('utf-8'),
                    "text/csv"
                )
                
                if success:
                    st.success(f"Combined data uploaded successfully to {final_container}")
                else:
                    st.error(f"Error uploading combined data: {url}")
            except Exception as e:
                st.error(f"Error in bulk upload: {str(e)}")
    else:
        st.info("No data available for bulk upload. Please view files in the Results tab first.")

# Tab 5: Download
with tabs[4]:
    st.header("Download")
    
    # Get DataFrames from session state
    high_df = st.session_state.high_confidence_df
    low_df = st.session_state.low_confidence_df
    
    # Create columns for high and low confidence downloads
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("High Confidence Data")
        if high_df is not None and not high_df.empty:
            # Apply any edits
            if len(st.session_state.edited_data) > 0:
                high_df = apply_edits
