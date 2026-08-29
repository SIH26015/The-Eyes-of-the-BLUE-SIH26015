from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from pydantic import BaseModel, Field, ConfigDict


class DatasetType(str, Enum):
    DEM = "dem"
    SATELLITE = "satellite"
    RAINFALL = "rainfall"
    TEMPERATURE = "temperature"
    GEO_PHOTOS = "geo_photos"
    LAND_USE = "land_use"
    VEGETATION = "vegetation"
    WATER_BODIES = "water_bodies"


class BlockStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    NOT_REQUIRED = "not_required"
    LOCKED = "locked"


class RequirementStatus(str, Enum):
    REQUIRED = "required"
    SATISFIED = "satisfied"
    PARTIAL = "partial"
    NOT_STARTED = "not_started"


class BBox(BaseModel):
    min_lat: float = Field(ge=-90, le=90)
    max_lat: float = Field(ge=-90, le=90)
    min_lon: float = Field(ge=-180, le=180)
    max_lon: float = Field(ge=-180, le=180)

    def __str__(self) -> str:
        return f"({self.min_lat}, {self.min_lon}) → ({self.max_lat}, {self.max_lon})"


class StudyArea(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: Optional[str] = None
    bbox: BBox
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SourceInfo(BaseModel):
    primary: Optional[str] = None
    alternative: Optional[str] = None
    backup: Optional[str] = None


class DataRequirement(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    study_area_id: str
    dataset_type: DatasetType
    status: RequirementStatus = RequirementStatus.REQUIRED

    temporal: Dict[str, Any] = Field(default_factory=dict)
    spatial_coverage: str = "entire_watershed"
    source: SourceInfo = Field(default_factory=SourceInfo)
    required_bands: List[str] = Field(default_factory=list)
    purpose: Optional[str] = None

    expected_count: int = 0
    collected_count: int = 0

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GridBlock(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    study_area_id: str
    lat_range: tuple[float, float]
    lon_range: tuple[float, float]

    status: BlockStatus = BlockStatus.MISSING
    locked: bool = False

    datasets: Dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AcquisitionGrid(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    study_area_id: str
    name: str
    grid_size_lat: float
    grid_size_lon: float
    blocks: List[GridBlock] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CollectionSession(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    date: date
    collector: str
    source: str
    dataset_type: DatasetType
    files_collected: int = 0
    area: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CatalogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    dataset_type: DatasetType
    tile_or_block: Optional[str] = None
    bounds: Optional[BBox] = None
    crs: Optional[str] = None
    resolution: Optional[str] = None
    date_collected: Optional[date] = None
    source_used: Optional[str] = None
    session_id: Optional[str] = None
    dataset_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
