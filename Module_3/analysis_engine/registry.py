from typing import Dict, Any, List, Optional
from pathlib import Path
import json
import os


ANALYSIS_NOT_FOUND = "ANALYSIS_NOT_FOUND"
ANALYSIS_RESULT_INVALID = "ANALYSIS_RESULT_INVALID"
ANALYSIS_OUTPUT_MISSING = "ANALYSIS_OUTPUT_MISSING"
ANALYSIS_FILE_NOT_ALLOWED = "ANALYSIS_FILE_NOT_ALLOWED"
ANALYSIS_PREVIEW_NOT_FOUND = "ANALYSIS_PREVIEW_NOT_FOUND"

ALLOWED_ANALYSIS_LAYERS = {"slope", "aspect", "hillshade"}
ALLOWED_ANALYSIS_FILES = {"slope.tif", "aspect.tif", "hillshade.tif", "result.json"}


class AnalysisResultRegistry:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.output_root = self.base_dir / "data" / "analysis"

    def list_results(self, dataset_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.output_root.exists():
            return []

        results = []
        for analysis_dir in self.output_root.iterdir():
            if not analysis_dir.is_dir():
                continue
            result_path = analysis_dir / "result.json"
            if not result_path.exists():
                continue
            try:
                result = _safe_read_json(result_path)
                if dataset_id is not None and result.get("dataset_id") != dataset_id:
                    continue
                results.append(result)
            except Exception:
                continue
        return results

    def get_result(self, analysis_id: str) -> Dict[str, Any]:
        analysis_dir = self._safe_analysis_dir(analysis_id)
        if analysis_dir is None:
            return {"error": ANALYSIS_NOT_FOUND, "message": "Analysis not found"}

        result_path = analysis_dir / "result.json"
        if not result_path.exists():
            return {"error": ANALYSIS_RESULT_INVALID, "message": "Analysis result is missing or invalid"}

        result = _safe_read_json(result_path)
        if result is None:
            return {"error": ANALYSIS_RESULT_INVALID, "message": "Analysis result is not valid JSON"}

        outputs = {}
        for layer in ALLOWED_ANALYSIS_FILES:
            file_path = analysis_dir / layer
            if file_path.exists():
                outputs[layer] = {
                    "path": str(file_path.relative_to(self.base_dir)),
                    "exists": True,
                }
        result["outputs"] = outputs
        return result

    def get_output_path(self, analysis_id: str, filename: str) -> Optional[str]:
        analysis_dir = self._safe_analysis_dir(analysis_id)
        if analysis_dir is None:
            return None

        safe_name = Path(filename).name
        if safe_name not in ALLOWED_ANALYSIS_FILES:
            return None

        file_path = analysis_dir / safe_name
        if not file_path.exists():
            return None
        return str(file_path)

    def get_preview_path(self, analysis_id: str, layer: str) -> Optional[str]:
        if layer not in ALLOWED_ANALYSIS_LAYERS:
            return None
        return self.get_output_path(analysis_id, f"{layer}.tif")

    def _safe_analysis_dir(self, analysis_id: str) -> Optional[Path]:
        try:
            analysis_id = Path(analysis_id).name
        except Exception:
            return None

        analysis_dir = self.output_root / analysis_id
        try:
            resolved = analysis_dir.resolve()
            if not str(resolved).startswith(str(self.output_root.resolve())):
                return None
        except Exception:
            return None

        if not resolved.exists() or not resolved.is_dir():
            return None
        return resolved


def _safe_read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None
