from typing import Dict, Any, Optional


def calculate_overlap(bounds_a: Dict[str, float], bounds_b: Dict[str, float]) -> Dict[str, float]:
    west = max(bounds_a["west"], bounds_b["west"])
    south = max(bounds_a["south"], bounds_b["south"])
    east = min(bounds_a["east"], bounds_b["east"])
    north = min(bounds_a["north"], bounds_b["north"])

    if west >= east or south >= north:
        return {"overlap": False, "west": west, "south": south, "east": east, "north": north, "area": 0.0}

    overlap_area = (east - west) * (north - south)
    return {"overlap": True, "west": west, "south": south, "east": east, "north": north, "area": overlap_area}


def calculate_coverage_percentage(dataset_bounds: Dict[str, float], query_bounds: Dict[str, float]) -> float:
    overlap = calculate_overlap(dataset_bounds, query_bounds)
    if not overlap["overlap"]:
        return 0.0

    query_area = (query_bounds["east"] - query_bounds["west"]) * (query_bounds["north"] - query_bounds["south"])
    if query_area <= 0:
        return 0.0

    coverage = (overlap["area"] / query_area) * 100
    return round(min(100.0, max(0.0, coverage)), 2)


def get_spatial_relation(dataset_bounds: Dict[str, float], query_bounds: Dict[str, float]) -> str:
    overlap = calculate_overlap(dataset_bounds, query_bounds)
    if not overlap["overlap"]:
        return "none"

    coverage = calculate_coverage_percentage(dataset_bounds, query_bounds)
    if coverage >= 99.0:
        return "full_coverage"
    elif coverage > 0:
        return "partial_overlap"
    return "none"


def check_crs_compatibility(crs_a: Optional[str], crs_b: Optional[str]) -> Dict[str, Any]:
    if not crs_a or not crs_b:
        return {"compatible": True, "warnings": ["CRS information missing for one or both datasets"]}

    if crs_a == crs_b:
        return {"compatible": True, "warnings": []}

    return {
        "compatible": False,
        "warnings": [f"CRS mismatch: {crs_a} vs {crs_b}"],
    }


def check_resolution_compatibility(res_a: Optional[str], res_b: Optional[str]) -> Dict[str, Any]:
    if not res_a or not res_b:
        return {"compatible": True, "warnings": ["Resolution information missing"]}

    if res_a == res_b:
        return {"compatible": True, "warnings": []}

    return {
        "compatible": True,
        "warnings": [f"Different resolutions: {res_a} vs {res_b}"],
    }
