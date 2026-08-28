from typing import Dict, Any, List, Optional
from pathlib import Path

from backend.app.ingestion.spatial_helpers import (
    calculate_overlap,
    calculate_coverage_percentage,
    get_spatial_relation,
    check_crs_compatibility,
    check_resolution_compatibility,
)
from backend.app.ingestion.recommendation import rank_datasets, RECOMMENDATION_WEIGHTS
from backend.app.ingestion.analysis_registry import get_analysis_requirements, get_supported_analyses
from backend.app.ingestion.catalog import (
    list_datasets, get_dataset, get_dataset_files, check_spatial_overlap,
    get_metadata_history, get_ingestion_runs,
)
from backend.app.ingestion.organizer import generate_manifest
import json


def _load_manifest(dataset_dir: Path) -> Dict[str, Any]:
    manifest_path = dataset_dir / "manifest.json"
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text())
        except Exception:
            pass
    return {}


def _get_dataset_quality(dataset_dir: Path) -> Dict[str, Any]:
    manifest = _load_manifest(dataset_dir)
    return manifest.get("quality") or {}


def _get_dataset_classification(dataset_dir: Path) -> Dict[str, Any]:
    manifest = _load_manifest(dataset_dir)
    return manifest.get("classification", {})


def _dataset_is_usable(dataset: Dict[str, Any], dataset_dir: Path) -> bool:
    if dataset.get("status") == "QUARANTINED":
        return False
    if dataset.get("deleted_at"):
        return False

    manifest = _load_manifest(dataset_dir)
    quality = manifest.get("quality") or {}
    if quality.get("score", 100) < 30:
        return False

    return True


def search_datasets_by_area(
    base_dir: str,
    bounds: Dict[str, float],
    dataset_types: Optional[List[str]] = None,
    include_partial_overlap: bool = True,
) -> Dict[str, Any]:
    from backend.app.ingestion.catalog import init_db
    init_db(base_dir)
    datasets = list_datasets(base_dir, limit=1000, offset=0)
    results = {
        "query_bounds": bounds,
        "fully_covering": [],
        "partially_overlapping": [],
        "nearby": [],
    }

    for ds in datasets:
        ds_bounds = {
            "west": ds.get("min_lon"),
            "south": ds.get("min_lat"),
            "east": ds.get("max_lon"),
            "north": ds.get("max_lat"),
        }
        if not all(v is not None for v in ds_bounds.values()):
            continue

        if dataset_types and ds.get("dataset_type") not in dataset_types:
            continue

        relation = get_spatial_relation(ds_bounds, bounds)
        if relation == "none":
            continue

        coverage = calculate_coverage_percentage(ds_bounds, bounds)
        dataset_dir = Path(base_dir) / ds.get("file_path", "")
        usable = _dataset_is_usable(ds, dataset_dir)
        quality = _get_dataset_quality(dataset_dir)

        entry = {
            "dataset_id": ds["id"],
            "dataset_name": ds.get("dataset_name"),
            "dataset_type": ds.get("dataset_type"),
            "theme": ds.get("theme"),
            "bounds": ds_bounds,
            "coverage_percentage": coverage,
            "spatial_relation": relation,
            "quality_score": quality.get("score"),
            "resolution": ds.get("resolution"),
            "format": ds.get("format"),
            "source": ds.get("source"),
            "location": ds.get("file_path"),
            "usable": usable,
            "warnings": quality.get("missing_fields", []),
        }

        if relation == "full_coverage":
            results["fully_covering"].append(entry)
        elif relation == "partial_overlap" and include_partial_overlap:
            results["partially_overlapping"].append(entry)

    results["fully_covering"].sort(key=lambda x: x["coverage_percentage"], reverse=True)
    results["partially_overlapping"].sort(key=lambda x: x["coverage_percentage"], reverse=True)

    return results


