from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi import Body
from pathlib import Path
from typing import Dict, Any, List, Optional
from backend.app.ingestion.pipeline import ingest_dataset, reprocess_dataset
from backend.app.ingestion.catalog import (
    list_datasets, get_dataset, update_dataset, init_db, delete_dataset,
    search_datasets, soft_delete_dataset, permanent_delete_dataset, restore_dataset,
    get_dataset_files, delete_dataset_file, update_dataset_file,
    get_metadata_history, record_metadata_history,
    get_dataset_relationships, insert_dataset_relationship,
    get_ingestion_runs, check_spatial_overlap,
)
from backend.app.ingestion.organizer import build_destination, organize_files, generate_manifest, write_manifest
from backend.app.ingestion.validator import validate_upload
from backend.app.ingestion.duplicates import is_exact_duplicate
import shutil
import json
import zipfile

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
INCOMING_DIR = BASE_DIR / "data" / "incoming"
PROCESSING_DIR = BASE_DIR / "data" / "processing"

INCOMING_DIR.mkdir(parents=True, exist_ok=True)
PROCESSING_DIR.mkdir(parents=True, exist_ok=True)


def _build_dataset_detail(base_dir: str, ds: Dict[str, Any]) -> Dict[str, Any]:
    dataset_dir = Path(base_dir) / ds.get("file_path", "")
    manifest = {}
    manifest_path = dataset_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception:
            pass

    files = get_dataset_files(base_dir, ds["id"])
    file_list = []
    for f in files:
        file_list.append({
            "id": f.get("id"),
            "name": f.get("file_name"),
            "relative_path": f.get("relative_path"),
            "role": f.get("file_role"),
            "type": f.get("format"),
            "size": f.get("file_size"),
            "spatial": bool(f.get("spatial")),
            "crs": f.get("crs"),
            "min_lon": f.get("min_lon"),
            "min_lat": f.get("min_lat"),
            "max_lon": f.get("max_lon"),
            "max_lat": f.get("max_lat"),
        })

    bounds = None
    if ds.get("min_lon") is not None and ds.get("max_lon") is not None and ds.get("min_lat") is not None and ds.get("max_lat") is not None:
        bounds = {
            "west": ds.get("min_lon"),
            "south": ds.get("min_lat"),
            "east": ds.get("max_lon"),
            "north": ds.get("max_lat"),
            "crs": ds.get("format"),
        }
    elif manifest.get("spatial_metadata", {}).get("bounds"):
        bounds = manifest["spatial_metadata"]["bounds"]

    classification = manifest.get("classification")
    if not classification:
        classification = {
            "dataset_type": ds.get("dataset_type"),
            "confidence": "unknown",
            "evidence": [],
        }

    quality = manifest.get("quality")

    provenance = manifest.get("metadata_provenance", {})

    return {
        "id": ds["id"],
        "dataset_name": ds.get("dataset_name"),
        "dataset_type": ds.get("dataset_type"),
        "theme": ds.get("theme"),
        "tile": ds.get("tile"),
        "version": ds.get("version"),
        "status": ds.get("status"),
        "resolution": ds.get("resolution"),
        "format": ds.get("format"),
        "source": ds.get("source"),
        "platform": ds.get("platform"),
        "sensor": ds.get("sensor"),
        "bits_per_pixel": ds.get("bits_per_pixel"),
        "original_filename": ds.get("original_filename"),
        "file_size": ds.get("file_size"),
        "ingested_at": ds.get("ingested_at"),
        "location": ds.get("file_path"),
        "bounds": bounds,
        "files": file_list,
        "classification": classification,
        "quality": quality,
        "metadata_provenance": provenance,
    }


