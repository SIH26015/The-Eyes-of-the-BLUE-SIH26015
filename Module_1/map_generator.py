import xml.etree.ElementTree as ET
import re
import folium
from folium.plugins import MousePosition

# 1. Helper function to parse Bhuvan XML Metadata
def parse_bhuvan_xml(xml_file_path):
    tree = ET.parse(xml_file_path)
    root = tree.getroot()
    
    # Extract general info
    tile_no = root.attrib.get('tileno', 'Unknown Tile')
    
    # Safely extract tags
    def get_text(parent, tag_name, default="N/A"):
        elem = parent.find(tag_name)
        return elem.text.strip() if elem is not None and elem.text else default

    info = root.find('Data_Identification_Information')
    dataset_name = get_text(info, 'Name_of_the_Dataset') if info is not None else "N/A"
    theme = get_text(info, 'Theme') if info is not None else "N/A"
    
    image_info = root.find('For_Image_Data')
    satellite = get_text(image_info, 'Name_of_the_Satellite') if image_info is not None else "N/A"
    resolution = f"{get_text(image_info, 'Spatial_Resolution')} {get_text(image_info, 'Spatial_Resolution_Unit')}" if image_info is not None else "N/A"

    # Extract Coverage Bounding Coordinates (e.g., "X = 72E, Y = 18N")
    coverage = root.find('Coverage')
    coords = {'min_lat': None, 'max_lat': None, 'min_lng': None, 'max_lng': None}
    
    if coverage is not None:
        def extract_deg(text):
            match_lng = re.search(r'X\s*=\s*(\d+)E', text)
            match_lat = re.search(r'Y\s*=\s*(\d+)N', text)
            lng = float(match_lng.group(1)) if match_lng else None
            lat = float(match_lat.group(1)) if match_lat else None
            return lng, lat

        ll_lng, ll_lat = extract_deg(get_text(coverage, 'Lower_left'))
        ur_lng, ur_lat = extract_deg(get_text(coverage, 'Upper_right'))

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
        'satellite': satellite,
        'resolution': resolution,
        'bounds': coords
    }

# 2. Build Interactive Leaflet Map in Python
def build_spatial_map(metadata_list=None):
    if metadata_list is None:
        metadata_list = []

    # Create Base Map centered over India
    m = folium.Map(
        location=[22.5937, 78.9629],
        zoom_start=5,
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        attr='&copy; <a href="https://carto.com/">CARTO</a>'
    )

    # Add Mouse Position Coordinate Tracker
    MousePosition().add_to(m)

    # Create mapping dictionary of registered tile keys
    registered_tiles = {}
    for meta in metadata_list:
        b = meta['bounds']
        if b['min_lng'] and b['min_lat']:
            key = f"{int(b['min_lng'])}E_{int(b['min_lat'])}N"
            registered_tiles[key] = meta

    # Generate 1° x 1° India Grid (6°N to 38°N, 68°E to 98°E)
    grid_group = folium.FeatureGroup(name="1° Grid Overlay")

    for lat in range(6, 38):
        for lng in range(68, 98):
            block_key = f"{lng}E_{lat}N"
            bounds = [[lat, lng], [lat + 1, lng + 1]]

            # Check if this grid block has attached XML metadata
            if block_key in registered_tiles:
                meta = registered_tiles[block_key]
                popup_content = f"""
                <div style="font-family: Arial; width: 220px;">
                    <h4 style="margin:0; color:#2563eb;">Tile: {block_key}</h4>
                    <p style="margin: 4px 0; font-size: 11px; color:#555;"><b>Dataset:</b> {meta['dataset_name']}</p>
                    <p style="margin: 2px 0; font-size: 11px;"><b>Theme:</b> {meta['theme']}</p>
                    <p style="margin: 2px 0; font-size: 11px;"><b>Satellite:</b> {meta['satellite']}</p>
                    <p style="margin: 2px 0; font-size: 11px;"><b>Resolution:</b> {meta['resolution']}</p>
                </div>
                """
                folium.Rectangle(
                    bounds=bounds,
                    color="#10b981",
                    weight=2,
                    fill=True,
                    fill_color="#10b981",
                    fill_opacity=0.4,
                    popup=folium.Popup(popup_content, max_width=250),
                    tooltip=f"Tile {block_key} - {meta['dataset_name']}"
                ).add_to(grid_group)
            else:
                folium.Rectangle(
                    bounds=bounds,
                    color="#475569",
                    weight=0.5,
                    fill=True,
                    fill_color="#475569",
                    fill_opacity=0.05,
                    tooltip=f"Tile Block: {block_key}"
                ).add_to(grid_group)

    grid_group.add_to(m)
    folium.LayerControl().add_to(m)

    # Save to standalone HTML file
    output_filename = "india_spatial_grid.html"
    m.save(output_filename)
    print(f"✅ Interactive map generated successfully: '{output_filename}'")

# --- EXECUTION ---
if __name__ == "__main__":
    # Example: Parse the uploaded Bhuvan XML file
    xml_file = "cdne43g.xml"  # Make sure cdne43g.xml is in the same folder
    
    try:
        parsed_meta = parse_bhuvan_xml(xml_file)
        print("Parsed XML Attributes:")
        print(parsed_meta)
        
        # Build the map with the loaded metadata
        build_spatial_map([parsed_meta])
    except FileNotFoundError:
        print(f"XML file '{xml_file}' not found. Generating default grid map...")
        build_spatial_map([])
