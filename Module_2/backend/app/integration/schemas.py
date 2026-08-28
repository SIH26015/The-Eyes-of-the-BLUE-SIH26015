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