@router.get("/")
def list_datasets_api(
    type: str = Query(None),
    theme: str = Query(None),
    tile: str = Query(None),
    version: str = Query(None),
    platform: str = Query(None),
    sensor: str = Query(None),
    status: str = Query(None),
    name: str = Query(None),
    limit: int = Query(100),
    offset: int = Query(0),
):
    filters = {}
    if type:
        filters["dataset_type"] = type
    if theme:
        filters["theme"] = theme
    if tile:
        filters["tile"] = tile
    if version:
        filters["version"] = version
    if platform:
        filters["platform"] = platform
    if sensor:
        filters["sensor"] = sensor
    if status:
        filters["status"] = status
    if name:
        filters["dataset_name"] = name
    return search_datasets(str(BASE_DIR), {"limit": limit, "offset": offset, **filters})


@router.get("/{dataset_id}")
def get_dataset_api(dataset_id: int):
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return _build_dataset_detail(str(BASE_DIR), ds)


@router.post("/upload")
async def upload_datasets(file: list[UploadFile] = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="No files uploaded")

    saved_paths = []
    for f in file:
        if not f.filename:
            continue
        file_path = INCOMING_DIR / f.filename
        with open(file_path, "wb") as buffer:
            content = await f.read()
            buffer.write(content)
        saved_paths.append(str(file_path))

    results = []
    for path in saved_paths:
        result = ingest_dataset(path, str(BASE_DIR))
        results.append(result)

    processed = [r for r in results if r.get("status") != "error"]
    errors = [r for r in results if r.get("status") == "error"]
    quarantined = [r for r in results if r.get("status") == "quarantined"]
    duplicates = [r for r in results if r.get("status") == "already_exists"]

    return {
        "results": results,
        "summary": {
            "processed": len(processed),
            "errors": len(errors),
            "quarantined": len(quarantined),
            "duplicates": len(duplicates),
        },
    }


@router.delete("/{dataset_id}")
def delete_dataset_api(dataset_id: int, permanent: bool = Query(False)):
    if permanent:
        result = permanent_delete_dataset(str(BASE_DIR), dataset_id)
    else:
        result = soft_delete_dataset(str(BASE_DIR), dataset_id)
    if not result.get("deleted"):
        raise HTTPException(status_code=404, detail=result.get("reason", "Dataset not found"))
    return result


@router.post("/{dataset_id}/restore")
def restore_dataset_api(dataset_id: int):
    result = restore_dataset(str(BASE_DIR), dataset_id)
    if not result.get("restored"):
        raise HTTPException(status_code=404, detail=result.get("reason", "Dataset not found"))
    return result


