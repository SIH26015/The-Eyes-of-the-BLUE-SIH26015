import zipfile
from pathlib import Path
from typing import Dict, Any, List

from backend.app.ingestion.metadata.xml_parser import parse_xml
from backend.app.ingestion.metadata.geotiff_reader import read_geotiff_metadata
from backend.app.ingestion.inspector import inspect_dataset


SUPPORTED_TYPES = {"DEM", "DSM", "LULC", "VECTOR", "UNKNOWN"}


def validate_upload(file_path: str) -> Dict[str, Any]:
    file_path = Path(file_path)
    result = {
        "valid": False,
        "file_path": str(file_path),
        "reason": None,
        "error_reason": None,
        "warnings": [],
    }

    if not file_path.exists():
        result["reason"] = "File not found"
        result["error_reason"] = "MISSING_FILE"
        return result

    if file_path.suffix.lower() == ".zip":
        if not zipfile.is_zipfile(file_path):
            result["reason"] = "Invalid or corrupted ZIP archive"
            result["error_reason"] = "CORRUPTED_ARCHIVE"
            return result
        result["valid"] = True
        return result

    return result


def validate_dataset(extract_dir: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "valid": False,
        "error_reason": None,
        "reason": None,
        "warnings": [],
    }

    if manifest.get("supported_files", 0) == 0:
        result["reason"] = "No supported data files found"
        result["error_reason"] = "NO_SUPPORTED_DATA_FILE"
        return result

    for tif in manifest.get("primary_files", []):
        if tif.suffix.lower() in {".tif", ".tiff"}:
            gt = read_geotiff_metadata(tif)
            if gt.get("_error") == "invalid_geotiff":
                result["reason"] = f"Unreadable GeoTIFF: {tif.name}"
                result["error_reason"] = "INVALID_GEOTIFF"
                return result

    for xml in manifest.get("xml_files", []):
        try:
            import xml.etree.ElementTree as ET
            ET.parse(xml)
        except Exception:
            result["reason"] = f"Unparseable XML: {xml.name}"
            result["error_reason"] = "INVALID_XML"
            return result

    if not manifest.get("xml_files") and not manifest.get("primary_files"):
        result["reason"] = "Insufficient metadata or data files"
        result["error_reason"] = "INSUFFICIENT_METADATA"
        return result

    result["valid"] = True
    return result
