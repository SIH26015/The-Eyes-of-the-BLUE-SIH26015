from pathlib import Path
from typing import Optional, Dict, Any
from backend.app.ingestion.catalog import query_one


def is_exact_duplicate(base_dir: str, original_filename: str, file_hash: str) -> bool:
    row = query_one(base_dir, file_hash=file_hash)
    if row:
        return True
    row = query_one(base_dir, original_filename=original_filename)
    if row:
        return True
    return False


def check_duplicate(base_dir: str, metadata: Dict[str, Any]) -> Optional[str]:
    dataset_name = metadata.get("dataset_name")
    dataset_type = metadata.get("dataset_type")
    tile = metadata.get("tile")
    version = metadata.get("version")

    if not all([dataset_name, dataset_type, tile, version]):
        return None

    row = query_one(base_dir, dataset_name, dataset_type, tile, version)
    if row:
        return "ALREADY_EXISTS"
    return None