@router.post("/{dataset_id}/reprocess")
def reprocess_dataset_api(dataset_id: int):
    result = reprocess_dataset(str(BASE_DIR), dataset_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error", "Reprocess failed"))
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found after reprocess")
    detail = _build_dataset_detail(str(BASE_DIR), ds)
    return {
        "status": "success",
        "operation": "reprocess",
        "dataset": detail,
    }


@router.put("/{dataset_id}/classify")
def classify_dataset_api(dataset_id: int, payload: dict = Body(...)):
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    current_path = Path(ds["file_path"])
    old_destination = BASE_DIR / current_path

    metadata = {
        "theme": payload.get("theme", ds.get("theme", "unknown")),
        "dataset_type": payload.get("dataset_type", ds.get("dataset_type", "UNKNOWN")),
        "tile": payload.get("tile", ds.get("tile", "UNKNOWN")),
        "version": payload.get("version", ds.get("version", "UNKNOWN")),
        "dataset_name": ds.get("dataset_name"),
        "resolution": ds.get("resolution"),
        "format": ds.get("format"),
        "source": ds.get("source"),
        "min_lon": ds.get("min_lon"),
        "max_lon": ds.get("max_lon"),
        "min_lat": ds.get("min_lat"),
        "max_lat": ds.get("max_lat"),
    }

    new_destination = build_destination(metadata, str(BASE_DIR), dataset_id=dataset_id)
    new_destination.mkdir(parents=True, exist_ok=True)

    if old_destination.exists() and old_destination != new_destination:
        if new_destination.exists() and any(new_destination.iterdir()):
            raise HTTPException(status_code=409, detail="Destination already exists and is not empty")
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

    rel_path = new_destination.relative_to(BASE_DIR)
    update_dataset(str(BASE_DIR), dataset_id, {
        "theme": metadata["theme"],
        "dataset_type": metadata["dataset_type"],
        "tile": metadata["tile"],
        "version": metadata["version"],
        "file_path": str(rel_path),
        "status": "READY",
    })

    manifest = generate_manifest(new_destination, metadata, dataset_id, ds.get("original_filename", ""), "READY")
    write_manifest(new_destination, manifest)

    updated_ds = get_dataset(str(BASE_DIR), dataset_id)
    detail = _build_dataset_detail(str(BASE_DIR), updated_ds)
    return {
        "status": "success",
        "operation": "classify",
        "dataset": detail,
    }


@router.put("/{dataset_id}/rename")
def rename_dataset_api(dataset_id: int, payload: dict = Body(...)):
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    new_name = payload.get("dataset_name")
    if not new_name:
        raise HTTPException(status_code=400, detail="dataset_name is required")

    current_path = Path(ds["file_path"])
    dataset_dir = BASE_DIR / current_path
    if not dataset_dir.exists():
        raise HTTPException(status_code=404, detail="Dataset directory not found")

    update_dataset(str(BASE_DIR), dataset_id, {
        "dataset_name": new_name,
    })

    manifest_path = dataset_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            manifest["dataset_name"] = new_name
            write_manifest(dataset_dir, manifest)
        except Exception:
            pass

    updated_ds = get_dataset(str(BASE_DIR), dataset_id)
    detail = _build_dataset_detail(str(BASE_DIR), updated_ds)
    return {
        "status": "success",
        "operation": "rename",
        "dataset": detail,
    }


@router.put("/{dataset_id}/metadata")
def update_dataset_metadata_api(dataset_id: int, payload: dict = Body(...)):
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    allowed_fields = {
        "dataset_name", "dataset_type", "theme", "tile", "version",
        "source", "platform", "sensor", "bits_per_pixel",
        "min_lon", "max_lon", "min_lat", "max_lat",
        "resolution", "format",
    }

    changes = []
    for field in allowed_fields:
        if field in payload:
            old_value = ds.get(field)
            new_value = payload[field]
            if old_value != new_value:
                record_metadata_history(str(BASE_DIR), dataset_id, field, str(old_value), str(new_value), "manual")
                changes.append({
                    "field": field,
                    "old_value": old_value,
                    "new_value": new_value,
                })

    if not changes:
        updated_ds = get_dataset(str(BASE_DIR), dataset_id)
        detail = _build_dataset_detail(str(BASE_DIR), updated_ds)
        return {"status": "success", "operation": "metadata", "dataset": detail, "changes": []}

    metadata_updates = {c["field"]: c["new_value"] for c in changes}
    metadata_updates["file_path"] = ds.get("file_path")
    metadata_updates["status"] = "READY"

    current_path = Path(ds["file_path"])
    old_destination = BASE_DIR / current_path
    new_destination = build_destination(metadata_updates, str(BASE_DIR), dataset_id=dataset_id)

    if old_destination.exists() and old_destination != new_destination:
        if new_destination.exists() and any(new_destination.iterdir()):
            raise HTTPException(status_code=409, detail="Destination already exists and is not empty")
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
        metadata_updates["file_path"] = str(new_destination.relative_to(BASE_DIR))

    update_dataset(str(BASE_DIR), dataset_id, metadata_updates)

    dataset_dir = BASE_DIR / metadata_updates["file_path"]
    if dataset_dir.exists():
        manifest_path = dataset_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
                for c in changes:
                    manifest_key = c["field"]
                    if manifest_key in manifest:
                        manifest[manifest_key] = c["new_value"]
                manifest["status"] = "READY"
                write_manifest(dataset_dir, manifest)
            except Exception:
                pass

    updated_ds = get_dataset(str(BASE_DIR), dataset_id)
    detail = _build_dataset_detail(str(BASE_DIR), updated_ds)
    return {
        "status": "success",
        "operation": "metadata",
        "dataset": detail,
        "changes": changes,
    }


@router.get("/{dataset_id}/files")
def get_dataset_files_api(dataset_id: int):
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    files = get_dataset_files(str(BASE_DIR), dataset_id)
    return {
        "dataset_id": dataset_id,
        "file_path": ds["file_path"],
        "files": files,
    }


@router.delete("/{dataset_id}/files/{file_id}")
def delete_dataset_file_api(dataset_id: int, file_id: int):
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    current_path = Path(ds["file_path"])
    dataset_dir = BASE_DIR / current_path
    if not dataset_dir.exists():
        raise HTTPException(status_code=404, detail="Dataset directory not found")

    file_records = get_dataset_files(str(BASE_DIR), dataset_id)
    target_record = next((f for f in file_records if f.get("id") == file_id), None)
    if not target_record:
        raise HTTPException(status_code=404, detail="File not found in catalog")

    relative_path = target_record.get("relative_path")
    target_file = dataset_dir / relative_path if relative_path else None
    if target_file and target_file.exists() and target_file.is_file():
        if target_file.name == "manifest.json":
            raise HTTPException(status_code=400, detail="Cannot delete manifest via this endpoint")
        target_file.unlink()

    result = delete_dataset_file(str(BASE_DIR), dataset_id, file_id)

    manifest_path = dataset_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            manifest["files"] = [f for f in manifest.get("files", []) if f.get("name") != target_record.get("file_name")]
            write_manifest(dataset_dir, manifest)
        except Exception:
            pass

    return result


@router.put("/{dataset_id}/files/{file_id}")
def update_dataset_file_api(dataset_id: int, file_id: int, payload: dict = Body(...)):
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    new_role = payload.get("role")
    if not new_role:
        raise HTTPException(status_code=400, detail="role is required")

    result = update_dataset_file(str(BASE_DIR), dataset_id, file_id, {"file_role": new_role})

    current_path = Path(ds["file_path"])
    dataset_dir = BASE_DIR / current_path
    if dataset_dir.exists():
        file_records = get_dataset_files(str(BASE_DIR), dataset_id)
        target_record = next((f for f in file_records if f.get("id") == file_id), None)
        if target_record:
            manifest_path = dataset_dir / "manifest.json"
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text())
                    for f in manifest.get("files", []):
                        if f.get("name") == target_record.get("file_name"):
                            f["role"] = new_role
                            break
                    write_manifest(dataset_dir, manifest)
                except Exception:
                    pass

    return result


