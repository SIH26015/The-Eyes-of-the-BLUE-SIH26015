from typing import Dict, Any, Optional, List
from pathlib import Path
import json
import uuid
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from datetime import datetime


class AnalysisResultWriter:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.output_root = self.base_dir / "data" / "analysis"
        self.output_root.mkdir(parents=True, exist_ok=True)

    def write_result(self, analysis_id: str, result: Dict[str, Any]) -> Path:
        analysis_dir = self.output_root / analysis_id
        analysis_dir.mkdir(parents=True, exist_ok=True)

        result_path = analysis_dir / "result.json"
        result_path.write_text(json.dumps(result, indent=2, default=str))

        return result_path

    def write_output(self, analysis_id: str, filename: str, data: Any) -> Optional[Path]:
        analysis_dir = self.output_root / analysis_id
        analysis_dir.mkdir(parents=True, exist_ok=True)

        output_path = analysis_dir / filename
        try:
            if hasattr(data, "tofile"):
                data = np.array(data)
            np.save(str(output_path.with_suffix("")), np.array(data), allow_pickle=False)
            return output_path.with_suffix(".npy")
        except Exception:
            return None

    def write_raster(self, analysis_id: str, filename: str, data: np.ndarray, profile: Dict[str, Any]) -> Optional[Path]:
        analysis_dir = self.output_root / analysis_id
        analysis_dir.mkdir(parents=True, exist_ok=True)

        output_path = analysis_dir / filename
        try:
            out_profile = {
                "driver": "GTiff",
                "height": data.shape[0],
                "width": data.shape[1],
                "count": 1,
                "dtype": data.dtype,
                "crs": profile.get("crs"),
                "transform": profile.get("transform"),
                "nodata": profile.get("nodata"),
            }
            out_profile = {k: v for k, v in out_profile.items() if v is not None}

            with rasterio.open(str(output_path), "w", **out_profile) as dst:
                dst.write(data, 1)
            return output_path
        except Exception:
            return None

    def get_result(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        result_path = self.output_root / analysis_id / "result.json"
        if not result_path.exists():
            return None
        try:
            return json.loads(result_path.read_text())
        except Exception:
            return None

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
                result = json.loads(result_path.read_text())
                if dataset_id is not None and result.get("dataset_id") != dataset_id:
                    continue
                results.append(result)
            except Exception:
                continue
        return results
