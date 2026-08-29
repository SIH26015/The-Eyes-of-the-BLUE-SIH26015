import json
from datetime import date
from typing import List, Optional
from sqlalchemy.orm import Session

from module0.database import SessionLocal, CatalogEntryDB
from module0.models import CatalogEntry, DatasetType
from module0.planner import DataAcquisitionPlanner


class Module2Ingest:
    def __init__(self):
        self.planner = DataAcquisitionPlanner()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.planner.close()
        return False

    def ingest_metadata(self, entries: List[dict]) -> List[CatalogEntry]:
        catalog_entries = []
        for entry in entries:
            cat_entry = CatalogEntry(
                id=entry.get("id") or f"cat-{date.today().isoformat()}-{hash(entry.get('filename',''))}",
                filename=entry["filename"],
                dataset_type=DatasetType(entry["dataset_type"]),
                tile_or_block=entry.get("tile_or_block"),
                bounds=entry.get("bounds"),
                crs=entry.get("crs"),
                resolution=entry.get("resolution"),
                date_collected=entry.get("date_collected"),
                source_used=entry.get("source_used"),
                session_id=entry.get("session_id"),
                dataset_metadata=entry.get("metadata", {}),
            )
            self.planner.ingest_catalog_entry(cat_entry)
            catalog_entries.append(cat_entry)
        return catalog_entries

    def ingest_from_file(self, file_path: str) -> List[CatalogEntry]:
        with open(file_path, "r") as f:
            entries = json.load(f)
        return self.ingest_metadata(entries)

    def update_requirement_from_catalog(self, study_area_id: str, dataset_type: DatasetType):
        db = SessionLocal()
        try:
            req = db.query(DataRequirementDB).filter(
                DataRequirementDB.study_area_id == study_area_id,
                DataRequirementDB.dataset_type == dataset_type,
            ).first()
            if not req:
                return

            count = db.query(CatalogEntryDB).filter(
                CatalogEntryDB.dataset_type == dataset_type,
            ).count()

            req.collected_count = count
            if count >= req.expected_count and req.expected_count > 0:
                req.status = RequirementStatus.SATISFIED
            elif count > 0:
                req.status = RequirementStatus.PARTIAL
            db.commit()
        finally:
            db.close()
