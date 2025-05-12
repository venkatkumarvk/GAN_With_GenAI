import streamlit as st
from helper_functions import *
import pandas as pd

st.set_page_config(page_title="PDF Processor", layout="wide")
st.title("📄 PDF Processor with Confidence Threshold")

config = load_config()
blob_service_client = get_blob_service_client(config["azure_storage_connection_string"])
container_name = config["container_name"]

confidence_selection = st.sidebar.radio("Select Confidence Level", ["high_confidence", "low_confidence"])
source_prefix = config[f"{confidence_selection}_source_prefix"]
processed_prefix = config[f"{confidence_selection}_processed_prefix"]

# Load blob data
source_blobs = list_blobs_with_prefix(blob_service_client, container_name, source_prefix)
processed_blobs = list_blobs_with_prefix(blob_service_client, container_name, processed_prefix)
matched_files = match_source_and_processed_files(source_blobs, processed_blobs)

tabs = st.tabs(["Results View", "Manual Edit", "Bulk Operations"])

# --------------- Tab 1: Results View ----------------
with tabs[0]:
    st.header("📊 Results View")

    if matched_files:
        selected_file = st.selectbox(
            "Choose a file:",
            matched_files,
            format_func=lambda f: f["base_name"]
        )

        pdf_bytes = download_blob_to_memory(blob_service_client, container_name, selected_file["source_blob"])
        base64_pdf = convert_pdf_to_base64(pdf_bytes)
        display_pdf_viewer(base64_pdf)

        df = load_csv_from_blob(blob_service_client, container_name, selected_file["processed_blob"])
        st.dataframe(df, use_container_width=True)

        confidence_cols = [c for c in df.columns if "confidence" in c.lower()]
        if confidence_cols:
            avg_conf = df[confidence_cols].mean().mean()
            high_conf = avg_conf >= 95
            st.success(f"Average Confidence: {avg_conf:.2f}% - {'High' if high_conf else 'Low'}")

# --------------- Tab 2: Manual Edit ----------------
with tabs[1]:
    st.header("✏️ Manual Edit")

    if matched_files:
        selected_file = st.selectbox(
            "Select file to edit:",
            matched_files,
            format_func=lambda f: f["base_name"],
            key="manual_edit_select"
        )

        df = load_csv_from_blob(blob_service_client, container_name, selected_file["processed_blob"])
        st.dataframe(df, use_container_width=True)

        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

        if st.button("Save Changes"):
            save_csv_to_blob(
                blob_service_client,
                container_name,
                selected_file["processed_blob"],
                edited_df
            )
            st.success("CSV saved successfully.")

# --------------- Tab 3: Bulk Operations ----------------
with tabs[2]:
    st.header("🛠️ Bulk Operations")

    editable_files = [f for f in matched_files]
    selected_bulk = st.multiselect(
        "Select files to bulk edit:",
        editable_files,
        format_func=lambda f: f["base_name"]
    )

    if selected_bulk:
        bulk_dfs = {}
        for f in selected_bulk:
            df = load_csv_from_blob(blob_service_client, container_name, f["processed_blob"])
            bulk_dfs[f["base_name"]] = df

        tabs_bulk = st.tabs(list(bulk_dfs.keys()))
        edited = {}

        for i, (filename, df) in enumerate(bulk_dfs.items()):
            with tabs_bulk[i]:
                st.subheader(f"Editing: {filename}")
                edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True, key=filename)
                edited[filename] = edited_df

        if st.button("Save All Changes"):
            for f in selected_bulk:
                save_csv_to_blob(
                    blob_service_client,
                    container_name,
                    f["processed_blob"],
                    edited[f["base_name"]]
                )
            st.success("All selected CSVs updated successfully.")
