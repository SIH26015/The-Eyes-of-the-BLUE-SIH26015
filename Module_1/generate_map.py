import os
import re
import xml.etree.ElementTree as ET
import folium
from folium.plugins import MousePosition

def parse_bhuvan_xml(xml_file_path):
    """
    Parses Bhuvan XML metadata files to extract dataset attributes and bounding coordinates.
    """
    if not os.path.exists(xml_file_path):
        raise FileNotFoundError(f"XML file not found at: {xml_file_path}")

    tree = ET.parse(xml_file_path)
    root = tree.getroot()

    # Extract Tile Number attribute
    tile_no = root.attrib.get('tileno', 'Unknown Tile')

    # Helper function for safe element text extraction
    def get_text(parent, tag_name, default="N/A"):
        if parent is None:
            return default
        elem = parent.find(tag_name)
        return elem.text.strip() if elem is not None and elem.text else default

    # Extract Data Identification Information
    info = root.find('Data_Identification_Information')
    dataset_name = get_text(info, 'Name_of_the_Dataset')
    theme = get_text(info, 'Theme')
    keywords = get_text(info, 'Keywords')

    # Extract Image / Satellite Data
    image_info = root.find('For_Image_Data')
    satellite = get_text(image_info, 'Name_of_the_Satellite')
    sensor = get_text(image_info, 'Sensor')
    resolution = f"{get_text(image_info, 'Spatial_Resolution')} {get_text(image_info, 'Spatial_Resolution_Unit')}"

    # Extract Bounding Coordinates from Coverage Tag
    coverage = root.find('Coverage')
    coords = {'min_lat': None, 'max_lat': None, 'min_lng': None, 'max_lng': None}

    if coverage is not None:
        def extract_coords(text):
            match_lng = re.search(r'X\s*=\s*(\d+)E', text)
            match_lat = re.search(r'Y\s*=\s*(\d+)N', text)
            lng = float(match_lng.group(1)) if match_lng else None
            lat = float(match_lat.group(1)) if match_lat else None
            return lng, lat

        ll_lng, ll_lat = extract_coords(get_text(coverage, 'Lower_left'))
        ur_lng, ur_lat = extract_coords(get_text(coverage, 'Upper_right'))

        coords = {
            'min_lat': ll_lat,
            'max_lat': ur_lat,
            'min_lng': ll_lng,
            'max_lng': ur_lng
        }

    return {
        'tile_no': tile_no,
        'dataset_name': dataset_name,
        'theme': theme,
        'keywords': keywords,
        'satellite': satellite,
        'sensor': sensor,
        'resolution': resolution,
        'bounds': coords
    }


def build_spatial_map(metadata_list, output_html="index.html"):
    """
    Generates an interactive Leaflet map centered over India with 1° Grid tiles.
    Uses free CARTO dark basemaps (no API key needed).
    """
    # 1. Initialize Map centered over India
    m = folium.Map(
        location=[22.5937, 78.9629],
        zoom_start=5,
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        attr='&copy; <a href="https://carto.com/">CARTO</a>'
    )

    # Add Mouse Coordinate Tracker to Bottom-Left
    MousePosition(position="bottomleft").add_to(m)

    # Index registered dataset tiles by their lower-left grid key (e.g., '72E_18N')
    registered_tiles = {}
    for meta in metadata_list:
        b = meta['bounds']
        if b['min_lng'] is not None and b['min_lat'] is not None:
            key = f"{int(b['min_lng'])}E_{int(b['min_lat'])}N"
            registered_tiles[key] = meta

    # 2. Construct 1° x 1° Spatial Grid across India (6°N to 38°N, 68°E to 98°E)
    grid_group = folium.FeatureGroup(name="1° Grid Overlay")

    for lat in range(6, 38):
        for lng in range(68, 98):
            block_key = f"{lng}E_{lat}N"
            bounds = [[lat, lng], [lat + 1, lng + 1]]

            # Highlight tile if parsed metadata exists for this grid block
            if block_key in registered_tiles:
                meta = registered_tiles[block_key]
                popup_content = f"""
                <div style="font-family: Arial, sans-serif; width: 240px;">
                    <h4 style="margin: 0 0 6px 0; color: #2563eb;">Tile Index: {block_key}</h4>
                    <hr style="margin: 4px 0; border: 0; border-top: 1px solid #ccc;">
                    <p style="margin: 3px 0; font-size: 11px;"><b>Dataset:</b> {meta['dataset_name']}</p>
                    <p style="margin: 3px 0; font-size: 11px;"><b>Theme:</b> {meta['theme']}</p>
                    <p style="margin: 3px 0; font-size: 11px;"><b>Satellite:</b> {meta['satellite']}</p>
                    <p style="margin: 3px 0; font-size: 11px;"><b>Sensor:</b> {meta['sensor']}</p>
                    <p style="margin: 3px 0; font-size: 11px;"><b>Resolution:</b> {meta['resolution']}</p>
                </div>
                """
                folium.Rectangle(
                    bounds=bounds,
                    color="#10b981",
                    weight=2,
                    fill=True,
                    fill_color="#10b981",
                    fill_opacity=0.45,
                    popup=folium.Popup(popup_content, max_width=260),
                    tooltip=f"Active Tile: {block_key} ({meta['dataset_name']})"
                ).add_to(grid_group)
            else:
                folium.Rectangle(
                    bounds=bounds,
                    color="#475569",
                    weight=0.5,
                    fill=True,
                    fill_color="#475569",
                    fill_opacity=0.05,
                    tooltip=f"Grid Block: {block_key}"
                ).add_to(grid_group)

    grid_group.add_to(m)
    folium.LayerControl().add_to(m)

    # Save to HTML file
    m.save(output_html)
    print(f"\n✅ Success! Map generated at: '{output_html}'")
    print(f"👉 Double-click '{output_html}' to view in your web browser.")


if __name__ == "__main__":
    xml_file = "cdne43g.xml"

    try:
        parsed_metadata = parse_bhuvan_xml(xml_file)
        print("Successfully Parsed XML Metadata:")
        for key, val in parsed_metadata.items():
            print(f"  • {key}: {val}")

        build_spatial_map([parsed_metadata])

    except FileNotFoundError:
        print(f"⚠️ '{xml_file}' not found. Generating default India grid map...")
        build_spatial_map([])