def evaluate_readiness(
    base_dir: str,
    bounds: Dict[str, float],
    analysis_type: str,
) -> Dict[str, Any]:
    requirements = get_analysis_requirements(analysis_type)
    if not requirements:
        return {
            "analysis": analysis_type,
            "ready": False,
            "readiness_score": 0,
            "datasets": [],
            "missing_requirements": [f"Unknown analysis type: {analysis_type}"],
            "warnings": [],
        }

    search_results = search_datasets_by_area(
        base_dir, bounds,
        dataset_types=requirements.get("required") + requirements.get("preferred", []),
        include_partial_overlap=True,
    )

    all_candidates = search_results["fully_covering"] + search_results["partially_overlapping"]

    required_types = set(requirements.get("required", []))
    preferred_types = set(requirements.get("preferred", []))
    min_datasets = requirements.get("min_datasets", 1)

    matched_required = {}
    matched_preferred = {}

    for ds in all_candidates:
        ds_type = ds.get("dataset_type")
        if ds_type in required_types:
            if ds_type not in matched_required:
                matched_required[ds_type] = ds
        elif ds_type in preferred_types:
            if ds_type not in matched_preferred:
                matched_preferred[ds_type] = ds

    datasets = []
    for ds in matched_required.values():
        datasets.append({
            "dataset_id": ds["dataset_id"],
            "role": "primary",
            "dataset_type": ds["dataset_type"],
            "coverage_percentage": ds["coverage_percentage"],
            "quality_score": ds.get("quality_score"),
            "usable": ds["usable"],
        })
    for ds in matched_preferred.values():
        datasets.append({
            "dataset_id": ds["dataset_id"],
            "role": "preferred",
            "dataset_type": ds["dataset_type"],
            "coverage_percentage": ds["coverage_percentage"],
            "quality_score": ds.get("quality_score"),
            "usable": ds["usable"],
        })

    missing_requirements = []
    for req_type in required_types:
        if req_type not in matched_required:
            missing_requirements.append(f"Required dataset type '{req_type}' not found")

    if analysis_type == "change_detection" and len(all_candidates) < min_datasets:
        missing_requirements.append(f"Change detection requires at least {min_datasets} compatible datasets")

    ready = len(missing_requirements) == 0 and len(datasets) > 0

    score = 0
    if ready:
        score = 100
        if missing_requirements:
            score -= len(missing_requirements) * 20
        for ds in datasets:
            if ds.get("coverage_percentage", 0) < 80:
                score -= 5
            qs = ds.get("quality_score") or 0
            if qs < 50:
                score -= 10
        score = max(0, min(100, score))

    return {
        "analysis": analysis_type,
        "ready": ready,
        "readiness_score": score,
        "datasets": datasets,
        "missing_requirements": missing_requirements,
        "warnings": [],
    }


def get_capabilities(base_dir: str, bounds: Dict[str, float]) -> Dict[str, Any]:
    supported = get_supported_analyses()
    capabilities = []

    for analysis in supported:
        readiness = evaluate_readiness(base_dir, bounds, analysis)
        capabilities.append({
            "analysis": analysis,
            "available": readiness["ready"],
            "readiness_score": readiness["readiness_score"],
            "missing_requirements": readiness.get("missing_requirements", []),
            "warnings": readiness.get("warnings", []),
        })

    return {
        "area": bounds,
        "capabilities": capabilities,
    }


def check_compatibility(base_dir: str, dataset_ids: List[int]) -> Dict[str, Any]:
    issues = []
    warnings = []
    recommendations = []

    datasets = []
    for did in dataset_ids:
        ds = get_dataset(base_dir, did)
        if not ds:
            issues.append(f"Dataset {did} not found")
            continue
        datasets.append(ds)

    if len(datasets) < 2:
        return {
            "compatible": len(datasets) >= 2,
            "issues": issues,
            "warnings": warnings,
            "recommendations": recommendations,
        }

    crs_set = set()
    res_set = set()
    type_set = set()

    for ds in datasets:
        if ds.get("format"):
            crs_set.add(ds.get("format"))
        if ds.get("resolution"):
            res_set.add(ds.get("resolution"))
        if ds.get("dataset_type"):
            type_set.add(ds.get("dataset_type"))

    if len(crs_set) > 1:
        issues.append(f"Multiple CRS/formats found: {', '.join(crs_set)}")
        recommendations.append("Reproject datasets to common CRS before analysis")

    if len(res_set) > 1:
        warnings.append(f"Different resolutions: {', '.join(str(r) for r in res_set)}")
        recommendations.append("Resample datasets to common resolution before analysis")

    if len(type_set) > 1:
        warnings.append(f"Mixed dataset types: {', '.join(type_set)}")

    for ds in datasets:
        dataset_dir = Path(base_dir) / ds.get("file_path", "")
        if not dataset_dir.exists():
            issues.append(f"Dataset {ds['id']} directory missing: {ds.get('file_path')}")

        manifest = _load_manifest(dataset_dir)
        quality = manifest.get("quality") or {}
        if quality.get("score", 100) < 50:
            warnings.append(f"Dataset {ds['id']} has low quality score: {quality.get('score')}")

    compatible = len(issues) == 0

    return {
        "compatible": compatible,
        "issues": issues,
        "warnings": warnings,
        "recommendations": recommendations,
    }


