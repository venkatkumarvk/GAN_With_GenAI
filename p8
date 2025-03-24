def add_manual_verification_section(all_pdf_results, timestamp, blob_service_client=None, result_upload_container=None):
    """
    Add a section for manual verification of all fields regardless of confidence score.
    Users can edit all fields and update the text and CSV files.
    
    Parameters:
    - all_pdf_results: List of PDF results
    - timestamp: Current timestamp for filenames
    - blob_service_client: Optional, for Azure Blob Storage
    - result_upload_container: Optional, for Azure Blob Storage
    """
    st.subheader("4. Manual Verification and Editing")
    
    # Store the session state for edits
    if 'edited_results' not in st.session_state:
        st.session_state.edited_results = all_pdf_results.copy()
    
    # Create tabs for each PDF
    if len(all_pdf_results) > 0:
        pdf_tabs = st.tabs([pdf_result["filename"] for pdf_result in all_pdf_results])
        
        for i, tab in enumerate(pdf_tabs):
            with tab:
                pdf_result = all_pdf_results[i]
                filename = pdf_result["filename"]
                
                st.write(f"### Editing: {filename}")
                
                # Create form for each page
                for page_idx, page in enumerate(pdf_result["pages"]):
                    page_num = page["page"]
                    data = page["data"]
                    
                    with st.expander(f"Page {page_num}"):
                        if "error" in data:
                            st.error(f"Error processing this page: {data['error']}")
                            continue
                        
                        # Create a form for editing fields
                        with st.form(key=f"edit_form_{filename}_{page_num}"):
                            # Define the fields we're extracting
                            fields = [
                                "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
                                "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
                                "Freight", "Salestax", "Total"
                            ]
                            
                            # Field columns
                            col1, col2 = st.columns(2)
                            
                            field_values = {}
                            
                            # Create input fields for each field
                            for idx, field in enumerate(fields):
                                field_display = ' '.join(field.replace('_', ' ').title().split())
                                
                                # Get current value and confidence
                                field_data = data.get(field, {})
                                
                                if isinstance(field_data, dict):
                                    current_value = field_data.get("value", "")
                                    confidence = field_data.get("confidence", 0)
                                    confidence_pct = round(confidence * 100, 2)
                                else:
                                    current_value = field_data if field_data else ""
                                    confidence_pct = 0
                                
                                # Create input field with appropriate column
                                if idx < len(fields) // 2 + len(fields) % 2:
                                    with col1:
                                        field_values[field] = st.text_input(
                                            f"{field_display} (Confidence: {confidence_pct}%)",
                                            value=current_value,
                                            key=f"{filename}_{page_num}_{field}"
                                        )
                                else:
                                    with col2:
                                        field_values[field] = st.text_input(
                                            f"{field_display} (Confidence: {confidence_pct}%)",
                                            value=current_value,
                                            key=f"{filename}_{page_num}_{field}"
                                        )
                            
                            # Submit button
                            submit_button = st.form_submit_button("Save Changes")
                            
                            if submit_button:
                                # Update the data in session state
                                for field, value in field_values.items():
                                    # Get original confidence value
                                    original_field_data = data.get(field, {})
                                    original_confidence = 0
                                    
                                    if isinstance(original_field_data, dict) and "confidence" in original_field_data:
                                        original_confidence = original_field_data.get("confidence", 0)
                                    
                                    # Update with edited value but keep original confidence
                                    st.session_state.edited_results[i]["pages"][page_idx]["data"][field] = {
                                        "value": value,
                                        "confidence": original_confidence,
                                        "manually_edited": True
                                    }
                                
                                st.success(f"Changes saved for page {page_num}")
    
    # Add a button to update all files with the edited data
    update_col1, update_col2 = st.columns([1, 3])
    
    with update_col1:
        update_button = st.button("Update All Files with Edits", type="primary")
    
    with update_col2:
        if update_button:
            # Use the edited results to update files
            with st.spinner("Updating files with edited data..."):
                # Create updated text files
                text_zip = create_text_files_zip(st.session_state.edited_results)
                
                # Create updated CSV
                results_df = create_results_dataframe(st.session_state.edited_results)
                
                # Upload updated files to blob storage if available
                if blob_service_client and result_upload_container:
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
                
                # Provide download buttons for updated files
                st.write("### Download Updated Files")
                download_col1, download_col2 = st.columns(2)
                
                with download_col1:
                    # Download updated text files as a zip
                    st.download_button(
                        label="Download Updated Text Files (ZIP)",
                        data=text_zip,
                        file_name=f"extracted_data_{timestamp}_edited.zip",
                        mime="application/zip"
                    )
                
                with download_col2:
                    # Download updated CSV
                    csv = results_df.to_csv(index=False)
                    st.download_button(
                        label="Download Updated CSV Results",
                        data=csv,
                        file_name=f"financial_data_extraction_{timestamp}_edited.csv",
                        mime="text/csv"
                    )
                
                st.success("All files have been updated with your edits.")
                
                # Option to clear memory and restart flow
                restart_button = st.button("Restart Process (Clear Memory)")
                if restart_button:
                    # Clear session state to restart flow
                    for key in list(st.session_state.keys()):
                        del st.session_state[key]
                    st.experimental_rerun()

