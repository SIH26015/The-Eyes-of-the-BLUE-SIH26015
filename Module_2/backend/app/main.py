from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Dict, Any
from .api import datasets
from .analysis import engine as analysis_engine
from .analysis.schemas import AnalysisRequest, AnalysisResult
from .analysis.registry import AnalysisResultRegistry, ANALYSIS_NOT_FOUND, ANALYSIS_RESULT_INVALID, ANALYSIS_FILE_NOT_ALLOWED

app = FastAPI(title="Spatial Data Import API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(datasets.router, prefix="/api/datasets", tags=["datasets"])


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/api/analysis/terrain", response_model=Dict[str, Any])
def run_terrain_analysis(request: AnalysisRequest):
    base_dir = str(datasets.BASE_DIR)
    eng = analysis_engine.AnalysisEngine(base_dir)
    result = eng.run_analysis(request.dataset_id, request.analysis, request.options)
    return result


@app.post("/api/analysis/ndvi", response_model=Dict[str, Any])
def run_ndvi_analysis(request: AnalysisRequest):
    base_dir = str(datasets.BASE_DIR)
    eng = analysis_engine.AnalysisEngine(base_dir)
    result = eng.run_analysis(request.dataset_id, request.analysis, request.options)
    return result


@app.get("/api/analysis/results")
def list_analysis_results(dataset_id: int = None):
    registry = AnalysisResultRegistry(str(datasets.BASE_DIR))
    results = registry.list_results(dataset_id=dataset_id)
    return {"results": results}


@app.get("/api/analysis/results/{analysis_id}")
def get_analysis_result(analysis_id: str):
    registry = AnalysisResultRegistry(str(datasets.BASE_DIR))
    result = registry.get_result(analysis_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@app.get("/api/analysis/results/{analysis_id}/files/{filename}")
def get_analysis_output_file(analysis_id: str, filename: str):
    registry = AnalysisResultRegistry(str(datasets.BASE_DIR))
    file_path = registry.get_output_path(analysis_id, filename)
    if file_path is None:
        raise HTTPException(status_code=404, detail="File not found or not allowed")
    return FileResponse(file_path, filename=filename)


@app.get("/api/analysis/results/{analysis_id}/preview/{layer}")
def get_analysis_preview(analysis_id: str, layer: str):
    registry = AnalysisResultRegistry(str(datasets.BASE_DIR))
    file_path = registry.get_preview_path(analysis_id, layer)
    if file_path is None:
        raise HTTPException(status_code=404, detail="Preview not found or invalid layer")
    return FileResponse(file_path, filename=f"{layer}.tif")


BASE_DIR = Path(__file__).resolve().parent.parent.parent
frontend_path = BASE_DIR / "frontend"

if frontend_path.exists():
    @app.get("/data-import")
    async def data_import_page():
        return FileResponse(str(frontend_path / "data-import.html"))

    @app.get("/data-catalog")
    async def data_catalog_page():
        return FileResponse(str(frontend_path / "data-catalog.html"))

    @app.get("/")
    async def root_page():
        return FileResponse(str(frontend_path / "data-import.html"))

    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
