import streamlit as st
import folium
from streamlit_folium import st_folium
import xml.etree.ElementTree as ET
import re

st.set_page_config(page_title="Spatial Data Engine", layout="wide")

st.title("🗺️ Spatial Data Engine (Pure Python)")
st.caption("Multi-Layer India Spatial Catalog & Bhuvan XML Parser")

# Session State for Dataset Storage
if "datasets" not in st.session_state:
    st.session_state["datasets"] = {}

# Sidebar Upload Controls
st.sidebar.header("📥 Data Ingestion")
uploaded_xml = st.sidebar.file_uploader("Upload Bhuvan XML Metadata", type=["xml"])

# Parse XML if uploaded
if uploaded_xml is not None:
    try:
        tree = ET.parse(uploaded_xml)
        root = tree.getroot()
        
        tile_no = root.attrib.get('tileno', 'Unknown')
        
        info = root.find('Data_Identification_Information')
        dataset_name = info.find('Name_of_the_Dataset').text if info is not None and info.find('Name_of_the_Dataset') is not None else "N/A"
        theme = info.find('Theme').text if info is not None and info.find('Theme') is not None else "N/A"
        
        image_info = root.find('For_Image_Data')
        satellite = image_info.find('Name_of_the_Satellite').text if image_info is not None and image_info.find('Name_of_the_Satellite') is not None else "N/A"
        
        coverage = root.find('Coverage')
        if coverage is not None:
            ll_text = coverage.find('Lower_left').text
            match_lng = re.search(r'X\s*=\s*(\d+)E', ll_text)
            match_lat = re.search(r'Y\s*=\s*(\d+)N', ll_text)
            
            if match_lng and match_lat:
                block_key = f"{match_lng.group(1)}E_{match_lat.group(1)}N"
                st.session_state["datasets"][block_key] = {
                    "dataset_name": dataset_name,
                    "theme": theme,
                    "satellite": satellite,
                    "min_lng": int(match_lng.group(1)),
                    "min_lat": int(match_lat.group(1))
                }
                st.sidebar.success(f"Successfully registered block {block_key}!")
    except Exception as e:
        st.sidebar.error(f"Failed to parse XML: {e}")

# Build Folium Map
m = folium.Map(
    location=[22.5937, 78.9629],
    zoom_start=5,
    tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    attr='&copy; CARTO'
)

# Draw 1° Grid over India
for lat in range(6, 38):
    for lng in range(68, 98):
        block_key = f"{lng}E_{lat}N"
        bounds = [[lat, lng], [lat + 1, lng + 1]]

        if block_key in st.session_state["datasets"]:
            data = st.session_state["datasets"][block_key]
            folium.Rectangle(
                bounds=bounds,
                color="#10b981",
                weight=2,
                fill=True,
                fill_color="#10b981",
                fill_opacity=0.45,
                tooltip=f"Active Tile: {block_key} ({data['dataset_name']})"
            ).add_to(m)
        else:
            folium.Rectangle(
                bounds=bounds,
                color="#475569",
                weight=0.5,
                fill=True,
                fill_color="#475569",
                fill_opacity=0.05,
                tooltip=f"Tile Block: {block_key}"
            ).add_to(m)

# Display Map in Streamlit
map_data = st_folium(m, width="100%", height=600)

# Display Registry Table
st.subheader("📋 Registered Block Datasets")
if st.session_state["datasets"]:
    st.json(st.session_state["datasets"])
else:
    st.info("No datasets loaded yet. Upload a Bhuvan XML file in the sidebar.")
