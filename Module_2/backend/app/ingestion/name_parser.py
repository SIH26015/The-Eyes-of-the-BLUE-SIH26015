import re
from typing import Dict, Any, Optional


_KNOWN_TILES = {
    "F43U", "F44U", "F45U", "F46U", "F47U", "F48U", "F49U", "F50U",
    "F51U", "F52U", "F53U", "F54U", "F55U", "F56U", "F57U", "F58U",
    "E43G", "E44G", "E45G", "E46G", "E47G", "E48G", "E49G", "E50G",
    "D43H", "D44H", "D45H", "D46H", "D47H", "D48H", "D49H", "D50H",
    "C40B", "C41B", "C42B", "C43B", "C44B", "C45B", "C46B", "C47B",
    "B40A", "B41A", "B42A", "B43A", "B44A", "B45A", "B46A", "B47A",
    "A42N", "A43N", "A44N", "A45N", "A46N", "A47N", "A48N", "A49N",
}


def _extract_tile_from_filename(name: str) -> Optional[str]:
    name_upper = name.upper()
    for tile in _KNOWN_TILES:
        if tile in name_upper:
            return tile
    match = re.search(r"\b([A-E]\d{2}[A-Z])\b", name_upper)
    if match:
        candidate = match.group(1)
        if candidate in _KNOWN_TILES:
            return candidate
    return None


def _extract_version_from_filename(name: str) -> Optional[str]:
    match = re.search(r"V(\d+)", name.upper())
    if match:
        return f"V{match.group(1)}"
    return None


def _infer_type_from_filename(name: str) -> Optional[str]:
    n = name.upper()
    if "DEM" in n:
        return "DEM"
    if "DSM" in n:
        return "DSM"
    if "LULC" in n or "LANDUSE" in n or "LAND_COVER" in n:
        return "LULC"
    return None


def parse_dataset_name(name: str) -> Dict[str, Any]:
    result = {
        "tile": None,
        "version": None,
        "dataset_type": None,
        "source": "filename",
        "confidence": "LOW",
    }

    tile = _extract_tile_from_filename(name)
    version = _extract_version_from_filename(name)
    dtype = _infer_type_from_filename(name)

    result["tile"] = tile
    result["version"] = version
    result["dataset_type"] = dtype

    if tile and version and dtype:
        result["confidence"] = "medium"
    elif tile or version or dtype:
        result["confidence"] = "medium"
    else:
        result["confidence"] = "low"

    return result