def find_temporal_pairs(
    base_dir: str,
    dataset_type: str,
    area: Optional[Dict[str, float]] = None,
    min_temporal_difference_days: int = 30,
) -> Dict[str, Any]:
    datasets = list_datasets(base_dir, limit=1000, offset=0, filters={"dataset_type": dataset_type})

    candidates = []
    for ds in datasets:
        if ds.get("status") == "QUARANTINED":
            continue
        if ds.get("deleted_at"):
            continue

        if area:
            ds_bounds = {
                "west": ds.get("min_lon"),
                "south": ds.get("min_lat"),
                "east": ds.get("max_lon"),
                "north": ds.get("max_lat"),
            }
            if not all(v is not None for v in ds_bounds.values()):
                continue
            relation = get_spatial_relation(ds_bounds, area)
            if relation == "none":
                continue

        candidates.append(ds)

    pairs = []
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            ds_a = candidates[i]
            ds_b = candidates[j]

            ingested_a = ds_a.get("ingested_at", "")
            ingested_b = ds_b.get("ingested_at", "")
            diff_days = 0
            if ingested_a and ingested_b:
                from datetime import datetime
                try:
                    date_a = datetime.fromisoformat(ingested_a)
                    date_b = datetime.fromisoformat(ingested_b)
                    diff_days = abs((date_b - date_a).days)
                except (ValueError, TypeError):
                    pass

            if diff_days < min_temporal_difference_days:
                continue

            ds_a_bounds = {
                "west": ds_a.get("min_lon"),
                "south": ds_a.get("min_lat"),
                "east": ds_a.get("max_lon"),
                "north": ds_a.get("max_lat"),
            }
            ds_b_bounds = {
                "west": ds_b.get("min_lon"),
                "south": ds_b.get("min_lat"),
                "east": ds_b.get("max_lon"),
                "north": ds_b.get("max_lat"),
            }
            overlap = calculate_overlap(ds_a_bounds, ds_b_bounds)
            overlap_pct = calculate_coverage_percentage(ds_a_bounds, ds_b_bounds)

            compatibility = check_compatibility(base_dir, [ds_a["id"], ds_b["id"]])

            score = 0
            score += min(100.0, overlap_pct) * 0.5
            if compatibility["compatible"]:
                score += 50
            score += min(100.0, diff_days / 365.0) * 0.3
            score = min(100.0, score)

            pairs.append({
                "dataset_a": {
                    "dataset_id": ds_a["id"],
                    "dataset_name": ds_a.get("dataset_name"),
                    "dataset_type": ds_a.get("dataset_type"),
                    "ingested_at": ingested_a,
                    "bounds": ds_a_bounds,
                },
                "dataset_b": {
                    "dataset_id": ds_b["id"],
                    "dataset_name": ds_b.get("dataset_name"),
                    "dataset_type": ds_b.get("dataset_type"),
                    "ingested_at": ingested_b,
                    "bounds": ds_b_bounds,
                },
                "temporal_difference_days": diff_days,
                "spatial_overlap_percentage": overlap_pct,
                "compatibility_score": round(score, 2),
                "compatible": compatibility["compatible"],
                "compatibility_issues": compatibility["issues"],
            })

    pairs.sort(key=lambda x: x["compatibility_score"], reverse=True)

    return {"pairs": pairs[:20]}


def prepare_analysis_data(
    base_dir: str,
    area: Dict[str, float],
    analysis: str,
) -> Dict[str, Any]:
    requirements = get_analysis_requirements(analysis)
    if not requirements:
        return {
            "status": "error",
            "analysis": analysis,
            "error": f"Unknown analysis type: {analysis}",
            "datasets": [],
        }

    readiness = evaluate_readiness(base_dir, area, analysis)
    if not readiness["ready"]:
        return {
            "status": "not_ready",
            "analysis": analysis,
            "readiness_score": readiness["readiness_score"],
            "datasets": readiness["datasets"],
            "missing_requirements": readiness["missing_requirements"],
            "warnings": readiness["warnings"],
        }

    search_results = search_datasets_by_area(
        base_dir, area,
        dataset_types=requirements.get("required") + requirements.get("preferred", []),
        include_partial_overlap=True,
    )
    all_candidates = search_results["fully_covering"] + search_results["partially_overlapping"]

    if not all_candidates:
        return {
            "status": "not_ready",
            "analysis": analysis,
            "readiness_score": 0,
            "datasets": [],
            "missing_requirements": ["No datasets found for the selected area"],
            "warnings": [],
        }

    ranking = rank_datasets(all_candidates, area, analysis, top_n=5)
    recommended = ranking["recommended"]

    datasets_info = []
    for rec in recommended:
        ds = next((d for d in all_candidates if d["dataset_id"] == rec["dataset_id"]), None)
        if not ds:
            continue

        dataset_dir = Path(base_dir) / ds.get("location", "")
        files = []
        if dataset_dir.exists():
            from backend.app.ingestion.catalog import get_dataset_files
            file_records = get_dataset_files(base_dir, ds["dataset_id"])
            for f in file_records:
                files.append({
                    "file_id": f.get("id"),
                    "path": f"{ds.get('location')}/{f.get('file_name')}",
                    "role": f.get("file_role"),
                    "type": f.get("format"),
                    "spatial": bool(f.get("spatial")),
                })

        datasets_info.append({
            "dataset_id": ds["dataset_id"],
            "dataset_type": ds.get("dataset_type"),
            "role": "primary",
            "location": ds.get("location"),
            "coverage_percentage": ds.get("coverage_percentage"),
            "quality_score": ds.get("quality_score"),
            "usable": ds["usable"],
            "files": files,
        })

    return {
        "status": "ready",
        "analysis": analysis,
        "area": area,
        "datasets": datasets_info,
        "recommendations": [r["reasons"] for r in recommended],
        "warnings": [w for r in recommended for w in r.get("warnings", [])],
    }
