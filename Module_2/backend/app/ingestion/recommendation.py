from typing import Dict, Any, List, Optional


RECOMMENDATION_WEIGHTS = {
    "coverage": 0.35,
    "quality": 0.25,
    "resolution": 0.20,
    "metadata_confidence": 0.10,
    "recency": 0.10,
}


def score_dataset(
    dataset: Dict[str, Any],
    query_bounds: Dict[str, float],
    analysis_type: str,
) -> Dict[str, Any]:
    reasons = []
    warnings = []
    scores = {}

    coverage = dataset.get("coverage_percentage", 0.0)
    coverage_score = min(100.0, coverage)
    scores["coverage"] = coverage_score
    if coverage >= 99.0:
        reasons.append("100% area coverage")
    elif coverage >= 80.0:
        reasons.append(f"{coverage}% area coverage")
    else:
        warnings.append(f"Low coverage: {coverage}%")

    quality = dataset.get("quality_score") or dataset.get("quality", {}).get("score") or 0
    quality_score = min(100.0, max(0.0, quality))
    scores["quality"] = quality_score
    if quality_score >= 80:
        reasons.append("High quality score")
    elif quality_score < 50:
        warnings.append("Low quality score")

    resolution = dataset.get("resolution")
    resolution_score = 50.0
    if resolution:
        res_str = str(resolution).lower()
        if "arc sec" in res_str or "m" in res_str:
            try:
                num = float(res_str.split()[0].replace("m", "").replace("arc", "").strip())
                if num <= 1:
                    resolution_score = 100.0
                    reasons.append("High resolution available")
                elif num <= 10:
                    resolution_score = 80.0
                elif num <= 30:
                    resolution_score = 60.0
                else:
                    resolution_score = 40.0
            except (ValueError, IndexError):
                resolution_score = 50.0
    scores["resolution"] = resolution_score

    confidence = 50.0
    classification = dataset.get("classification", {})
    if classification.get("confidence") == "high":
        confidence = 100.0
        reasons.append("High metadata confidence")
    elif classification.get("confidence") == "medium":
        confidence = 70.0
    elif classification.get("confidence") == "low":
        confidence = 30.0
        warnings.append("Low metadata confidence")
    scores["metadata_confidence"] = confidence

    recency = 50.0
    version = dataset.get("version", "")
    if version:
        import re
        match = re.search(r"v(\d+)", version, re.IGNORECASE)
        if match:
            ver_num = int(match.group(1))
            if ver_num >= 3:
                recency = 90.0
                reasons.append("Recent version available")
            elif ver_num >= 2:
                recency = 70.0
            else:
                recency = 50.0
    scores["recency"] = recency

    total_score = sum(scores.get(k, 0.0) * v for k, v in RECOMMENDATION_WEIGHTS.items())

    return {
        "score": round(total_score, 2),
        "scores": scores,
        "reasons": reasons,
        "warnings": warnings,
    }


def rank_datasets(
    datasets: List[Dict[str, Any]],
    query_bounds: Dict[str, float],
    analysis_type: str,
    top_n: int = 5,
) -> Dict[str, Any]:
    scored = []
    for ds in datasets:
        result = score_dataset(ds, query_bounds, analysis_type)
        scored.append({
            "dataset_id": ds.get("dataset_id") or ds.get("id"),
            "dataset_name": ds.get("dataset_name"),
            "dataset_type": ds.get("dataset_type"),
            "score": result["score"],
            "reasons": result["reasons"],
            "warnings": result["warnings"],
            "coverage_percentage": ds.get("coverage_percentage", 0.0),
            "quality_score": ds.get("quality_score") or ds.get("quality", {}).get("score") or 0,
            "resolution": ds.get("resolution"),
            "location": ds.get("location") or ds.get("file_path"),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    recommended = scored[:top_n]
    alternatives = scored[top_n:]

    return {
        "recommended": recommended,
        "alternatives": alternatives,
    }
