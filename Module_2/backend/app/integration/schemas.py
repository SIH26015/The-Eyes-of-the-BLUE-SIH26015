from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional


class BoundsModel(BaseModel):
    west: float
    south: float
    east: float
    north: float


class AreaSearchRequest(BaseModel):
    bounds: BoundsModel
    dataset_types: Optional[List[str]] = None
    include_partial_overlap: bool = True


class ReadinessRequest(BaseModel):
    area: BoundsModel
    analysis: str


class RecommendRequest(BaseModel):
    area: BoundsModel
    analysis: Optional[str] = None
    dataset_type: Optional[str] = None
    top_n: int = 5


class CompatibilityRequest(BaseModel):
    dataset_ids: List[int]


class TemporalPairsRequest(BaseModel):
    area: Optional[BoundsModel] = None
    dataset_type: str
    min_temporal_difference_days: int = 30


class PrepareAnalysisRequest(BaseModel):
    area: BoundsModel
    analysis: str
    dataset_type: Optional[str] = None


class CapabilitiesRequest(BaseModel):
    area: BoundsModel


class AnalysisDatasetFile(BaseModel):
    name: str
    path: str
    type: str
    role: str
    exists: bool
    size: Optional[int] = None


class AnalysisDataset(BaseModel):
    dataset_id: int
    dataset_name: str
    dataset_type: str
    theme: str
    tile: str
    version: str
    status: str
    file_path: str
    directory_exists: bool
    manifest_exists: bool
    manifest_valid: bool
    bounds: Optional[Dict[str, Any]] = None
    resolution: Optional[str] = None
    format: Optional[str] = None
    crs: Optional[str] = None
    platform: Optional[str] = None
    sensor: Optional[str] = None
    files: List[AnalysisDatasetFile] = []
    manifest: Dict[str, Any] = {}
    metadata: Dict[str, Any] = {}
    usable: bool = False
    ready_for_analysis: bool = False
    errors: List[str] = []
    warnings: List[str] = []


class AnalysisHandoffError(BaseModel):
    dataset_id: int
    code: str
    message: str
