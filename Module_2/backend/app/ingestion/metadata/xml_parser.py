import xml.etree.ElementTree as ET
import re
from pathlib import Path
from typing import Optional, Dict, Any


def _parse_coordinate(coord_str: str) -> Optional[float]:
    if not coord_str:
        return None
    match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", coord_str.replace(",", ""))
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def _parse_point(text: str) -> tuple:
    x = None
    y = None
    if not text:
        return x, y
    x_match = re.search(r"X\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", text)
    y_match = re.search(r"Y\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", text)
    if x_match:
        try:
            x = float(x_match.group(1))
        except ValueError:
            pass
    if y_match:
        try:
            y = float(y_match.group(1))
        except ValueError:
            pass
    return x, y


def _parse_coverage(root: ET.Element) -> Dict[str, Optional[float]]:
    coverage = {"min_lon": None, "max_lon": None, "min_lat": None, "max_lat": None}
    coverage_elem = root.find("Coverage")
    if coverage_elem is None:
        coverage_elem = root.find("coverage")
    if coverage_elem is None:
        return coverage

    def _get_point(tag: str):
        elem = coverage_elem.find(tag)
        if elem is None or elem.text is None:
            return None, None
        return _parse_point(elem.text)

    ul_x, ul_y = _get_point("Upper_left")
    ur_x, ur_y = _get_point("Upper_right")
    lr_x, lr_y = _get_point("Lower_right")
    ll_x, ll_y = _get_point("Lower_left")

    lons = [v for v in [ul_x, ur_x, lr_x, ll_x] if v is not None]
    lats = [v for v in [ul_y, ur_y, lr_y, ll_y] if v is not None]

    if lons:
        coverage["min_lon"] = min(lons)
        coverage["max_lon"] = max(lons)
    if lats:
        coverage["min_lat"] = min(lats)
        coverage["max_lat"] = max(lats)

    return coverage


def _extract_text(parent: ET.Element, tag: str) -> Optional[str]:
    elem = parent.find(tag)
    if elem is not None and elem.text:
        return elem.text.strip()
    for descendant in parent.iter(tag):
        if descendant is not None and descendant.text:
            return descendant.text.strip()
    return None


def _normalize_theme(theme: Optional[str]) -> Optional[str]:
    if not theme:
        return None
    theme_lower = theme.strip().lower()
    mapping = {
        "terrain": "terrain",
        "satellite": "satellite",
        "landcover": "landcover",
        "land cover": "landcover",
        "land use": "landcover",
        "vector": "vector",
        "unknown": "unknown",
    }
    return mapping.get(theme_lower, theme_lower)


def _normalize_version(version: Optional[str]) -> Optional[str]:
    if not version:
        return None
    match = re.search(r"v(\d+)", version, re.IGNORECASE)
    if match:
        return f"V{match.group(1)}"
    return None


def _extract_version_from_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    match = re.search(r"_v(\d+)_", name, re.IGNORECASE)
    if match:
        return f"V{match.group(1)}"
    return None


def _normalize_tile(tile: Optional[str]) -> Optional[str]:
    if not tile:
        return None
    tile_clean = tile.strip().upper()
    if not re.match(r"^[A-Z]\d{2}[A-Z]$", tile_clean):
        return None
    return tile_clean


def _infer_dataset_type(xml_meta: Dict[str, Any]) -> Optional[str]:
    keywords = (xml_meta.get("keywords") or "").upper()
    data_type = (xml_meta.get("data_type") or "").upper()
    topic = (xml_meta.get("topic_category") or "").upper()
    dataset_name = (xml_meta.get("dataset_name") or "").upper()

    if "DEM" in keywords or "DIGITAL ELEVATION" in data_type or "DIGITAL ELEVATION" in topic or "DEM" in dataset_name:
        return "DEM"
    if "DSM" in keywords or "DIGITAL SURFACE" in data_type or "DIGITAL SURFACE" in topic or "DSM" in dataset_name:
        return "DSM"
    if "LULC" in keywords or "LAND USE" in keywords or "LAND COVER" in keywords or "LULC" in dataset_name:
        return "LULC"
    if "VECTOR" in keywords:
        return "VECTOR"
    return None