@router.get("/{dataset_id}/history")
def get_dataset_history_api(dataset_id: int):
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    metadata_history = get_metadata_history(str(BASE_DIR), dataset_id)
    ingestion_runs = get_ingestion_runs(str(BASE_DIR), dataset_id)
    relationships = get_dataset_relationships(str(BASE_DIR), dataset_id)

    return {
        "dataset_id": dataset_id,
        "dataset_name": ds.get("dataset_name"),
        "metadata_history": metadata_history,
        "ingestion_runs": ingestion_runs,
        "relationships": relationships,
    }


@router.get("/{dataset_id}/quality")
def get_dataset_quality_api(dataset_id: int):
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    current_path = Path(ds["file_path"])
    dataset_dir = BASE_DIR / current_path
    manifest_path = dataset_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception:
            pass

    quality = manifest.get("quality", {})
    return {
        "dataset_id": dataset_id,
        "dataset_name": ds.get("dataset_name"),
        "status": ds.get("status"),
        "quality": quality,
    }


@router.post("/{dataset_id}/move")
def move_dataset_api(dataset_id: int, payload: dict = Body(...)):
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    theme = payload.get("theme", ds.get("theme", "unknown"))
    dataset_type = payload.get("dataset_type", ds.get("dataset_type", "UNKNOWN"))
    tile = payload.get("tile", ds.get("tile", "UNKNOWN"))
    version = payload.get("version", ds.get("version", "UNKNOWN"))

    metadata = {
        "theme": theme,
        "dataset_type": dataset_type,
        "tile": tile,
        "version": version,
        "dataset_name": ds.get("dataset_name"),
        "resolution": ds.get("resolution"),
        "format": ds.get("format"),
        "source": ds.get("source"),
        "min_lon": ds.get("min_lon"),
        "max_lon": ds.get("max_lon"),
        "min_lat": ds.get("min_lat"),
        "max_lat": ds.get("max_lat"),
    }

    current_path = Path(ds["file_path"])
    old_destination = BASE_DIR / current_path
    new_destination = build_destination(metadata, str(BASE_DIR), dataset_id=dataset_id)

    if old_destination == new_destination:
        updated_ds = get_dataset(str(BASE_DIR), dataset_id)
        detail = _build_dataset_detail(str(BASE_DIR), updated_ds)
        return {"status": "success", "operation": "move", "dataset": detail}

    if new_destination.exists() and any(new_destination.iterdir()):
        raise HTTPException(status_code=409, detail="Destination already exists and is not empty")

    new_destination.mkdir(parents=True, exist_ok=True)
    moved_items = []
    try:
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
            moved_items.append((item, target))
        shutil.rmtree(old_destination)
    except Exception as e:
        for src, dst in moved_items:
            try:
                shutil.move(str(dst), str(src))
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Move failed, rolled back: {str(e)}")

    rel_path = new_destination.relative_to(BASE_DIR)
    update_dataset(str(BASE_DIR), dataset_id, {
        "theme": theme,
        "dataset_type": dataset_type,
        "tile": tile,
        "version": version,
        "file_path": str(rel_path),
        "status": "READY",
    })

    manifest = generate_manifest(new_destination, metadata, dataset_id, ds.get("original_filename", ""), "READY")
    write_manifest(new_destination, manifest)

    updated_ds = get_dataset(str(BASE_DIR), dataset_id)
    detail = _build_dataset_detail(str(BASE_DIR), updated_ds)
    return {
        "status": "success",
        "operation": "move",
        "dataset": detail,
    }


