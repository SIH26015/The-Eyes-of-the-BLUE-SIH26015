from typing import Dict, Any, Optional
import numpy as np
from pathlib import Path


class VegetationAnalyzer:
    def __init__(self, raster_info: Dict[str, Any], red_band: int = 4, nir_band: int = 8):
        self.data = raster_info["data"]
        self.width = raster_info["width"]
        self.height = raster_info["height"]
        self.resolution = raster_info["resolution"]
        self.nodata = raster_info.get("nodata")
        self.bounds = raster_info["bounds"]
        self.crs = raster_info["crs"]
        self.red_band = red_band - 1 if red_band > 0 else red_band
        self.nir_band = nir_band - 1 if nir_band > 0 else nir_band

    def analyze(self) -> Dict[str, Any]:
        red = self._extract_band(self.red_band)
        nir = self._extract_band(self.nir_band)

        ndvi = self._compute_ndvi(red, nir)
        stats = self._ndvi_statistics(ndvi)
        distribution = self._ndvi_distribution(ndvi)

        return {
            "ndvi": stats,
            "distribution": distribution,
            "spatial": {
                "bounds": self.bounds,
                "crs": self.crs,
                "resolution": self.resolution,
                "width": self.width,
                "height": self.height,
            },
            "arrays": {"ndvi": ndvi},
        }

    def _extract_band(self, band_index: int) -> np.ndarray:
        if isinstance(self.data, dict) and "bands" in self.data:
            bands = self.data["bands"]
            if band_index < len(bands):
                arr = bands[band_index]
                return self._to_array(arr)
        if self.data.ndim == 3 and self.data.shape[0] > 1:
            if band_index < self.data.shape[0]:
                arr = self.data[band_index]
                return self._to_array(arr)
        if self.data.ndim == 2:
            arr = self.data
            return self._to_array(arr)
        raise ValueError(f"Cannot extract band {band_index} from dataset with shape {self.data.shape}")

    def _compute_ndvi(self, red: np.ndarray, nir: np.ndarray) -> np.ndarray:
        red = red.astype(np.float32)
        nir = nir.astype(np.float32)
        denominator = nir + red
        ndvi = np.where(denominator == 0, np.nan, (nir - red) / denominator)
        mask = np.isnan(red) | np.isnan(nir)
        ndvi = np.where(mask, np.nan, ndvi)
        return ndvi

    def _ndvi_statistics(self, ndvi: np.ndarray) -> Dict[str, Any]:
        valid = ndvi[~np.isnan(ndvi)]
        if len(valid) == 0:
            return {
                "min": None,
                "max": None,
                "mean": None,
                "median": None,
                "std": None,
                "valid_pixels": 0,
                "nodata_pixels": int(ndvi.size),
            }
        return {
            "min": float(np.min(valid)),
            "max": float(np.max(valid)),
            "mean": float(np.mean(valid)),
            "median": float(np.median(valid)),
            "std": float(np.std(valid)),
            "valid_pixels": int(len(valid)),
            "nodata_pixels": int(ndvi.size - len(valid)),
        }

    def _ndvi_distribution(self, ndvi: np.ndarray) -> Dict[str, Any]:
        valid = ndvi[~np.isnan(ndvi)]
        if len(valid) == 0:
            return {
                "very_low": 0.0,
                "low": 0.0,
                "moderate": 0.0,
                "high": 0.0,
                "total_valid": 0,
            }

        total = len(valid)
        bins = [
            ("very_low", -1.0, 0.0),
            ("low", 0.0, 0.2),
            ("moderate", 0.2, 0.5),
            ("high", 0.5, 1.0),
        ]

        distribution = {}
        for label, low, high in bins:
            count = int(np.sum((valid >= low) & (valid < high)))
            distribution[label] = round((count / total) * 100, 2)

        distribution["total_valid"] = total
        return distribution

    def _to_array(self, arr) -> np.ndarray:
        if hasattr(arr, "filled"):
            return arr.filled(np.nan)
        if hasattr(arr, "mask"):
            arr = arr.copy()
            arr = np.where(arr.mask, np.nan, arr)
            return arr
        return np.array(arr, dtype=np.float32)
