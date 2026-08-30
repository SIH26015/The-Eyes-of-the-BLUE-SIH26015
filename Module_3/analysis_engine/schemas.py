from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional


class AnalysisRequest(BaseModel):
    dataset_id: int
    analysis: str = "terrain"
    options: Optional[Dict[str, Any]] = None


class AnalysisResult(BaseModel):
    analysis_id: str
    status: str
    dataset_id: int
    dataset_name: str
    dataset_type: str
    analysis_type: str
    terrain: Optional[Dict[str, Any]] = None
    spatial: Optional[Dict[str, Any]] = None
    outputs: Optional[Dict[str, Any]] = None
    warnings: List[str] = []
    errors: List[str] = []


class AnalysisError(BaseModel):
    code: str
    message: str
    dataset_id: Optional[int] = None


class AnalysisListItem(BaseModel):
    analysis_id: str
    dataset_id: int
    dataset_name: str
    dataset_type: str
    analysis_type: str
    status: str
    created_at: str


class AnalysisOutputFile(BaseModel):
    filename: str
    path: str
    format: str
    exists: bool


class AnalysisPreviewRequest(BaseModel):
    layer: str