@router.post("/{dataset_id}/relationships")
def add_relationship_api(dataset_id: int, payload: dict = Body(...)):
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    related_id = payload.get("related_dataset_id")
    relationship_type = payload.get("relationship_type")
    if not related_id or not relationship_type:
        raise HTTPException(status_code=400, detail="related_dataset_id and relationship_type are required")

    related = get_dataset(str(BASE_DIR), related_id)
    if not related:
        raise HTTPException(status_code=404, detail="Related dataset not found")

    insert_dataset_relationship(str(BASE_DIR), dataset_id, related_id, relationship_type)

    return {
        "status": "success",
        "dataset_id": dataset_id,
        "related_dataset_id": related_id,
        "relationship_type": relationship_type,
    }


@router.get("/{dataset_id}/relationships")
def get_relationships_api(dataset_id: int):
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    relationships = get_dataset_relationships(str(BASE_DIR), dataset_id)
    return {
        "dataset_id": dataset_id,
        "relationships": relationships,
    }


@router.get("/integrity/check/{dataset_id}")
def check_dataset_integrity(dataset_id: int):
    ds = get_dataset(str(BASE_DIR), dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    path = BASE_DIR / ds["file_path"]
    checks = []
    issues = []

    checks.append({"check": "catalog_record_exists", "passed": True})

    if path.exists() and path.is_dir():
        checks.append({"check": "directory_exists", "passed": True})
    else:
        checks.append({"check": "directory_exists", "passed": False})
        issues.append("MISSING_DIRECTORY")
        return {
            "dataset_id": dataset_id,
            "dataset_name": ds.get("dataset_name"),
            "file_path": ds.get("file_path"),
            "status": "broken",
            "checks": checks,
            "issues": issues,
        }

    manifest_path = path / "manifest.json"
    if manifest_path.exists():
        checks.append({"check": "manifest_exists", "passed": True})
        try:
            manifest = json.loads(manifest_path.read_text())
            if manifest.get("dataset_id") == dataset_id:
                checks.append({"check": "manifest_dataset_id_matches", "passed": True})
            else:
                checks.append({"check": "manifest_dataset_id_matches", "passed": False})
                issues.append("MANIFEST_ID_MISMATCH")

            expected_files = {f["name"] for f in manifest.get("files", [])}
            actual_files = {p.name for p in path.iterdir() if p.is_file() and p.name != "manifest.json"}
            missing = expected_files - actual_files
            extra = actual_files - expected_files
            if missing:
                checks.append({"check": "expected_files_present", "passed": False})
                issues.append(f"MISSING_FILES: {sorted(missing)}")
            else:
                checks.append({"check": "expected_files_present", "passed": True})
            if extra:
                checks.append({"check": "unexpected_files_absent", "passed": False})
                issues.append(f"UNEXPECTED_FILES: {sorted(extra)}")
            else:
                checks.append({"check": "unexpected_files_absent", "passed": True})
        except Exception:
            checks.append({"check": "manifest_readable", "passed": False})
            issues.append("CORRUPTED_MANIFEST")
    else:
        checks.append({"check": "manifest_exists", "passed": False})
        issues.append("MISSING_MANIFEST")

    primary_files = [p for p in path.iterdir() if p.is_file() and p.name != "manifest.json"]
    if primary_files:
        checks.append({"check": "primary_file_exists", "passed": True})
    else:
        checks.append({"check": "primary_file_exists", "passed": False})
        issues.append("NO_PRIMARY_FILE")

    status = "healthy" if not issues else "broken"
    return {
        "dataset_id": dataset_id,
        "dataset_name": ds.get("dataset_name"),
        "file_path": ds.get("file_path"),
        "status": status,
        "checks": checks,
        "issues": issues,
    }


@router.get("/search/overlap")
def search_spatial_overlap(
    dataset_type: str = Query(...),
    west: float = Query(...),
    south: float = Query(...),
    east: float = Query(...),
    north: float = Query(...),
    exclude_dataset_id: int = Query(None),
):
    overlaps = check_spatial_overlap(str(BASE_DIR), dataset_type, {
        "west": west, "south": south, "east": east, "north": north,
    }, exclude_dataset_id)
    return {
        "dataset_type": dataset_type,
        "query_bounds": {"west": west, "south": south, "east": east, "north": north},
        "overlapping_datasets": overlaps,
        "count": len(overlaps),
    }


@router.post("/search/area")
def search_datasets_by_area(payload: dict = Body(...)):
    try:
        bounds = payload["bounds"]
    except KeyError:
        raise HTTPException(status_code=400, detail="bounds is required")

    dataset_types = payload.get("dataset_types")
    include_partial = payload.get("include_partial_overlap", True)

    from backend.app.integration.analysis_data_provider import search_datasets_by_area as _search
    result = _search(str(BASE_DIR), bounds, dataset_types, include_partial)
    return result


@router.post("/readiness")
def evaluate_dataset_readiness(payload: dict = Body(...)):
    try:
        area = payload["area"]
        analysis = payload["analysis"]
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing required field: {str(e)}")

    from backend.app.integration.analysis_data_provider import evaluate_readiness
    result = evaluate_readiness(str(BASE_DIR), area, analysis)
    return result


@router.post("/recommend")
def recommend_datasets(payload: dict = Body(...)):
    try:
        area = payload["area"]
    except KeyError:
        raise HTTPException(status_code=400, detail="area is required")

    analysis = payload.get("analysis")
    dataset_type = payload.get("dataset_type")
    top_n = payload.get("top_n", 5)

    from backend.app.integration.analysis_data_provider import search_datasets_by_area, rank_datasets
    search_results = search_datasets_by_area(
        str(BASE_DIR), area,
        dataset_types=[dataset_type] if dataset_type else None,
        include_partial_overlap=True,
    )
    all_candidates = search_results["fully_covering"] + search_results["partially_overlapping"]

    if not analysis:
        if dataset_type:
            analysis = dataset_type.lower()
        else:
            analysis = "terrain"

    ranking = rank_datasets(all_candidates, area, analysis, top_n=top_n)
    return {
        "area": area,
        "analysis": analysis,
        "dataset_type": dataset_type,
        **ranking,
    }


@router.post("/compatibility")
def check_dataset_compatibility(payload: dict = Body(...)):
    try:
        dataset_ids = payload["dataset_ids"]
    except KeyError:
        raise HTTPException(status_code=400, detail="dataset_ids is required")

    from backend.app.integration.analysis_data_provider import check_compatibility
    result = check_compatibility(str(BASE_DIR), dataset_ids)
    return result


@router.post("/temporal-pairs")
def find_temporal_dataset_pairs(payload: dict = Body(...)):
    try:
        dataset_type = payload["dataset_type"]
    except KeyError:
        raise HTTPException(status_code=400, detail="dataset_type is required")

    area = payload.get("area")
    min_days = payload.get("min_temporal_difference_days", 30)

    from backend.app.integration.analysis_data_provider import find_temporal_pairs
    result = find_temporal_pairs(str(BASE_DIR), dataset_type, area, min_days)
    return result


@router.post("/prepare-analysis")
def prepare_analysis_package(payload: dict = Body(...)):
    try:
        area = payload["area"]
        analysis = payload["analysis"]
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing required field: {str(e)}")

    from backend.app.integration.analysis_data_provider import prepare_analysis_data
    result = prepare_analysis_data(str(BASE_DIR), area, analysis)
    return result


@router.post("/capabilities")
def get_area_capabilities(payload: dict = Body(...)):
    try:
        area = payload["area"]
    except KeyError:
        raise HTTPException(status_code=400, detail="area is required")

    from backend.app.integration.analysis_data_provider import get_capabilities
    result = get_capabilities(str(BASE_DIR), area)
    return result


@router.get("/search/temporal")
def search_datasets_temporal(
    dataset_type: str = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    west: float = Query(None),
    south: float = Query(None),
    east: float = Query(None),
    north: float = Query(None),
):
    from backend.app.ingestion.catalog import list_datasets, get_conn
    from datetime import datetime

    datasets = list_datasets(str(BASE_DIR), limit=1000, offset=0)

    filtered = []
    for ds in datasets:
        if dataset_type and ds.get("dataset_type") != dataset_type:
            continue
        if start_date or end_date:
            acquired = ds.get("acquired_at") or ds.get("ingested_at")
            if acquired:
                try:
                    dt = datetime.fromisoformat(acquired)
                    if start_date:
                        s = datetime.fromisoformat(start_date)
                        if dt < s:
                            continue
                    if end_date:
                        e = datetime.fromisoformat(end_date)
                        if dt > e:
                            continue
                except (ValueError, TypeError):
                    pass
        if all(v is not None for v in [west, south, east, north]):
            if not (ds.get("min_lon") and ds.get("max_lon") and ds.get("min_lat") and ds.get("max_lat")):
                continue
            if not (ds["min_lon"] < east and ds["max_lon"] > west and ds["min_lat"] < north and ds["max_lat"] > south):
                continue
        filtered.append(ds)

    return {
        "dataset_type": dataset_type,
        "start_date": start_date,
        "end_date": end_date,
        "count": len(filtered),
        "datasets": filtered,
    }
