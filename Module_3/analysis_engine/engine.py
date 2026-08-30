from typing import Dict, Any, Optional, Callable
from Module_3.analysis_engine.dataset_loader import AnalysisDatasetLoader, ANALYSIS_DATASET_NOT_READY, PRIMARY_SPATIAL_FILE_MISSING, UNSUPPORTED_DATASET_TYPE, RASTER_OPEN_FAILED
from Module_3.analysis_engine.terrain import TerrainAnalyzer
from Module_3.analysis_engine.vegetation import VegetationAnalyzer
from Module_3.analysis_engine.results import AnalysisResultWriter
from Module_3.analysis_engine.interfaces.dataset_provider import DatasetProvider
import uuid
from datetime import datetime


class AnalysisEngine:
    def __init__(self, base_dir: str, dataset_provider: Optional[Callable[[int], Dict[str, Any]]] = None):
        self.base_dir = base_dir
        self.loader = AnalysisDatasetLoader(base_dir)
        self.writer = AnalysisResultWriter(base_dir)
        self._dataset_provider = dataset_provider

    def _get_dataset(self, dataset_id: int) -> Dict[str, Any]:
        if self._dataset_provider is None:
            raise RuntimeError(
                "AnalysisEngine requires a dataset_provider. "
                "Pass dataset_provider=get_analysis_dataset or equivalent when constructing."
            )
        return self._dataset_provider(dataset_id)

    def run_analysis(self, dataset_id: int, analysis_type: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        dataset_contract = self._get_dataset(dataset_id)
        loaded = self.loader.load(dataset_contract)
        if not loaded["success"]:
            return {
                "analysis_id": str(uuid.uuid4()),
                "status": "failed",
                "dataset_id": dataset_id,
                "dataset_name": dataset_contract.get("dataset_name", "Unknown"),
                "dataset_type": dataset_contract.get("dataset_type", "Unknown"),
                "analysis_type": analysis_type,
                "errors": [loaded.get("message", "Analysis failed")],
                "warnings": [],
            }

        analysis_id = str(uuid.uuid4())
        raster_info = loaded["raster_info"]
        dataset_type = dataset_contract.get("dataset_type", "").upper()
        created_at = datetime.utcnow().isoformat()

        try:
            if analysis_type == "terrain" and dataset_type in {"DEM", "DSM", "UNKNOWN"}:
                result = self._run_terrain(analysis_id, dataset_contract, raster_info, options, created_at)
            elif analysis_type == "ndvi" and dataset_type in {"SATELLITE", "MULTISPECTRAL", "UNKNOWN"}:
                result = self._run_ndvi(analysis_id, dataset_contract, raster_info, options, created_at)
            else:
                return {
                    "analysis_id": analysis_id,
                    "status": "failed",
                    "dataset_id": dataset_id,
                    "dataset_name": dataset_contract.get("dataset_name", "Unknown"),
                    "dataset_type": dataset_type,
                    "analysis_type": analysis_type,
                    "errors": [f"Analysis type '{analysis_type}' not supported for dataset type '{dataset_type}'"],
                    "warnings": [],
                }
        except Exception as e:
            return {
                "analysis_id": analysis_id,
                "status": "failed",
                "dataset_id": dataset_id,
                "dataset_name": dataset_contract.get("dataset_name", "Unknown"),
                "dataset_type": dataset_type,
                "analysis_type": analysis_type,
                "errors": [str(e)],
                "warnings": [],
            }

        self.writer.write_result(analysis_id, result)
        terrain = result.get("terrain", {})
        terrain.pop("arrays", None)
        result["terrain"] = terrain
        return result

    def _run_terrain(self, analysis_id: str, dataset_contract: Dict[str, Any], raster_info: Dict[str, Any], options: Optional[Dict[str, Any]], created_at: str) -> Dict[str, Any]:
        options = options or {}
        compute_slope = options.get("slope", True)
        compute_aspect = options.get("aspect", True)
        compute_hillshade = options.get("hillshade", True)

        analyzer = TerrainAnalyzer(raster_info)
        terrain_result = analyzer.analyze(
            compute_slope=compute_slope,
            compute_aspect=compute_aspect,
            compute_hillshade=compute_hillshade,
        )

        source_profile = {
            "crs": raster_info.get("crs"),
            "transform": raster_info.get("transform"),
            "nodata": raster_info.get("nodata"),
            "width": raster_info.get("width"),
            "height": raster_info.get("height"),
        }

        outputs = {}
        if compute_slope:
            slope_path = self.writer.write_raster(analysis_id, "slope.tif", terrain_result["arrays"]["slope"], source_profile)
            outputs["slope"] = {
                "path": str(slope_path.relative_to(self.base_dir)) if slope_path else None,
                "format": "GeoTIFF",
                "exists": slope_path is not None,
            }
        if compute_aspect:
            aspect_path = self.writer.write_raster(analysis_id, "aspect.tif", terrain_result["arrays"]["aspect"], source_profile)
            outputs["aspect"] = {
                "path": str(aspect_path.relative_to(self.base_dir)) if aspect_path else None,
                "format": "GeoTIFF",
                "exists": aspect_path is not None,
            }
        if compute_hillshade:
            hs_path = self.writer.write_raster(analysis_id, "hillshade.tif", terrain_result["arrays"]["hillshade"], source_profile)
            outputs["hillshade"] = {
                "path": str(hs_path.relative_to(self.base_dir)) if hs_path else None,
                "format": "GeoTIFF",
                "exists": hs_path is not None,
            }

        return {
            "analysis_id": analysis_id,
            "status": "completed",
            "dataset_id": dataset_contract.get("dataset_id"),
            "dataset_name": dataset_contract.get("dataset_name"),
            "dataset_type": dataset_contract.get("dataset_type"),
            "analysis_type": "terrain",
            "created_at": created_at,
            "source": {
                "dataset_name": dataset_contract.get("dataset_name"),
                "dataset_type": dataset_contract.get("dataset_type"),
                "source_file": dataset_contract.get("files", [{}])[0].get("full_path") if dataset_contract.get("files") else None,
                "crs": raster_info.get("crs"),
                "bounds": raster_info.get("bounds"),
            },
            "statistics": {
                "elevation": terrain_result.get("elevation"),
                "slope": terrain_result.get("slope"),
                "aspect": terrain_result.get("aspect"),
                "hillshade": terrain_result.get("hillshade"),
            },
            "terrain": terrain_result,
            "spatial": terrain_result.get("spatial"),
            "outputs": outputs,
            "warnings": [],
            "errors": [],
        }

    def _run_ndvi(self, analysis_id: str, dataset_contract: Dict[str, Any], raster_info: Dict[str, Any], options: Optional[Dict[str, Any]], created_at: str) -> Dict[str, Any]:
        red_band = options.get("red_band", 1) if options else 1
        nir_band = options.get("nir_band", 2) if options else 2

        analyzer = VegetationAnalyzer(raster_info, red_band=red_band, nir_band=nir_band)
        veg_result = analyzer.analyze()

        source_profile = {
            "crs": raster_info.get("crs"),
            "transform": raster_info.get("transform"),
            "nodata": raster_info.get("nodata"),
            "width": raster_info.get("width"),
            "height": raster_info.get("height"),
        }

        ndvi_path = None
        if "ndvi" in veg_result.get("arrays", {}):
            ndvi_path = self.writer.write_raster(analysis_id, "ndvi.tif", veg_result["arrays"]["ndvi"], source_profile)

        outputs = {}
        if ndvi_path:
            outputs["ndvi"] = {
                "path": str(ndvi_path.relative_to(self.base_dir)) if ndvi_path else None,
                "format": "GeoTIFF",
                "exists": ndvi_path is not None,
            }

        return {
            "analysis_id": analysis_id,
            "status": "completed",
            "dataset_id": dataset_contract.get("dataset_id"),
            "dataset_name": dataset_contract.get("dataset_name"),
            "dataset_type": dataset_contract.get("dataset_type"),
            "analysis_type": "ndvi",
            "created_at": created_at,
            "source": {
                "dataset_name": dataset_contract.get("dataset_name"),
                "dataset_type": dataset_contract.get("dataset_type"),
                "source_file": dataset_contract.get("files", [{}])[0].get("full_path") if dataset_contract.get("files") else None,
                "crs": raster_info.get("crs"),
                "bounds": raster_info.get("bounds"),
                "red_band": red_band,
                "nir_band": nir_band,
            },
            "statistics": {
                "ndvi": veg_result.get("ndvi"),
            },
            "distribution": veg_result.get("distribution"),
            "spatial": veg_result.get("spatial"),
            "outputs": outputs,
            "warnings": [],
            "errors": [],
        }