# Create a modified version of the create_results_dataframe function that respects edited values
def create_results_dataframe_with_edits(all_pdf_results):
    """
    Create a pandas DataFrame from the extracted results, including any manual edits.
    """
    rows = []
    
    # Define the fields we're extracting
    fields = [
        "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
        "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
        "Freight", "Salestax", "Total"
    ]
    
    for pdf_result in all_pdf_results:
        filename = pdf_result["filename"]
        
        for page in pdf_result["pages"]:
            page_num = page["page"]
            data = page["data"]
            
            # Check for errors
            if "error" in data:
                row_data = {
                    "Filename": filename,
                    "Page": page_num
                }
                
                # Add placeholders for all fields and confidence values
                for field in fields:
                    row_data[field] = "N/A"
                    row_data[f"{field} Confidence"] = 0
                    row_data[f"{field} Edited"] = "No"
                
                rows.append(row_data)
                continue
            
            # Initialize row data
            row_data = {
                "Filename": filename,
                "Page": page_num
            }
            
            # Process each field
            for field in fields:
                field_data = data.get(field, {})
                
                if isinstance(field_data, dict):
                    value = field_data.get("value", "N/A")
                    confidence = field_data.get("confidence", 0)
                    manually_edited = field_data.get("manually_edited", False)
                else:
                    value = field_data if field_data else "N/A"
                    confidence = 0
                    manually_edited = False
                
                # Ensure values are strings to avoid PyArrow errors
                if isinstance(value, (list, dict)):
                    value = str(value)
                
                # Add to row data
                row_data[field] = value
                row_data[f"{field} Confidence"] = round(confidence * 100, 2)
                row_data[f"{field} Edited"] = "Yes" if manually_edited else "No"
            
            # Add completed row to rows
            rows.append(row_data)
    
    try:
        # Create DataFrame with string type
        return pd.DataFrame(rows, dtype=str)
    except Exception as e:
        st.warning(f"Error creating DataFrame: {e}. Trying alternative method...")
        
        try:
            # Try with pandas default types but disable PyArrow
            with pd.option_context('mode.dtype_backend', 'numpy'):
                return pd.DataFrame(rows)
        except Exception as e:
            st.warning(f"Second method failed: {e}. Using final fallback method...")
            
            try:
                # Convert all values to strings explicitly before creating DataFrame
                string_rows = []
                for row in rows:
                    string_row = {}
                    for key, value in row.items():
                        string_row[key] = str(value)
                    string_rows.append(string_row)
                return pd.DataFrame(string_rows)
            except Exception as e:
                st.error(f"All DataFrame creation methods failed: {e}")
                return pd.DataFrame()
                
 # Modifications to the main() function to integrate manual verification
# These changes should be added to the main() function

# Replace the existing functions with updated versions that support manual editing
def create_text_files_zip(all_pdf_results):
    """
    Create a zip file containing text files for each PDF.
    Works with both original and edited results.
    """
    # Create a BytesIO object to store the zip file
    zip_buffer = io.BytesIO()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Create a ZipFile object
    with zipfile.ZipFile(zip_buffer, 'a', zipfile.ZIP_DEFLATED, False) as zip_file:
        for pdf_result in all_pdf_results:
            filename = pdf_result["filename"]
            base_filename = os.path.splitext(filename)[0]
            
            # Create the text content for this PDF (only key-value pairs)
            page_results_text = create_page_results_text(pdf_result)
            
            # Add structured data as a text file with timestamp
            zip_file.writestr(f"{base_filename}_{timestamp}.txt", page_results_text)
    
    # Seek to the beginning of the BytesIO object
    zip_buffer.seek(0)
    return zip_buffer

