import json
import uuid
from datetime import date, datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from module0.database import (
    SessionLocal,
    StudyAreaDB,
    DataRequirementDB,
    AcquisitionGridDB,
    GridBlockDB,
    CollectionSessionDB,
    CatalogEntryDB,
)
from module0.models import (
    StudyArea,
    DataRequirement,
    AcquisitionGrid,
    GridBlock,
    CollectionSession,
    CatalogEntry,
    DatasetType,
    BlockStatus,
    RequirementStatus,
    BBox,
    SourceInfo,
)


class DataAcquisitionPlanner:
    def __init__(self):
        self.db: Session = SessionLocal()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        self.db.close()

    def create_study_area(self, study_area: StudyArea) -> StudyArea:
        db_obj = StudyAreaDB(
            id=study_area.id,
            name=study_area.name,
            description=study_area.description,
            min_lat=study_area.bbox.min_lat,
            max_lat=study_area.bbox.max_lat,
            min_lon=study_area.bbox.min_lon,
            max_lon=study_area.bbox.max_lon,
        )
        self.db.add(db_obj)
        self.db.commit()
        self.db.refresh(db_obj)
        return self._to_study_area(db_obj)

    def get_study_area(self, study_area_id: str) -> Optional[StudyArea]:
        obj = self.db.query(StudyAreaDB).filter(StudyAreaDB.id == study_area_id).first()
        return self._to_study_area(obj) if obj else None

    def list_study_areas(self) -> List[StudyArea]:
        return [self._to_study_area(obj) for obj in self.db.query(StudyAreaDB).all()]

    def _to_study_area(self, obj: StudyAreaDB) -> StudyArea:
        return StudyArea(
            id=obj.id,
            name=obj.name,
            description=obj.description,
            bbox=BBox(
                min_lat=obj.min_lat,
                max_lat=obj.max_lat,
                min_lon=obj.min_lon,
                max_lon=obj.max_lon,
            ),
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )

    def create_requirement(self, req: DataRequirement) -> DataRequirement:
        db_obj = DataRequirementDB(
            id=req.id,
            study_area_id=req.study_area_id,
            dataset_type=req.dataset_type,
            status=req.status,
            temporal=json.dumps(req.temporal),
            spatial_coverage=req.spatial_coverage,
            source_primary=req.source.primary,
            source_alternative=req.source.alternative,
            source_backup=req.source.backup,
            required_bands=json.dumps(req.required_bands),
            purpose=req.purpose,
            expected_count=req.expected_count,
            collected_count=req.collected_count,
        )
        self.db.add(db_obj)
        self.db.commit()
        self.db.refresh(db_obj)
        return self._to_requirement(db_obj)

    def get_requirement(self, req_id: str) -> Optional[DataRequirement]:
        obj = self.db.query(DataRequirementDB).filter(DataRequirementDB.id == req_id).first()
        return self._to_requirement(obj) if obj else None

    def list_requirements(self, study_area_id: Optional[str] = None) -> List[DataRequirement]:
        q = self.db.query(DataRequirementDB)
        if study_area_id:
            q = q.filter(DataRequirementDB.study_area_id == study_area_id)
        return [self._to_requirement(obj) for obj in q.all()]

    def _to_requirement(self, obj: DataRequirementDB) -> DataRequirement:
        return DataRequirement(
            id=obj.id,
            study_area_id=obj.study_area_id,
            dataset_type=obj.dataset_type,
            status=obj.status,
            temporal=json.loads(obj.temporal),
            spatial_coverage=obj.spatial_coverage,
            source=SourceInfo(
                primary=obj.source_primary,
                alternative=obj.source_alternative,
                backup=obj.source_backup,
            ),
            required_bands=json.loads(obj.required_bands),
            purpose=obj.purpose,
            expected_count=obj.expected_count,
            collected_count=obj.collected_count,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )

    def create_acquisition_grid(self, grid: AcquisitionGrid) -> AcquisitionGrid:
        db_grid = AcquisitionGridDB(
            id=grid.id,
            study_area_id=grid.study_area_id,
            name=grid.name,
            grid_size_lat=grid.grid_size_lat,
            grid_size_lon=grid.grid_size_lon,
        )
        self.db.add(db_grid)
        for block in grid.blocks:
            db_block = GridBlockDB(
                id=block.id,
                study_area_id=block.study_area_id,
                grid_id=grid.id,
                lat_min=block.lat_range[0],
                lat_max=block.lat_range[1],
                lon_min=block.lon_range[0],
                lon_max=block.lon_range[1],
                status=block.status,
                locked=block.locked,
                datasets=json.dumps(block.datasets),
            )
            self.db.add(db_block)
        self.db.commit()
        return grid

    def get_grid(self, grid_id: str) -> Optional[AcquisitionGrid]:
        db_grid = self.db.query(AcquisitionGridDB).filter(AcquisitionGridDB.id == grid_id).first()
        if not db_grid:
            return None
        blocks = [
            GridBlock(
                id=b.id,
                study_area_id=b.study_area_id,
                lat_range=(b.lat_min, b.lat_max),
                lon_range=(b.lon_min, b.lon_max),
                status=b.status,
                locked=b.locked,
                datasets=json.loads(b.datasets),
                created_at=b.created_at,
                updated_at=b.updated_at,
            )
            for b in self.db.query(GridBlockDB).filter(GridBlockDB.grid_id == grid_id).all()
        ]
        return AcquisitionGrid(
            id=db_grid.id,
            study_area_id=db_grid.study_area_id,
            name=db_grid.name,
            grid_size_lat=db_grid.grid_size_lat,
            grid_size_lon=db_grid.grid_size_lon,
            blocks=blocks,
            created_at=db_grid.created_at,
        )

    def list_grids(self, study_area_id: Optional[str] = None) -> List[AcquisitionGrid]:
        q = self.db.query(AcquisitionGridDB)
        if study_area_id:
            q = q.filter(AcquisitionGridDB.study_area_id == study_area_id)
        return [self.get_grid(g.id) for g in q.all()]

    def update_block_status(self, block_id: str, status: BlockStatus, locked: bool = False) -> Optional[GridBlock]:
        db_block = self.db.query(GridBlockDB).filter(GridBlockDB.id == block_id).first()
        if not db_block:
            return None
        db_block.status = status
        db_block.locked = locked
        db_block.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(db_block)
        return GridBlock(
            id=db_block.id,
            study_area_id=db_block.study_area_id,
            lat_range=(db_block.lat_min, db_block.lat_max),
            lon_range=(db_block.lon_min, db_block.lon_max),
            status=db_block.status,
            locked=db_block.locked,
            datasets=json.loads(db_block.datasets),
            created_at=db_block.created_at,
            updated_at=db_block.updated_at,
        )

    def create_session(self, session: CollectionSession) -> CollectionSession:
        db_obj = CollectionSessionDB(
            id=session.id,
            date=session.date,
            collector=session.collector,
            source=session.source,
            dataset_type=session.dataset_type,
            files_collected=session.files_collected,
            area=session.area,
            notes=session.notes,
        )
        self.db.add(db_obj)
        self.db.commit()
        return session

    def list_sessions(self, dataset_type: Optional[DatasetType] = None) -> List[CollectionSession]:
        q = self.db.query(CollectionSessionDB)
        if dataset_type:
            q = q.filter(CollectionSessionDB.dataset_type == dataset_type)
        return [
            CollectionSession(
                id=s.id,
                date=s.date,
                collector=s.collector,
                source=s.source,
                dataset_type=s.dataset_type,
                files_collected=s.files_collected,
                area=s.area,
                notes=s.notes,
                created_at=s.created_at,
            )
            for s in q.order_by(CollectionSessionDB.date.desc()).all()
        ]

    def ingest_catalog_entry(self, entry: CatalogEntry) -> CatalogEntry:
        db_obj = CatalogEntryDB(
            id=entry.id,
            filename=entry.filename,
            dataset_type=entry.dataset_type,
            tile_or_block=entry.tile_or_block,
            bounds_min_lat=entry.bounds.min_lat if entry.bounds else None,
            bounds_max_lat=entry.bounds.max_lat if entry.bounds else None,
            bounds_min_lon=entry.bounds.min_lon if entry.bounds else None,
            bounds_max_lon=entry.bounds.max_lon if entry.bounds else None,
            crs=entry.crs,
            resolution=entry.resolution,
            date_collected=entry.date_collected,
            source_used=entry.source_used,
            session_id=entry.session_id,
            dataset_metadata=json.dumps(entry.dataset_metadata),
        )
        self.db.add(db_obj)
        self.db.commit()
        return entry

    def list_catalog(self, dataset_type: Optional[DatasetType] = None) -> List[CatalogEntry]:
        q = self.db.query(CatalogEntryDB)
        if dataset_type:
            q = q.filter(CatalogEntryDB.dataset_type == dataset_type)
        return [
            CatalogEntry(
                id=e.id,
                filename=e.filename,
                dataset_type=e.dataset_type,
                tile_or_block=e.tile_or_block,
                bounds=BBox(
                    min_lat=e.bounds_min_lat,
                    max_lat=e.bounds_max_lat,
                    min_lon=e.bounds_min_lon,
                    max_lon=e.bounds_max_lon,
                ) if e.bounds_min_lat is not None else None,
                crs=e.crs,
                resolution=e.resolution,
                date_collected=e.date_collected,
                source_used=e.source_used,
                session_id=e.session_id,
                dataset_metadata=json.loads(e.dataset_metadata),
                created_at=e.created_at,
            )
            for e in q.all()
        ]

    def calculate_coverage(self, study_area_id: str) -> Dict[str, Any]:
        requirements = self.db.query(DataRequirementDB).filter(
            DataRequirementDB.study_area_id == study_area_id
        ).all()

        total_expected = sum(r.expected_count for r in requirements)
        total_collected = sum(r.collected_count for r in requirements)

        by_type = {}
        for r in requirements:
            pct = (r.collected_count / r.expected_count * 100) if r.expected_count > 0 else 0.0
            by_type[r.dataset_type.value] = {
                "expected": r.expected_count,
                "collected": r.collected_count,
                "missing": max(0, r.expected_count - r.collected_count),
                "coverage_pct": round(pct, 1),
                "status": r.status.value,
            }

        return {
            "study_area_id": study_area_id,
            "total_expected": total_expected,
            "total_collected": total_collected,
            "total_missing": max(0, total_expected - total_collected),
            "overall_coverage_pct": round((total_collected / total_expected * 100) if total_expected > 0 else 0.0, 1),
            "by_type": by_type,
        }

    def get_acquisition_queue(self, study_area_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        requirements = self.db.query(DataRequirementDB).filter(
            DataRequirementDB.study_area_id == study_area_id,
            DataRequirementDB.status != RequirementStatus.SATISFIED,
        ).all()

        queue = []
        for r in requirements:
            missing = max(0, r.expected_count - r.collected_count)
            if missing <= 0:
                continue
            queue.append({
                "requirement_id": r.id,
                "dataset_type": r.dataset_type.value,
                "missing": missing,
                "source_primary": r.source_primary,
                "source_alternative": r.source_alternative,
                "purpose": r.purpose,
            })

        queue.sort(key=lambda x: x["missing"], reverse=True)
        return queue[:limit]
