from pathlib import Path
from typing import Dict, Any, Optional


def read_geotiff_metadata(tif_file: Path) -> Dict[str, Any]:
    tif_file = Path(tif_file)
    if not tif_file.exists() or not tif_file.is_file():
        return {"_error": "file_not_found"}

    try:
        import rasterio
    except ImportError:
        return {
            "crs": None,
            "bounds": None,
            "width": None,
            "height": None,
            "resolution": None,
            "count": None,
            "dtype": None,
            "driver": None,
            "_note": "rasterio not available",
        }

    try:
        with rasterio.open(tif_file) as src:
            bounds = src.bounds
            return {
                "crs": src.crs.to_string() if src.crs else None,
                "bounds": (bounds.left, bounds.bottom, bounds.right, bounds.top),
                "width": src.width,
                "height": src.height,
                "resolution": (
                    abs(src.res[0]) if src.res and len(src.res) > 0 else None
                ),
                "count": src.count,
                "dtype": src.dtypes[0] if src.dtypes else None,
                "driver": src.driver,
            }
    except Exception:
        return {"_error": "invalid_geotiff"}
