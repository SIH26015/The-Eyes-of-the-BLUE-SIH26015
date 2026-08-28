import json
from pathlib import Path
from typing import Dict, Any, List


def build_destination(metadata: Dict[str, Any], base_dir: str, dataset_id: int = None) -> Path:
    theme = metadata.get("theme", "unknown")
    dataset_type = metadata.get("dataset_type", "unknown")
    tile = metadata.get("tile", "unknown")
    version = metadata.get("version", "V1")

    is_unknown = theme == "unknown" or dataset_type == "unknown" or tile == "unknown" or version == "UNKNOWN"
    if is_unknown and dataset_id is not None:
        destination = Path(base_dir) / "data" / "raw" / "unknown" / str(dataset_id)
    else:
        destination = Path(base_dir) / "data" / "raw" / theme / dataset_type / tile / version
        base_dest = destination
        counter = 2
        while destination.exists() and any(destination.iterdir()):
            destination = Path(f"{base_dest}_{counter}")
            counter += 1

    return destination


def organize_files(files: list, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for file in files:
        file = Path(file)
        if file.is_file():
            target = destination / file.name
            if target.exists():
                base = target.stem
                suffix = target.suffix
                i = 2
                while target.exists():
                    target = destination / f"{base}_{i}{suffix}"
                    i += 1
            file.rename(target)


def generate_manifest(destination: Path, metadata: Dict[str, Any], dataset_id: int, original_filename: str, status: str, file_inventory: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    if file_inventory is None:
        file_inventory = []
        for file_path in sorted(destination.iterdir()):
            if file_path.is_file() and file_path.name != "manifest.json":
                ext = file_path.suffix.lower()
                if ext in {".tif", ".tiff"}:
                    file_type = "GeoTIFF"
                elif ext == ".xml":
                    file_type = "XML"
                elif ext == ".shp":
                    file_type = "Shapefile"
                elif ext in {".json", ".geojson"}:
                    file_type = "GeoJSON"
                elif ext == ".csv":
                    file_type = "CSV"
                else:
                    file_type = ext.upper().lstrip(".")
                file_inventory.append({
                    "name": file_path.name,
                    "type": file_type,
                    "role": _infer_role(file_path.name, file_type),
                })

    bounds = None
    bounds_obj = metadata.get("bounds")
    if isinstance(bounds_obj, dict):
        bounds = {
            "west": bounds_obj.get("west"),
            "south": bounds_obj.get("south"),
            "east": bounds_obj.get("east"),
            "north": bounds_obj.get("north"),
            "source": bounds_obj.get("source"),
            "confidence": metadata.get("bounds_confidence"),
            "crs": bounds_obj.get("crs"),
        }
    elif metadata.get("min_lon") is not None and metadata.get("max_lon") is not None and metadata.get("min_lat") is not None and metadata.get("max_lat") is not None:
        bounds = {
            "west": metadata["min_lon"],
            "south": metadata["min_lat"],
            "east": metadata["max_lon"],
            "north": metadata["max_lat"],
        }

    spatial_metadata = {
        "bounds": bounds,
        "resolution": metadata.get("resolution"),
        "format": metadata.get("format"),
        "crs": metadata.get("crs"),
    }
    if metadata.get("spatial_consistency"):
        spatial_metadata["consistency"] = metadata["spatial_consistency"]
    if metadata.get("spatial_note"):
        spatial_metadata["note"] = metadata["spatial_note"]

    manifest = {
        "dataset_id": dataset_id,
        "dataset_name": metadata.get("dataset_name"),
        "dataset_type": metadata.get("dataset_type", "UNKNOWN"),
        "theme": metadata.get("theme", "unknown"),
        "tile": metadata.get("tile", "UNKNOWN"),
        "version": metadata.get("version", "UNKNOWN"),
        "status": status,
        "source": metadata.get("source"),
        "platform": metadata.get("satellite"),
        "sensor": metadata.get("sensor"),
        "bits_per_pixel": metadata.get("bits_per_pixel"),
        "files": file_inventory,
        "spatial_metadata": spatial_metadata,
        "ingested_at": metadata.get("ingested_at"),
        "original_filename": original_filename,
        "classification": metadata.get("classification"),
        "metadata_provenance": {
            key: {
                "value": metadata.get(key),
                "source": metadata.get(f"{key}_source", "unknown"),
                "confidence": metadata.get(f"{key}_confidence", "UNKNOWN"),
            }
            for key in ["tile", "version", "dataset_type", "theme", "dataset_name"]
        },
        "quality": metadata.get("quality"),
    }
    return manifest


def write_manifest(destination: Path, manifest: Dict[str, Any]) -> None:
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))


def _infer_role(filename: str, file_type: str) -> str:
    name_lower = filename.lower()
    if file_type == "XML" and ("meta" in name_lower or name_lower.endswith(".xml")):
        return "metadata"
    if file_type == "GeoTIFF":
        return "primary"
    if file_type in {"Shapefile", "GeoJSON", "CSV"}:
        return "primary"
    if "readme" in name_lower or "license" in name_lower or "policy" in name_lower:
        return "documentation"
    if file_type == "IMAGE":
        return "preview"
    return "supporting"
