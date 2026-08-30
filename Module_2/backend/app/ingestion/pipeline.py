import hashlib
import json
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional
import shutil

from backend.app.ingestion.parser.xml_parser import parse_xml
from backend.app.ingestion.parser.geotiff_reader import read_geotiff_metadata
from backend.app.ingestion.inspector import inspect_dataset
from backend.app.ingestion.classifier import classify_dataset
from backend.app.ingestion.validator import validate_upload, validate_dataset
from backend.app.ingestion.duplicates import is_exact_duplicate
from backend.app.ingestion.organizer import build_destination, organize_files, generate_manifest, write_manifest
from backend.app.ingestion.catalog import (
    insert_dataset, update_status, update_dataset, init_db,
    insert_dataset_file, start_ingestion_run, complete_ingestion_run,
    get_dataset_files, get_dataset, record_metadata_history,
    get_conn,
)
from backend.app.ingestion.name_parser import parse_dataset_name
from backend.app.ingestion.parser.resolver import MetadataResolver


def _file_hash(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_size(file_path: Path) -> int:
    return file_path.stat().st_size


def extract_if_archive(file_path: Path, processing_dir: Path) -> Optional[Path]:
    if file_path.suffix.lower() != ".zip":
        return None
    extract_folder = processing_dir / file_path.stem
    extract_folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(file_path, "r") as zf:
        zf.extractall(extract_folder)
    return extract_folder


def _build_merged_metadata(xml_meta: Dict[str, Any], gtiff_meta: Dict[str, Any], filename: str) -> Dict[str, Any]:
    resolver = MetadataResolver()

    xml_fields = [
        "dataset_name", "dataset_type", "theme", "tile", "version",
        "min_lon", "max_lon", "min_lat", "max_lat",
        "resolution", "format", "source", "satellite", "sensor",
        "number_of_bands", "bits_per_pixel",
    ]
    for field in xml_fields:
        value = xml_meta.get(field)
        if value is not None and value != "UNKNOWN":
            evidence = f"xml.{field}"
            if field == "tile" and xml_meta.get("_tile_source"):
                evidence = f"xml.Citation.Lineage.Tile_Name"
            elif field == "version" and xml_meta.get("dataset_name"):
                evidence = f"xml.dataset_name:{xml_meta['dataset_name']}"
            resolver.set(field, value, "xml", "high", evidence)

    gtiff_fields = [
        "crs", "bounds", "width", "height", "count", "dtype", "driver",
    ]
    for field in gtiff_fields:
        value = gtiff_meta.get(field)
        if value is not None:
            resolver.set(field, value, "geotiff", "high", f"geotiff.{field}")

    name_info = parse_dataset_name(filename)
    for field in ["tile", "version", "dataset_type"]:
        value = name_info.get(field)
        if value and not resolver.get(field):
            resolver.set(field, value, "filename", name_info.get("confidence", "low").lower(), f"filename:{filename}")

    dataset_name = xml_meta.get("dataset_name")
    if dataset_name:
        name_info_xml = parse_dataset_name(dataset_name)
        for field in ["tile", "version", "dataset_type"]:
            value = name_info_xml.get(field)
            if value and not resolver.get(field):
                resolver.set(field, value, "xml", "high", f"xml.dataset_name:{dataset_name}")

    for field in ["tile", "version", "dataset_type", "theme", "dataset_name"]:
        if resolver.get(field) is None:
            if field == "theme":
                resolver.set(field, "unknown", "unknown", "unknown")
            elif field == "tile":
                resolver.set(field, "UNKNOWN", "unknown", "unknown")
            elif field == "version":
                resolver.set(field, "UNKNOWN", "unknown", "unknown")
            elif field == "dataset_type":
                resolver.set(field, "UNKNOWN", "unknown", "unknown")

    return resolver.to_flat()


def _resolve_spatial_bounds(merged: Dict[str, Any], gtiff_meta: Dict[str, Any]) -> None:
    xml_bounds = None
    if all(merged.get(k) is not None for k in ["min_lon", "max_lon", "min_lat", "max_lat"]):
        xml_bounds = {
            "west": float(merged["min_lon"]),
            "south": float(merged["min_lat"]),
            "east": float(merged["max_lon"]),
            "north": float(merged["max_lat"]),
            "source": "xml",
        }

    gtiff_bounds = gtiff_meta.get("bounds")
    if isinstance(gtiff_bounds, (list, tuple)) and len(gtiff_bounds) == 4:
        gtiff_bounds = {
            "west": float(gtiff_bounds[0]),
            "south": float(gtiff_bounds[1]),
            "east": float(gtiff_bounds[2]),
            "north": float(gtiff_bounds[3]),
            "source": "geotiff",
        }

    if not xml_bounds and not gtiff_bounds:
        return

    if xml_bounds and not gtiff_bounds:
        merged["bounds"] = xml_bounds
        merged["bounds_confidence"] = "medium"
        merged["metadata_coverage"] = xml_bounds
        return

    if not xml_bounds and gtiff_bounds:
        merged["bounds"] = gtiff_bounds
        merged["bounds_confidence"] = "high"
        return

    xml_span_lon = xml_bounds["east"] - xml_bounds["west"]
    xml_span_lat = xml_bounds["north"] - xml_bounds["south"]
    gtiff_span_lon = gtiff_bounds["east"] - gtiff_bounds["west"]
    gtiff_span_lat = gtiff_bounds["north"] - gtiff_bounds["south"]

    xml_center_lon = (xml_bounds["west"] + xml_bounds["east"]) / 2
    xml_center_lat = (xml_bounds["south"] + xml_bounds["north"]) / 2
    gtiff_center_lon = (gtiff_bounds["west"] + gtiff_bounds["east"]) / 2
    gtiff_center_lat = (gtiff_bounds["south"] + gtiff_bounds["north"]) / 2

    center_distance = ((xml_center_lon - gtiff_center_lon) ** 2 + (xml_center_lat - gtiff_center_lat) ** 2) ** 0.5
    span_diff = abs(xml_span_lon - gtiff_span_lon) + abs(xml_span_lat - gtiff_span_lat)

    if center_distance < 0.01 and span_diff < 0.01:
        merged["bounds"] = xml_bounds
        merged["bounds_confidence"] = "high"
        merged["spatial_consistency"] = "consistent"
        merged["metadata_coverage"] = xml_bounds
    elif center_distance < 1.0 and span_diff < 1.0:
        merged["bounds"] = xml_bounds
        merged["bounds_confidence"] = "medium"
        merged["spatial_consistency"] = "consistent"
        merged["metadata_coverage"] = xml_bounds
    else:
        merged["bounds"] = gtiff_bounds
        merged["bounds_confidence"] = "high"
        merged["spatial_consistency"] = "conflict"
        merged["metadata_coverage"] = xml_bounds
        merged["spatial_note"] = "XML coverage differs from GeoTIFF extent; GeoTIFF bounds used"


def _build_file_inventory(dataset_id: int, extract_dir: Path, manifest: Dict[str, Any], base_dir: str) -> List[Dict[str, Any]]:
    files = []
    manifest_files = {f["name"]: f for f in manifest.get("files", [])}

    for file_path in sorted(extract_dir.rglob("*")):
        if not file_path.is_file() or file_path.name == "manifest.json":
            continue
        name = file_path.name
        ext = file_path.suffix.lower()
        file_type = "OTHER"
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
        elif ext in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            file_type = "IMAGE"
        elif ext in {".txt", ".pdf"}:
            file_type = "DOCUMENT"

        role = "unknown"
        if file_type == "GeoTIFF":
            role = "primary"
        elif file_type == "XML":
            role = "metadata"
        elif file_type == "Shapefile":
            role = "primary"
        elif file_type in {"GeoJSON", "CSV"}:
            role = "primary"
        elif file_type == "DOCUMENT":
            role = "documentation"
        elif file_type == "IMAGE":
            role = "preview"

        mf = manifest_files.get(name, {})
        if mf.get("role"):
            role = mf["role"]

        file_hash = _file_hash(file_path) if file_path.exists() else None
        file_size = _file_size(file_path) if file_path.exists() else None

        file_meta = {
            "relative_path": str(file_path.relative_to(extract_dir)),
            "file_name": name,
            "extension": ext,
            "file_role": role,
            "file_size": file_size,
            "file_hash": file_hash,
            "format": file_type,
            "spatial": file_type in {"GeoTIFF", "Shapefile", "GeoJSON", "CSV"},
        }

        if file_type == "GeoTIFF":
            gtiff_meta = read_geotiff_metadata(file_path)
            if not gtiff_meta.get("_error"):
                file_meta.update({
                    "crs": gtiff_meta.get("crs"),
                    "min_lon": gtiff_meta.get("bounds", (None, None, None, None))[0] if gtiff_meta.get("bounds") else None,
                    "min_lat": gtiff_meta.get("bounds", (None, None, None, None))[1] if gtiff_meta.get("bounds") else None,
                    "max_lon": gtiff_meta.get("bounds", (None, None, None, None))[2] if gtiff_meta.get("bounds") else None,
                    "max_lat": gtiff_meta.get("bounds", (None, None, None, None))[3] if gtiff_meta.get("bounds") else None,
                    "width": gtiff_meta.get("width"),
                    "height": gtiff_meta.get("height"),
                    "count": gtiff_meta.get("count"),
                    "dtype": gtiff_meta.get("dtype"),
                })

        insert_dataset_file(base_dir, dataset_id, file_meta)
        files.append(file_meta)

    return files


def _compute_dataset_bounds_from_files(base_dir: str, dataset_id: int) -> Dict[str, Any]:
    files = get_dataset_files(base_dir, dataset_id)
    spatial_files = [f for f in files if f.get("spatial") and f.get("min_lon") is not None]
    if not spatial_files:
        return {}

    west = min(f["min_lon"] for f in spatial_files)
    south = min(f["min_lat"] for f in spatial_files)
    east = max(f["max_lon"] for f in spatial_files)
    north = max(f["max_lat"] for f in spatial_files)

    crs_set = {f.get("crs") for f in spatial_files if f.get("crs")}
    crs = crs_set.pop() if crs_set else None

    return {
        "west": west,
        "south": south,
        "east": east,
        "north": north,
        "source": "file_union",
        "crs": crs,
    }


def _build_quality_report(merged: Dict[str, Any], file_inventory: List[Dict[str, Any]], classification: Dict[str, Any]) -> Dict[str, Any]:
    important_fields = ["dataset_name", "dataset_type", "theme", "tile", "version", "source", "platform", "sensor"]
    missing_fields = []
    manual_fields = []
    conflicts = []

    for field in important_fields:
        value = merged.get(field)
        source = merged.get(f"{field}_source", "unknown")
        if not value or value in ("unknown", "UNKNOWN", None):
            missing_fields.append(field)
        if source == "manual":
            manual_fields.append(field)

    spatial_files = [f for f in file_inventory if f.get("spatial")]
    primary_files = [f for f in file_inventory if f.get("file_role") == "primary"]
    metadata_files = [f for f in file_inventory if f.get("file_role") == "metadata"]
    unknown_files = [f for f in file_inventory if f.get("file_role") == "unknown"]

    total = len(important_fields)
    filled = total - len(missing_fields)
    score = int((filled / total) * 100) if total > 0 else 0

    if classification.get("confidence") == "high":
        score = min(100, score + 10)
    elif classification.get("confidence") == "medium":
        score = min(100, score + 5)

    return {
        "score": score,
        "missing_fields": missing_fields,
        "manual_fields": manual_fields,
        "conflicts": conflicts,
        "spatial_quality": {
            "has_bounds": merged.get("bounds") is not None,
            "has_crs": any(f.get("crs") for f in spatial_files),
            "spatial_files": len(spatial_files),
        },
        "file_quality": {
            "total_files": len(file_inventory),
            "primary_files": len(primary_files),
            "metadata_files": len(metadata_files),
            "unknown_files": len(unknown_files),
        },
        "classification": classification,
    }


def reprocess_dataset(base_dir: str, dataset_id: int, parser_version: str = "1.0") -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []
    base_dir = str(Path(base_dir).resolve())

    ds = get_dataset(base_dir, dataset_id)
    if not ds:
        return {"status": "error", "error": "Dataset not found", "dataset_id": dataset_id}

    current_path = Path(ds.get("file_path", ""))
    dataset_dir = Path(base_dir) / current_path
    if not dataset_dir.exists():
        return {"status": "error", "error": "Dataset directory not found", "dataset_id": dataset_id}

    manifest_path = dataset_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception:
            pass

    steps.append({"step": "Loaded existing dataset", "status": "complete", "detail": f"ID {dataset_id}"})

    xml_files = list(dataset_dir.rglob("*.xml"))
    xml_meta: Dict[str, Any] = {}
    if xml_files:
        xml_meta = parse_xml(xml_files[0])
        steps.append({"step": f"XML parsed: {xml_files[0].name}", "status": "done"})
    else:
        steps.append({"step": "No XML metadata found", "status": "warning"})

    gtiff_meta: Dict[str, Any] = {}
    for primary in manifest.get("files", []):
        if primary.get("type") == "GeoTIFF":
            gtiff_path = dataset_dir / primary.get("name", "")
            if gtiff_path.exists():
                gtiff_meta = read_geotiff_metadata(gtiff_path)
                if gtiff_meta.get("_error"):
                    steps.append({"step": f"GeoTIFF unreadable: {primary.get('name')}", "status": "error"})
                else:
                    steps.append({"step": f"GeoTIFF metadata read: {primary.get('name')}", "status": "done"})
            break

    merged = _build_merged_metadata(xml_meta, gtiff_meta, ds.get("original_filename", ""))
    if not merged.get("dataset_name"):
        merged["dataset_name"] = ds.get("dataset_name")

    _resolve_spatial_bounds(merged, gtiff_meta)

    classification = classify_dataset(xml_meta, gtiff_meta, ds.get("original_filename", ""))
    dataset_type = classification.get("dataset_type", "UNKNOWN")
    confidence = classification.get("confidence", "low")
    evidence = classification.get("evidence", [])
    merged["dataset_type"] = dataset_type
    merged["confidence"] = confidence
    merged["classification_evidence"] = evidence
    steps.append({"step": f"Classified as {dataset_type} ({confidence} confidence)", "status": "done"})

    for key in ["theme", "tile", "version", "dataset_name"]:
        if key not in merged or merged[key] is None:
            if key == "theme":
                merged[key] = ds.get("theme", "unknown")
            elif key == "tile":
                merged[key] = ds.get("tile", "UNKNOWN")
            elif key == "version":
                merged[key] = ds.get("version", "UNKNOWN")
            elif key == "dataset_name":
                merged[key] = ds.get("dataset_name")

    if merged.get("theme") == "unknown" and merged.get("dataset_type") not in (None, "UNKNOWN"):
        theme_map = {
            "DEM": "terrain",
            "DSM": "terrain",
            "LULC": "landcover",
            "VECTOR": "vector",
            "BATHYMETRY": "terrain",
        }
        inferred_theme = theme_map.get(merged["dataset_type"])
        if inferred_theme:
            merged["theme"] = inferred_theme
            merged["theme_source"] = "inference"
            merged["theme_confidence"] = "medium"

    is_unknown = (
        merged.get("theme") == "unknown"
        or merged.get("dataset_type") == "UNKNOWN"
        or merged.get("tile") == "UNKNOWN"
        or merged.get("version") == "UNKNOWN"
    )
    status = "NEEDS_REVIEW" if is_unknown else "READY"

    old_destination = dataset_dir
    new_destination = build_destination(merged, base_dir, dataset_id=dataset_id)

    if old_destination.exists() and old_destination != new_destination:
        if new_destination.exists() and any(new_destination.iterdir()):
            new_destination = build_destination(merged, base_dir, dataset_id=f"{dataset_id}_reprocess")
        try:
            new_destination.mkdir(parents=True, exist_ok=True)
            for item in old_destination.iterdir():
                target = new_destination / item.name
                if target.exists():
                    base = target.stem
                    suffix = target.suffix
                    i = 2
                    while target.exists():
                        target = new_destination / f"{base}_{i}{suffix}"
                        i += 1
                shutil.move(str(item), str(target))
            shutil.rmtree(old_destination)
            steps.append({"step": f"Moved to {new_destination.relative_to(Path(base_dir))}", "status": "done"})
        except Exception as e:
            return {"status": "error", "error": f"Move failed: {str(e)}", "dataset_id": dataset_id}
    else:
        new_destination = old_destination

    rel_path = new_destination.relative_to(Path(base_dir))
    record = {
        "dataset_name": merged.get("dataset_name"),
        "dataset_type": merged.get("dataset_type"),
        "theme": merged.get("theme"),
        "tile": merged.get("tile"),
        "version": merged.get("version"),
        "min_lon": merged.get("min_lon"),
        "max_lon": merged.get("max_lon"),
        "min_lat": merged.get("min_lat"),
        "max_lat": merged.get("max_lat"),
        "resolution": merged.get("resolution"),
        "format": merged.get("format"),
        "source": merged.get("source"),
        "platform": merged.get("platform"),
        "sensor": merged.get("sensor"),
        "bits_per_pixel": merged.get("bits_per_pixel"),
        "file_path": str(rel_path),
        "status": status,
    }
    update_dataset(base_dir, dataset_id, record)
    steps.append({"step": "Updated catalog record", "status": "done"})

    manifest = generate_manifest(new_destination, merged, dataset_id, ds.get("original_filename", ""), status)
    write_manifest(new_destination, manifest)

    conn = get_conn(base_dir)
    conn.execute("DELETE FROM dataset_files WHERE dataset_id = ?", (dataset_id,))
    conn.commit()
    conn.close()

    all_files = [p for p in new_destination.rglob("*") if p.is_file() and p.name != "manifest.json"]
    for file_path in sorted(all_files):
        file_meta = {
            "relative_path": str(file_path.relative_to(new_destination)),
            "file_name": file_path.name,
            "extension": file_path.suffix.lower(),
            "file_role": "unknown",
            "file_size": file_path.stat().st_size,
            "file_hash": _file_hash(file_path),
            "format": "OTHER",
            "spatial": False,
        }
        ext = file_path.suffix.lower()
        if ext in {".tif", ".tiff"}:
            file_meta["format"] = "GeoTIFF"
            file_meta["file_role"] = "primary"
            file_meta["spatial"] = True
            gtiff_meta = read_geotiff_metadata(file_path)
            if not gtiff_meta.get("_error"):
                file_meta.update({
                    "crs": gtiff_meta.get("crs"),
                    "min_lon": gtiff_meta.get("bounds", (None, None, None, None))[0] if gtiff_meta.get("bounds") else None,
                    "min_lat": gtiff_meta.get("bounds", (None, None, None, None))[1] if gtiff_meta.get("bounds") else None,
                    "max_lon": gtiff_meta.get("bounds", (None, None, None, None))[2] if gtiff_meta.get("bounds") else None,
                    "max_lat": gtiff_meta.get("bounds", (None, None, None, None))[3] if gtiff_meta.get("bounds") else None,
                    "width": gtiff_meta.get("width"),
                    "height": gtiff_meta.get("height"),
                    "count": gtiff_meta.get("count"),
                    "dtype": gtiff_meta.get("dtype"),
                })
        elif ext == ".xml":
            file_meta["format"] = "XML"
            file_meta["file_role"] = "metadata"
        elif ext == ".shp":
            file_meta["format"] = "Shapefile"
            file_meta["file_role"] = "primary"
            file_meta["spatial"] = True
        elif ext in {".json", ".geojson"}:
            file_meta["format"] = "GeoJSON"
            file_meta["file_role"] = "primary"
            file_meta["spatial"] = True
        elif ext == ".csv":
            file_meta["format"] = "CSV"
            file_meta["file_role"] = "primary"
            file_meta["spatial"] = True
        elif ext in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            file_meta["format"] = "IMAGE"
            file_meta["file_role"] = "preview"
        elif ext in {".txt", ".pdf"}:
            file_meta["format"] = "DOCUMENT"
            file_meta["file_role"] = "documentation"
        insert_dataset_file(base_dir, dataset_id, file_meta)
    steps.append({"step": "Rebuilt file inventory", "status": "done"})

    computed_bounds = _compute_dataset_bounds_from_files(base_dir, dataset_id)
    if computed_bounds and not merged.get("bounds"):
        merged["bounds"] = computed_bounds
        merged["bounds_source"] = "file_union"
        merged["bounds_confidence"] = "high"
        manifest["spatial_metadata"]["bounds"] = computed_bounds
        write_manifest(new_destination, manifest)

    file_inventory = get_dataset_files(base_dir, dataset_id)
    quality_report = _build_quality_report(merged, file_inventory, classification)

    provenance = {}
    for key in ["tile", "version", "dataset_type"]:
        provenance[key] = {
            "value": merged.get(key),
            "source": merged.get(f"{key}_source", "unknown"),
            "confidence": merged.get(f"{key}_confidence", "UNKNOWN"),
        }

    run_id = start_ingestion_run(base_dir, dataset_id, ds.get("original_filename", ""), parser_version)
    if status == "NEEDS_REVIEW":
        steps.append({"step": "Dataset needs manual classification", "status": "warning"})
        complete_ingestion_run(base_dir, run_id, "needs_review", f"Missing: {quality_report['missing_fields']}")
    else:
        steps.append({"step": "Ready", "status": "complete"})
        complete_ingestion_run(base_dir, run_id, "success", f"Type: {dataset_type}, Confidence: {confidence}")

    response = {
        "status": "success",
        "operation": "reprocess",
        "dataset_id": dataset_id,
        "dataset_type": merged.get("dataset_type"),
        "dataset_name": merged.get("dataset_name"),
        "theme": merged.get("theme"),
        "tile": merged.get("tile"),
        "version": merged.get("version"),
        "bounds": merged.get("bounds"),
        "resolution": merged.get("resolution"),
        "format": merged.get("format"),
        "source": merged.get("source"),
        "platform": merged.get("platform"),
        "sensor": merged.get("sensor"),
        "bits_per_pixel": merged.get("bits_per_pixel"),
        "location": str(new_destination.relative_to(Path(base_dir))),
        "files": manifest.get("files", []),
        "confidence": confidence,
        "steps": steps,
        "classification": {
            "dataset_type": dataset_type,
            "confidence": confidence,
            "evidence": evidence,
        },
        "quality": quality_report,
        "metadata_provenance": provenance,
    }
    return response


def ingest_dataset(file_path: str, base_dir: str, parser_version: str = "1.0") -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []
    base_dir = str(Path(base_dir).resolve())
    processing_dir = Path(base_dir) / "data" / "processing"
    processing_dir.mkdir(parents=True, exist_ok=True)

    source_file = Path(file_path)
    steps.append({"step": "Validating upload", "status": "complete", "detail": source_file.name})

    validation = validate_upload(file_path)
    if not validation["valid"] and validation.get("error_reason"):
        return {
            "file": source_file.name,
            "status": "error",
            "error": validation["reason"],
            "error_reason": validation["error_reason"],
            "steps": steps + [{"step": validation["reason"], "status": "error"}],
        }

    file_hash = _file_hash(source_file)
    file_size = _file_size(source_file)

    init_db(base_dir)
    if is_exact_duplicate(base_dir, source_file.name, file_hash):
        steps.append({"step": "Exact duplicate detected - skipped", "status": "warning"})
        return {
            "file": source_file.name,
            "status": "already_exists",
            "steps": steps,
        }

    run_id = None
    record = {
        "original_filename": source_file.name,
        "file_size": file_size,
        "file_hash": file_hash,
        "status": "PROCESSING",
        "theme": "unknown",
    }
    dataset_id = insert_dataset(base_dir, record)
    run_id = start_ingestion_run(base_dir, dataset_id, source_file.name, parser_version)

    extract_dir = extract_if_archive(source_file, processing_dir)
    if extract_dir:
        steps.append({"step": "Archive extracted", "status": "done", "detail": str(extract_dir.name)})
    else:
        package_dir = processing_dir / source_file.stem
        package_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, package_dir / source_file.name)
        extract_dir = package_dir
        steps.append({"step": "File staged", "status": "done"})

    manifest = inspect_dataset(str(extract_dir))
    steps.append({"step": f"Inspected {manifest['supported_files']} supported files", "status": "done"})

    xml_meta: Dict[str, Any] = {}
    if manifest["xml_files"]:
        xml_meta = parse_xml(manifest["xml_files"][0])
        steps.append({"step": f"XML parsed: {manifest['xml_files'][0].name}", "status": "done"})
    else:
        steps.append({"step": "No XML metadata found", "status": "warning"})

    gtiff_meta: Dict[str, Any] = {}
    for primary in manifest.get("primary_files", []):
        if primary.suffix.lower() in {".tif", ".tiff"}:
            gtiff_meta = read_geotiff_metadata(primary)
            if gtiff_meta.get("_error"):
                steps.append({"step": f"GeoTIFF unreadable: {primary.name}", "status": "error"})
            else:
                steps.append({"step": f"GeoTIFF metadata read: {primary.name}", "status": "done"})
            break

    merged = _build_merged_metadata(xml_meta, gtiff_meta, source_file.name)
    if not merged.get("dataset_name"):
        merged["dataset_name"] = source_file.name

    _resolve_spatial_bounds(merged, gtiff_meta)

    steps.append({"step": "Metadata merged", "status": "done"})

    classification = classify_dataset(xml_meta, gtiff_meta, source_file.name)
    dataset_type = classification.get("dataset_type", "UNKNOWN")
    confidence = classification.get("confidence", "low")
    evidence = classification.get("evidence", [])
    merged["dataset_type"] = dataset_type
    merged["confidence"] = confidence
    merged["classification_evidence"] = evidence
    steps.append({"step": f"Classified as {dataset_type} ({confidence} confidence)", "status": "done"})

    for key in ["theme", "tile", "version", "dataset_name"]:
        if key not in merged or merged[key] is None:
            if key == "theme":
                merged[key] = "unknown"
            elif key == "tile":
                merged[key] = "UNKNOWN"
            elif key == "version":
                merged[key] = "UNKNOWN"
            elif key == "dataset_type" and not merged.get("dataset_type"):
                merged[key] = "UNKNOWN"
            merged[f"{key}_source"] = "unknown"
            merged[f"{key}_confidence"] = "unknown"

    if merged.get("theme") == "unknown" and merged.get("dataset_type") not in (None, "UNKNOWN"):
        theme_map = {
            "DEM": "terrain",
            "DSM": "terrain",
            "LULC": "landcover",
            "VECTOR": "vector",
            "BATHYMETRY": "terrain",
        }
        inferred_theme = theme_map.get(merged["dataset_type"])
        if inferred_theme:
            merged["theme"] = inferred_theme
            merged["theme_source"] = "inference"
            merged["theme_confidence"] = "medium"

    is_unknown = (
        merged.get("theme") == "unknown"
        or merged.get("dataset_type") == "UNKNOWN"
        or merged.get("tile") == "UNKNOWN"
        or merged.get("version") == "UNKNOWN"
    )
    if is_unknown:
        record["status"] = "NEEDS_REVIEW"
        update_status(base_dir, dataset_id, "NEEDS_REVIEW", error_reason="INSUFFICIENT_METADATA")

        all_files = [p for p in extract_dir.rglob("*") if p.is_file()]
        destination = build_destination(merged, base_dir, dataset_id=dataset_id)
        organize_files(all_files, destination)

        rel_path = destination.relative_to(Path(base_dir))
        record["file_path"] = str(rel_path)
        for k, v in merged.items():
            if k not in record or record[k] is None or record.get(k) in ("unknown", "UNKNOWN"):
                record[k] = v
        if merged.get("satellite") and not record.get("platform"):
            record["platform"] = merged["satellite"]
        record["file_path"] = str(rel_path)
        update_dataset(base_dir, dataset_id, record)

        manifest = generate_manifest(destination, merged, dataset_id, source_file.name, "NEEDS_REVIEW")
        write_manifest(destination, manifest)

        file_inventory = _build_file_inventory(dataset_id, destination, manifest, base_dir)
        quality_report = _build_quality_report(merged, file_inventory, classification)

        provenance = {}
        for key in ["tile", "version", "dataset_type"]:
            provenance[key] = {
                "value": merged.get(key),
                "source": merged.get(f"{key}_source", "unknown"),
                "confidence": merged.get(f"{key}_confidence", "UNKNOWN"),
            }

        if run_id:
            complete_ingestion_run(base_dir, run_id, "needs_review", f"Missing: {quality_report['missing_fields']}")

        return {
            "file": source_file.name,
            "status": "needs_review",
            "dataset_type": merged.get("dataset_type"),
            "dataset_name": merged.get("dataset_name"),
            "theme": merged.get("theme"),
            "tile": merged.get("tile"),
            "version": merged.get("version"),
            "bounds": merged.get("bounds"),
            "resolution": merged.get("resolution"),
            "format": merged.get("format"),
            "source": merged.get("source"),
            "platform": merged.get("satellite"),
            "sensor": merged.get("sensor"),
            "bits_per_pixel": merged.get("bits_per_pixel"),
            "confidence": confidence,
            "location": str(destination),
            "files": manifest.get("files", []),
            "metadata_provenance": provenance,
            "classification": {
                "dataset_type": dataset_type,
                "confidence": confidence,
                "evidence": evidence,
            },
            "dataset_id": dataset_id,
            "quality": quality_report,
            "steps": steps + [{"step": "Organized to unknown folder", "status": "done"}, {"step": "Generated manifest.json", "status": "done"}, {"step": "Dataset needs manual classification", "status": "warning"}],
        }

    dataset_validation = validate_dataset(extract_dir, manifest)
    if not dataset_validation["valid"]:
        reason = dataset_validation.get("error_reason", "UNKNOWN")
        update_status(base_dir, dataset_id, "QUARANTINED", error_reason=reason)
        quarantine_path = Path(base_dir) / "data" / "quarantine" / reason
        quarantine_path.mkdir(parents=True, exist_ok=True)
        dest = quarantine_path / source_file.name
        counter = 2
        while dest.exists():
            dest = quarantine_path / f"{source_file.stem}_{counter}{source_file.suffix}"
            counter += 1
        shutil.move(str(source_file), str(dest))
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        steps.append({"step": f"Quarantined: {dataset_validation['reason']}", "status": "error"})
        if run_id:
            complete_ingestion_run(base_dir, run_id, "quarantined", reason)
        return {
            "file": source_file.name,
            "status": "quarantined",
            "error_reason": reason,
            "reason": dataset_validation["reason"],
            "dataset_type": merged.get("dataset_type"),
            "tile": merged.get("tile"),
            "version": merged.get("version"),
            "steps": steps,
        }

    all_files = [p for p in extract_dir.rglob("*") if p.is_file()]
    destination = build_destination(merged, base_dir, dataset_id=dataset_id)
    organize_files(all_files, destination)

    rel_path = destination.relative_to(Path(base_dir))
    record["file_path"] = str(rel_path)
    record["status"] = "READY"
    for k, v in merged.items():
        if k not in record or record[k] is None or record.get(k) in ("unknown", "UNKNOWN"):
            record[k] = v
    if merged.get("satellite") and not record.get("platform"):
        record["platform"] = merged["satellite"]
    record["file_path"] = str(rel_path)
    update_dataset(base_dir, dataset_id, record)

    manifest = generate_manifest(destination, merged, dataset_id, source_file.name, "READY")
    write_manifest(destination, manifest)

    file_inventory = _build_file_inventory(dataset_id, destination, manifest, base_dir)

    computed_bounds = _compute_dataset_bounds_from_files(base_dir, dataset_id)
    if computed_bounds and not merged.get("bounds"):
        merged["bounds"] = computed_bounds
        merged["bounds_confidence"] = "high"
        merged["bounds_source"] = "file_union"
        manifest["spatial_metadata"]["bounds"] = computed_bounds
        write_manifest(destination, manifest)

    quality_report = _build_quality_report(merged, file_inventory, classification)

    steps.append({"step": f"Organized to {rel_path}", "status": "done"})
    steps.append({"step": "Generated manifest.json", "status": "done"})
    steps.append({"step": "Saved to catalog", "status": "done"})
    steps.append({"step": "Ready", "status": "complete"})

    response = {
        "file": source_file.name,
        "status": "success",
        "dataset_type": merged.get("dataset_type"),
        "dataset_name": merged.get("dataset_name"),
        "theme": merged.get("theme"),
        "tile": merged.get("tile"),
        "version": merged.get("version"),
        "bounds": merged.get("bounds"),
        "metadata_coverage": merged.get("metadata_coverage"),
        "spatial_consistency": merged.get("spatial_consistency"),
        "resolution": merged.get("resolution"),
        "format": merged.get("format"),
        "source": merged.get("source"),
        "platform": merged.get("satellite"),
        "sensor": merged.get("sensor"),
        "bits_per_pixel": merged.get("bits_per_pixel"),
        "location": str(destination),
        "files": manifest.get("files", []),
        "confidence": confidence,
        "steps": steps,
        "dataset_id": dataset_id,
        "classification": {
            "dataset_type": dataset_type,
            "confidence": confidence,
            "evidence": evidence,
        },
        "quality": quality_report,
    }

    provenance = {}
    for key in ["tile", "version", "dataset_type"]:
        provenance[key] = {
            "value": merged.get(key),
            "source": merged.get(f"{key}_source", "unknown"),
            "confidence": merged.get(f"{key}_confidence", "UNKNOWN"),
        }
    response["metadata_provenance"] = provenance

    if run_id:
        complete_ingestion_run(base_dir, run_id, "success", f"Type: {dataset_type}, Confidence: {confidence}")

    return response
