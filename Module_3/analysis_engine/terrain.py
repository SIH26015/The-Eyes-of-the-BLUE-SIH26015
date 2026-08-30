from typing import Dict, Any, Optional
import numpy as np
from pathlib import Path
import math
import rasterio.crs


class TerrainAnalyzer:
    def __init__(self, raster_info: Dict[str, Any]):
        data = raster_info["data"]
        if isinstance(data, dict) and "primary" in data:
            self.data = data["primary"]
        else:
            self.data = data
        self.width = raster_info["width"]
        self.height = raster_info["height"]
        self.resolution = raster_info["resolution"]
        self.nodata = raster_info["nodata"]
        self.bounds = raster_info["bounds"]
        self.crs = raster_info["crs"]

    def analyze(self, compute_slope: bool = True, compute_aspect: bool = True, compute_hillshade: bool = True) -> Dict[str, Any]:
        result = {
            "elevation": self._elevation_stats(),
            "spatial": {
                "bounds": self.bounds,
                "crs": self.crs,
                "resolution": self.resolution,
                "width": self.width,
                "height": self.height,
            },
            "arrays": {},
        }

        slope_array = None
        aspect_array = None

        if compute_slope:
            slope_array = self._compute_slope()
            result["slope"] = self._array_stats(slope_array, "slope")
            result["arrays"]["slope"] = slope_array

        if compute_aspect:
            aspect_array = self._compute_aspect()
            result["aspect"] = {
                "available": True,
                "min": float(np.nanmin(aspect_array)),
                "max": float(np.nanmax(aspect_array)),
                "mean": float(np.nanmean(aspect_array)),
            }
            result["arrays"]["aspect"] = aspect_array

        if compute_hillshade and slope_array is not None and aspect_array is not None:
            hillshade = self._compute_hillshade(slope_array, aspect_array)
            result["hillshade"] = {
                "available": True,
                "min": float(np.nanmin(hillshade)),
                "max": float(np.nanmax(hillshade)),
                "mean": float(np.nanmean(hillshade)),
            }
            result["arrays"]["hillshade"] = hillshade
        else:
            result["hillshade"] = {"available": False}

        return result

    def _elevation_stats(self) -> Dict[str, Any]:
        arr = self.data
        if hasattr(arr, "compressed"):
            valid = arr.compressed()
        else:
            valid = arr[~arr.mask] if hasattr(arr, "mask") and arr.mask.any() else arr

        if len(valid) == 0:
            return {
                "min": None,
                "max": None,
                "mean": None,
                "valid_pixels": 0,
                "nodata_pixels": self.width * self.height,
            }

        return {
            "min": float(np.min(valid)),
            "max": float(np.max(valid)),
            "mean": float(np.mean(valid)),
            "valid_pixels": int(len(valid)),
            "nodata_pixels": int(self.width * self.height - len(valid)),
        }

    def _get_resolution_meters(self) -> tuple[float, float]:
        res_x = self.resolution["x"]
        res_y = self.resolution["y"]
        
        is_geographic = False
        if self.crs:
            try:
                crs_obj = rasterio.crs.CRS.from_string(self.crs)
                is_geographic = crs_obj.is_geographic
            except Exception:
                if "4326" in str(self.crs):
                    is_geographic = True

        if is_geographic:
            center_lat = (self.bounds["south"] + self.bounds["north"]) / 2.0
            meters_per_deg_lat = 111320.0
            meters_per_deg_lon = 111320.0 * math.cos(math.radians(center_lat))
            res_x = res_x * meters_per_deg_lon
            res_y = res_y * meters_per_deg_lat
            
        return res_x, res_y

    def _compute_slope(self) -> np.ndarray:
        arr = self._to_array()
        res_x, res_y = self._get_resolution_meters()
        dx, dy = np.gradient(arr, res_x, res_y)
        slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
        slope_deg = np.degrees(slope_rad)
        return self._mask_nodata(slope_deg)

    def _compute_aspect(self) -> np.ndarray:
        arr = self._to_array()
        res_x, res_y = self._get_resolution_meters()
        dx, dy = np.gradient(arr, res_x, res_y)
        aspect_rad = np.arctan2(dy, -dx)
        aspect_deg = np.degrees(aspect_rad)
        aspect_deg = (aspect_deg + 360) % 360
        return self._mask_nodata(aspect_deg)

    def _compute_hillshade(self, slope: np.ndarray, aspect: np.ndarray, azimuth: float = 315.0, altitude: float = 45.0) -> np.ndarray:
        slope_rad = np.radians(slope)
        aspect_rad = np.radians(aspect)
        azimuth_rad = np.radians(azimuth)
        altitude_rad = np.radians(altitude)

        hillshade = (
            np.cos(altitude_rad) * np.cos(slope_rad)
            + np.sin(altitude_rad) * np.sin(slope_rad) * np.cos(azimuth_rad - aspect_rad)
        )
        hillshade = np.clip(hillshade, 0, 1)
        return self._mask_nodata(hillshade)

    def _to_array(self) -> np.ndarray:
        if hasattr(self.data, "filled"):
            return self.data.filled(np.nan)
        if hasattr(self.data, "mask"):
            arr = self.data.copy()
            arr = np.where(arr.mask, np.nan, arr)
            return arr
        return self.data.copy()

    def _mask_nodata(self, arr: np.ndarray) -> np.ndarray:
        if hasattr(self.data, "mask"):
            return np.where(self.data.mask, np.nan, arr)
        if self.nodata is not None:
            return np.where(np.isnan(self.data) if isinstance(self.data, np.ma.MaskedArray) else False, np.nan, arr)
        return arr

    def _array_stats(self, arr: np.ndarray, name: str) -> Dict[str, Any]:
        valid = arr[~np.isnan(arr)]
        if len(valid) == 0:
            return {
                "min": None,
                "max": None,
                "mean": None,
                "valid_pixels": 0,
                "nodata_pixels": int(arr.size),
            }
        return {
            "min": float(np.min(valid)),
            "max": float(np.max(valid)),
            "mean": float(np.mean(valid)),
            "valid_pixels": int(len(valid)),
            "nodata_pixels": int(arr.size - len(valid)),
        }
