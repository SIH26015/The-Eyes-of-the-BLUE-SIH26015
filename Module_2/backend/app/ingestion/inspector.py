from pathlib import Path
from typing import List, Dict, Any, Set


SUPPORTED_EXTENSIONS = {
    ".xml",
    ".tif",
    ".tiff",
    ".shp",
    ".shx",
    ".dbf",
    ".prj",
    ".cpg",
    ".geojson",
    ".json",
    ".csv",
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
    ".nc",
    ".hdf5",
    ".h5",
    ".zarr",
    ".parquet",
    ".feather",
    ".xlsx",
    ".txt",
    ".pdf",
}

SHAPEFILE_GROUP_EXTENSIONS = {".shp", ".shx", ".dbf", ".prj", ".cpg"}


def _is_shapefile_group(files: List[Path], file: Path) -> bool:
    if file.suffix.lower() != ".shp":
        return False
    stem = file.stem
    parent = file.parent
    required = {".shp", ".shx", ".dbf"}
    present = {f.suffix.lower() for f in files if f.parent == parent and f.stem == stem}
    return required.issubset(present)


def _primary_extensions() -> Set[str]:
    return {".tif", ".tiff", ".shp", ".geojson", ".json", ".nc", ".hdf5", ".h5", ".zarr", ".csv"}


def inspect_dataset(dataset_path: str) -> Dict[str, Any]:
    dataset_path = Path(dataset_path)
    if not dataset_path.exists():
        return {"files": [], "primary_files": [], "xml_files": [], "shapefile_groups": [], "supported_files": 0}

    all_files = [p for p in dataset_path.rglob("*") if p.is_file()]
    supported = [p for p in all_files if p.suffix.lower() in SUPPORTED_EXTENSIONS]
    primary = [p for p in supported if p.suffix.lower() in _primary_extensions()]
    xml_files = [p for p in supported if p.suffix.lower() == ".xml"]
    shapefile_groups = [p for p in supported if _is_shapefile_group(supported, p)]

    return {
        "files": supported,
        "primary_files": primary,
        "xml_files": xml_files,
        "shapefile_groups": shapefile_groups,
        "supported_files": len(supported),
    }