def parse_bhuvan_xml(xml_file: Path) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "dataset_name": None,
        "dataset_type": None,
        "theme": None,
        "tile": None,
        "version": None,
        "min_lon": None,
        "max_lon": None,
        "min_lat": None,
        "max_lat": None,
        "resolution": None,
        "format": None,
        "source": None,
        "satellite": None,
        "sensor": None,
        "number_of_bands": None,
        "bits_per_pixel": None,
        "data_type": None,
        "topic_category": None,
        "keywords": None,
    }

    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
    except Exception:
        return metadata

    tileno = root.attrib.get("tileno")
    if tileno:
        metadata["tile"] = _normalize_tile(tileno)

    metadata["dataset_name"] = _extract_text(root, "Name_of_the_Dataset")
    metadata["keywords"] = _extract_text(root, "Keywords")
    metadata["data_type"] = _extract_text(root, "Data_Type")
    metadata["topic_category"] = _extract_text(root, "Data_Identification_topic_category")
    metadata["theme"] = _normalize_theme(_extract_text(root, "Theme"))

    if metadata.get("tile") is None:
        tile_elem = root.find(".//Tile_Name")
        if tile_elem is not None and tile_elem.text:
            metadata["tile"] = _normalize_tile(tile_elem.text.strip())

    if metadata.get("version") is None and metadata.get("dataset_name"):
        metadata["version"] = _extract_version_from_name(metadata["dataset_name"])

    coverage = _parse_coverage(root)
    if coverage.get("min_lon") is not None:
        metadata["min_lon"] = coverage["min_lon"]
        metadata["max_lon"] = coverage["max_lon"]
        metadata["min_lat"] = coverage["min_lat"]
        metadata["max_lat"] = coverage["max_lat"]

    res = _extract_text(root, "Resolution")
    if res:
        metadata["resolution"] = res

    fmt = _extract_text(root, "File_Format")
    if fmt:
        metadata["format"] = fmt

    fid = root.find("For_Image_Data")
    if fid is not None:
        metadata["satellite"] = _extract_text(fid, "Name_of_the_Satellite")
        metadata["sensor"] = _extract_text(fid, "Sensor")
        spatial_res = _extract_text(fid, "Spatial_Resolution")
        if spatial_res:
            metadata["resolution"] = spatial_res
        bands = _extract_text(fid, "Number_of_Bands")
        if bands:
            try:
                metadata["number_of_bands"] = int(bands)
            except ValueError:
                metadata["number_of_bands"] = bands
        bpp = _extract_text(fid, "Bits_per_Pixel")
        if bpp:
            metadata["bits_per_pixel"] = bpp

    metadata["source"] = _extract_text(root, "Original_Source")

    if not metadata["source"]:
        parts = []
        keywords = _extract_text(root, "Keywords") or ""
        if "bhuvan" in keywords.lower() or "isro" in keywords.lower() or "nrsc" in keywords.lower():
            parts.append("Bhuvan")
        if "nrsc" in keywords.lower():
            parts.append("NRSC")
        if "isro" in keywords.lower():
            parts.append("ISRO")
        if parts:
            metadata["source"] = " / ".join(parts)

    metadata["dataset_type"] = _infer_dataset_type(metadata)

    return metadata


def parse_xml(xml_file: Path) -> Dict[str, Any]:
    xml_file = Path(xml_file)
    if not xml_file.exists() or not xml_file.is_file():
        return {}

    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        text = ET.tostring(root, encoding="unicode")
    except Exception:
        return {}

    metadata = parse_bhuvan_xml(xml_file)

    if metadata.get("dataset_type") is None:
        tag_text = text.lower()
        if "dem" in tag_text or "digital elevation" in tag_text:
            metadata["dataset_type"] = "DEM"
        elif "dsm" in tag_text or "digital surface" in tag_text:
            metadata["dataset_type"] = "DSM"
        elif "lulc" in tag_text or "land use" in tag_text or "land cover" in tag_text:
            metadata["dataset_type"] = "LULC"
        elif "vector" in tag_text:
            metadata["dataset_type"] = "VECTOR"
        else:
            metadata["dataset_type"] = "UNKNOWN"

    return {k: v for k, v in metadata.items() if v is not None and not k.startswith("_")}
