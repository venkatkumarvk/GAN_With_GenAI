import os
import io
import json
import base64
import pandas as pd
import streamlit as st
from azure.storage.blob import BlobServiceClient


def load_config(config_path="config.json"):
    with open(config_path, "r") as f:
        return json.load(f)


def get_blob_service_client(connection_string):
    return BlobServiceClient.from_connection_string(connection_string)


def list_blobs_with_prefix(blob_service_client, container_name, prefix=""):
    container_client = blob_service_client.get_container_client(container_name)
    return list(container_client.list_blobs(name_starts_with=prefix))


def download_blob_to_memory(blob_service_client, container_name, blob_name):
    blob_client = blob_service_client.get_container_client(container_name).get_blob_client(blob_name)
    return blob_client.download_blob().readall()


def upload_blob_from_memory(blob_service_client, container_name, blob_name, content):
    blob_client = blob_service_client.get_container_client(container_name).get_blob_client(blob_name)
    blob_client.upload_blob(content, overwrite=True)


def convert_pdf_to_base64(pdf_content):
    return base64.b64encode(pdf_content).decode('utf-8')


def display_pdf_viewer(base64_pdf, height=500):
    pdf_display = f"""
    <iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="{height}" type="application/pdf"></iframe>
    """
    st.markdown(pdf_display, unsafe_allow_html=True)


def load_csv_from_blob(blob_service_client, container_name, blob_name):
    content = download_blob_to_memory(blob_service_client, container_name, blob_name)
    return pd.read_csv(io.BytesIO(content))


def get_filename_from_blob_path(blob_path):
    return blob_path.split('/')[-1] if '/' in blob_path else blob_path


def match_source_and_processed_files(source_blobs, processed_blobs):
    sources = {get_filename_from_blob_path(b.name).split('.')[0]: b.name for b in source_blobs}
    processed = {get_filename_from_blob_path(b.name).split('.')[0]: b.name for b in processed_blobs}
    return [
        {"base_name": name, "source_blob": sources[name], "processed_blob": processed[name]}
        for name in sources if name in processed
    ]


def save_csv_to_blob(blob_service_client, container_name, blob_name, df):
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    upload_blob_from_memory(blob_service_client, container_name, blob_name, csv_buffer.getvalue())