def create_page_results_text(pdf_result):
    """
    Create a text file containing only the key-value pairs from each page.
    Returns a string with the formatted key-value pairs.
    Supports both original and edited values.
    """
    # Define the fields we're extracting
    fields = [
        "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
        "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
        "Freight", "Salestax", "Total"
    ]
    
    result_text = ""
    
    for page in pdf_result["pages"]:
        page_num = page["page"]
        data = page["data"]
        
        result_text += f"--- PAGE {page_num} ---\n"
        
        if "error" in data:
            result_text += f"error: {data['error']}\n\n"
            continue
            
        # Process fields with confidence scores
        for field in fields:
            display_field = ''.join(' ' + char if char.isupper() else char for char in field).strip().lower()
            
            field_data = data.get(field, {})
            if isinstance(field_data, dict):
                value = field_data.get("value", "N/A")
                confidence = field_data.get("confidence", 0)
                manually_edited = field_data.get("manually_edited", False)
                
                result_text += f"{display_field}: {value}\n"
                result_text += f"{display_field} confidence: {round(confidence * 100, 2)}%\n"
                
                if manually_edited:
                    result_text += f"{display_field} manually edited: Yes\n"
            else:
                result_text += f"{display_field}: {field_data}\n"
        
        result_text += "\n"
        
    return result_text

def create_results_dataframe(all_pdf_results):
    """
    Create a pandas DataFrame from the extracted results.
    Works with both original and edited results.
    """
    rows = []
    
    # Define the fields we're extracting
    fields = [
        "VendorName", "InvoiceNumber", "InvoiceDate", "CustomerName", 
        "PurchaseOrder", "StockCode", "UnitPrice", "InvoiceAmount", 
        "Freight", "Salestax", "Total"
    ]
    
    for pdf_result in all_pdf_results:
        filename = pdf_result["filename"]
        
        for page in pdf_result["pages"]:
            page_num = page["page"]
            data = page["data"]
            
            # Check for errors
            if "error" in data:
                row_data = {
                    "Filename": filename,
                    "Page": page_num
                }
                
                # Add placeholders for all fields and confidence values
                for field in fields:
                    row_data[field] = "N/A"
                    row_data[f"{field} Confidence"] = 0
                    row_data[f"{field} Edited"] = "No"
                
                rows.append(row_data)
                continue
            
            # Initialize row data
            row_data = {
                "Filename": filename,
                "Page": page_num
            }
            
            # Process each field
            for field in fields:
                field_data = data.get(field, {})
                
                if isinstance(field_data, dict):
                    value = field_data.get("value", "N/A")
                    confidence = field_data.get("confidence", 0)
                    manually_edited = field_data.get("manually_edited", False)
                else:
                    value = field_data if field_data else "N/A"
                    confidence = 0
                    manually_edited = False
                
                # Ensure values are strings to avoid PyArrow errors
                if isinstance(value, (list, dict)):
                    value = str(value)
                
                # Add to row data
                row_data[field] = value
                row_data[f"{field} Confidence"] = round(confidence * 100, 2)
                row_data[f"{field} Edited"] = "Yes" if manually_edited else "No"
            
            # Add completed row to rows
            rows.append(row_data)
    
    try:
        # First method: Try creating a DataFrame with string type
        return pd.DataFrame(rows, dtype=str)
    except Exception as e:
        st.warning(f"Error creating DataFrame: {e}. Trying alternative method...")
        
        try:
            # Second method: Try with pandas default types but disable PyArrow
            with pd.option_context('mode.dtype_backend', 'numpy'):
                return pd.DataFrame(rows)
        except Exception as e:
            st.warning(f"Second method failed: {e}. Using final fallback method...")
            
            try:
                # Third method: Convert all values to strings explicitly before creating DataFrame
                string_rows = []
                for row in rows:
                    string_row = {}
                    for key, value in row.items():
                        string_row[key] = str(value)
                    string_rows.append(string_row)
                return pd.DataFrame(string_rows)
            except Exception as e:
                st.error(f"All DataFrame creation methods failed: {e}")
                # Return empty DataFrame as absolute last resort
                return pd.DataFrame()

# In the main() function, replace the section after "4. Documents Needing Manual Verification"
# with the following code:

# Remove the original code that looks like this:
"""
    # 4. Documents that need manual verification
    st.subheader("4. Documents Needing Manual Verification")
    
    # Get documents with fields in low confidence range
    docs_to_verify = []
    
    for filename, counts in confidence_by_document.items():
        if counts["low"] > 0:
            docs_to_verify.append({
                "filename": filename,
                "low_count": counts["low"]
            })
    
    if docs_to_verify:
        for doc in docs_to_verify:
            st.warning(f"⚠️ {doc['filename']} - Needs verification ({doc['low_count']} fields with <90% confidence)")
    else:
        st.success("✅ No documents need manual verification (all fields above 90% confidence)")
"""

# Replace with this call to add_manual_verification_section:
add_manual_verification_section(all_pdf_results, timestamp, blob_service_client, result_upload_container)

# Then continue with the existing section 5 (which will now become section 5):
"""
# 5. Display Blob Storage upload results
if blob_service_client and blob_upload_results:
    st.subheader("5. Azure Blob Storage Upload Results")
    ...
"""

# Important: Update the numbering in the subsequent sections (5, 6, 7) to (6, 7, 8)
