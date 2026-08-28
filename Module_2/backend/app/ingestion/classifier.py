from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from backend.app.ingestion.metadata.xml_parser import parse_xml, parse_bhuvan_xml
from backend.app.ingestion.metadata.geotiff_reader import read_geotiff_metadata
from backend.app.ingestion.name_parser import parse_dataset_name


SUPPORTED_TYPES = {"DEM", "DSM", "LULC", "VECTOR", "BATHYMETRY", "NDVI", "UNKNOWN"}


def _geotiff_type_hint(meta: Dict[str, Any]) -> Optional[str]:
    crs = (meta.get("crs") or "").upper()
    count = meta.get("count")
    dtype = (meta.get("dtype") or "").upper()
    driver = (meta.get("driver") or "").upper()
    if "DEM" in driver or "SRTM" in driver:
        return "DEM"
    return None


def _detect_type_from_xml(xml_metadata: Dict[str, Any]) -> Optional[Tuple[str, List[str]]]:
    evidence: List[str] = []

    xml_type = xml_metadata.get("dataset_type")
    if xml_type and xml_type != "UNKNOWN":
        evidence.append(f"Explicit dataset type: {xml_type}")
        return xml_type, evidence

    topic = (xml_metadata.get("topic_category") or "").lower()
    if "digital elevation" in topic:
        evidence.append("Dataset topic category: Digital Elevation Model")
        return "DEM", evidence
    if "digital surface" in topic:
        evidence.append("Dataset topic category: Digital Surface Model")
        return "DSM", evidence
    if "land cover" in topic or "land use" in topic:
        evidence.append("Dataset topic category: Land Cover/Land Use")
        return "LULC", evidence

    keywords = (xml_metadata.get("keywords") or "").upper()
    if "DEM" in keywords or "DIGITAL ELEVATION" in keywords:
        evidence.append(f"Keyword: {xml_metadata.get('keywords')}")
        return "DEM", evidence
    if "DSM" in keywords or "DIGITAL SURFACE" in keywords:
        evidence.append(f"Keyword: {xml_metadata.get('keywords')}")
        return "DSM", evidence
    if "LULC" in keywords or "LAND USE" in keywords or "LAND COVER" in keywords:
        evidence.append(f"Keyword: {xml_metadata.get('keywords')}")
        return "LULC", evidence
    if "BATHYMETRY" in keywords:
        evidence.append(f"Keyword: {xml_metadata.get('keywords')}")
        return "BATHYMETRY", evidence

    data_type = (xml_metadata.get("data_type") or "").lower()
    if "elevation" in data_type:
        evidence.append(f"Data type: {xml_metadata.get('data_type')}")
        return "DEM", evidence
    if "surface" in data_type:
        evidence.append(f"Data type: {xml_metadata.get('data_type')}")
        return "DSM", evidence

    dataset_name = (xml_metadata.get("dataset_name") or "").upper()
    if "DEM" in dataset_name:
        evidence.append(f"Dataset name: {xml_metadata.get('dataset_name')}")
        return "DEM", evidence
    if "DSM" in dataset_name:
        evidence.append(f"Dataset name: {xml_metadata.get('dataset_name')}")
        return "DSM", evidence
    if "LULC" in dataset_name:
        evidence.append(f"Dataset name: {xml_metadata.get('dataset_name')}")
        return "LULC", evidence
    if "NDVI" in dataset_name:
        evidence.append(f"Dataset name: {xml_metadata.get('dataset_name')}")
        return "NDVI", evidence
    return None, evidence


def classify_dataset(xml_metadata: Dict[str, Any], geotiff_metadata: Dict[str, Any], filename: str) -> Dict[str, Any]:
    evidence: List[str] = []
    stem = Path(filename).stem if filename else ""
    stem_upper = stem.upper()

    xml_type, xml_evidence = _detect_type_from_xml(xml_metadata)
    evidence.extend(xml_evidence)
    if xml_type and xml_type in SUPPORTED_TYPES:
        return {
            "dataset_type": xml_type,
            "confidence": "high",
            "evidence": evidence,
        }

    gt_hint = _geotiff_type_hint(geotiff_metadata)
    if gt_hint:
        evidence.append(f"GeoTIFF driver hint: {geotiff_metadata.get('driver')}")
        return {
            "dataset_type": gt_hint,
            "confidence": "medium",
            "evidence": evidence,
        }

    name_info = parse_dataset_name(stem)
    if name_info.get("dataset_type") and name_info["dataset_type"] in SUPPORTED_TYPES:
        evidence.append(f"Filename pattern: {stem}")
        return {
            "dataset_type": name_info["dataset_type"],
            "confidence": name_info.get("confidence", "low").lower(),
            "evidence": evidence,
        }

    for dtype in ["DEM", "DSM", "LULC", "VECTOR", "BATHYMETRY", "NDVI"]:
        if dtype in stem_upper:
            evidence.append(f"Filename substring: {dtype}")
            return {
                "dataset_type": dtype,
                "confidence": "medium",
                "evidence": evidence,
            }

    dataset_name = (xml_metadata.get("dataset_name") or "").upper()
    for dtype in ["DEM", "DSM", "LULC", "VECTOR", "BATHYMETRY", "NDVI"]:
        if dtype in dataset_name:
            evidence.append(f"Dataset name substring: {dtype}")
            return {
                "dataset_type": dtype,
                "confidence": "medium",
                "evidence": evidence,
            }

    return {
        "dataset_type": "UNKNOWN",
        "confidence": "low",
        "evidence": ["No strong metadata signals found"],
    }
