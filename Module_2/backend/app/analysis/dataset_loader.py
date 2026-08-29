from typing import Dict, Any, Optional, List
from pathlib import Path
import rasterio
from rasterio.errors import RasterioIOError


ANALYSIS_DATASET_NOT_READY = "ANALYSIS_DATASET_NOT_READY"
PRIMARY_SPATIAL_FILE_MISSING = "PRIMARY_SPATIAL_FILE_MISSING"
UNSUPPORTED_DATASET_TYPE = "UNSUPPORTED_DATASET_TYPE"
RASTER_OPEN_FAILED = "RASTER_OPEN_FAILED"
INVALID_RASTER = "INVALID_RASTER"


class AnalysisDatasetLoader:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)

    def load(self, dataset_contract: Dict[str, Any]) -> Dict[str, Any]:
        if not dataset_contract.get("ready_for_analysis"):
            return {
                "success": False,
                "error": ANALYSIS_DATASET_NOT_READY,
                "message": "Dataset is not ready for analysis",
                "dataset_id": dataset_contract.get("dataset_id"),
            }

        dataset_type = dataset_contract.get("dataset_type", "").upper()
        if dataset_type not in {"DEM", "DSM", "UNKNOWN"}:
            return {
                "success": False,
                "error": UNSUPPORTED_DATASET_TYPE,
                "message": f"Unsupported dataset type for analysis: {dataset_type}",
                "dataset_id": dataset_contract.get("dataset_id"),
            }

        primary_file = self._find_primary_file(dataset_contract)
        if not primary_file:
            return {
                "success": False,
                "error": PRIMARY_SPATIAL_FILE_MISSING,
                "message": "No primary spatial file found in dataset",
                "dataset_id": dataset_contract.get("dataset_id"),
            }

        raster_info = self._open_raster(primary_file)
        if not raster_info:
            return {
                "success": False,
                "error": RASTER_OPEN_FAILED,
                "message": f"Failed to open raster file: {primary_file}",
                "dataset_id": dataset_contract.get("dataset_id"),
            }

        return {
            "success": True,
            "dataset_contract": dataset_contract,
            "primary_file": primary_file,
            "raster_info": raster_info,
        }

    def _find_primary_file(self, dataset_contract: Dict[str, Any]) -> Optional[str]:
        files = dataset_contract.get("files", [])
        for f in files:
            if f.get("role") == "primary" and f.get("exists"):
                path = f.get("full_path") or f.get("path")
                if path:
                    full_path = Path(path)
                    if not full_path.is_absolute():
                        full_path = self.base_dir / full_path
                    if full_path.exists():
                        return str(full_path)

        dataset_dir = dataset_contract.get("file_path", "")
        if dataset_dir:
            dir_path = self.base_dir / dataset_dir
            if dir_path.exists():
                for ext in [".tif", ".tiff", ".TIF", ".TIFF"]:
                    candidates = list(dir_path.rglob(f"*{ext}"))
                    for candidate in candidates:
                        if candidate.is_file():
                            return str(candidate)
        return None

    def _open_raster(self, file_path: str) -> Optional[Dict[str, Any]]:
        try:
            with rasterio.open(file_path) as src:
                data = src.read(1, masked=True)
                bounds = src.bounds
                crs = src.crs.to_string() if src.crs else None
                transform = src.transform
                resolution = (
                    abs(transform.a),
                    abs(transform.e),
                )

                if src.count > 1:
                    bands = src.read(masked=True)
                    result_data = {
                        "bands": [bands[i] for i in range(src.count)],
                        "count": src.count,
                        "dtype": str(src.dtypes[0]),
                        "primary": data,
                    }
                else:
                    result_data = {
                        "count": 1,
                        "dtype": str(src.dtypes[0]),
                        "primary": data,
                    }

                return {
                    "data": result_data,
                    "width": src.width,
                    "height": src.height,
                    "count": src.count,
                    "dtype": str(src.dtypes[0]),
                    "crs": crs,
                    "bounds": {
                        "west": bounds.left,
                        "south": bounds.bottom,
                        "east": bounds.right,
                        "north": bounds.top,
                    },
                    "resolution": {
                        "x": resolution[0],
                        "y": resolution[1],
                    },
                    "nodata": src.nodata,
                    "transform": transform,
                }
        except (RasterioIOError, Exception):
            return None
