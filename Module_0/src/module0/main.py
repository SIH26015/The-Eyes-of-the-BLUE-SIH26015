from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import List, Optional

from module0.database import init_db, SessionLocal
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
from module0.planner import DataAcquisitionPlanner
from module0.ingest import Module2Ingest

app = FastAPI(title="Module 0 — Data Acquisition & Research Tracker")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    with DataAcquisitionPlanner() as planner:
        study_areas = planner.list_study_areas()
        sessions = planner.list_sessions()
        catalog = planner.list_catalog()

        coverage_data = {}
        queue_data = []
        for sa in study_areas:
            coverage_data[sa.id] = planner.calculate_coverage(sa.id)
            queue_data.extend(planner.get_acquisition_queue(sa.id))

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "study_areas": study_areas,
                "sessions": sessions[:10],
                "catalog_count": len(catalog),
                "coverage_data": coverage_data,
                "queue_data": queue_data[:10],
            },
        )


@app.get("/api/study-areas", response_class=JSONResponse)
async def api_list_study_areas():
    with DataAcquisitionPlanner() as planner:
        return [sa.model_dump(mode="json") for sa in planner.list_study_areas()]


@app.post("/api/study-areas", response_class=JSONResponse)
async def api_create_study_area(study_area: StudyArea):
    with DataAcquisitionPlanner() as planner:
        return planner.create_study_area(study_area).model_dump(mode="json")


@app.get("/api/study-areas/{study_area_id}", response_class=JSONResponse)
async def api_get_study_area(study_area_id: str):
    with DataAcquisitionPlanner() as planner:
        sa = planner.get_study_area(study_area_id)
        if not sa:
            raise HTTPException(status_code=404, detail="Study area not found")
        return sa.model_dump(mode="json")


@app.get("/api/study-areas/{study_area_id}/requirements", response_class=JSONResponse)
async def api_list_requirements(study_area_id: str):
    with DataAcquisitionPlanner() as planner:
        return [r.model_dump(mode="json") for r in planner.list_requirements(study_area_id)]


@app.post("/api/requirements", response_class=JSONResponse)
async def api_create_requirement(req: DataRequirement):
    with DataAcquisitionPlanner() as planner:
        return planner.create_requirement(req).model_dump(mode="json")


@app.get("/api/study-areas/{study_area_id}/coverage", response_class=JSONResponse)
async def api_get_coverage(study_area_id: str):
    with DataAcquisitionPlanner() as planner:
        return planner.calculate_coverage(study_area_id)


@app.get("/api/study-areas/{study_area_id}/queue", response_class=JSONResponse)
async def api_get_queue(study_area_id: str, limit: int = 20):
    with DataAcquisitionPlanner() as planner:
        return planner.get_acquisition_queue(study_area_id, limit)


@app.post("/api/sessions", response_class=JSONResponse)
async def api_create_session(session: CollectionSession):
    with DataAcquisitionPlanner() as planner:
        return planner.create_session(session).model_dump(mode="json")


@app.get("/api/sessions", response_class=JSONResponse)
async def api_list_sessions(dataset_type: Optional[str] = None):
    with DataAcquisitionPlanner() as planner:
        dt = DatasetType(dataset_type) if dataset_type else None
        return [s.model_dump(mode="json") for s in planner.list_sessions(dt)]


@app.post("/api/ingest/module2", response_class=JSONResponse)
async def api_ingest_module2(entries: List[dict]):
    with Module2Ingest() as ingest:
        catalog_entries = ingest.ingest_metadata(entries)
        return {"ingested": len(catalog_entries)}


@app.get("/api/catalog", response_class=JSONResponse)
async def api_list_catalog(dataset_type: Optional[str] = None):
    with DataAcquisitionPlanner() as planner:
        dt = DatasetType(dataset_type) if dataset_type else None
        return [c.model_dump(mode="json") for c in planner.list_catalog(dt)]


@app.post("/api/grids", response_class=JSONResponse)
async def api_create_grid(grid: AcquisitionGrid):
    with DataAcquisitionPlanner() as planner:
        return planner.create_acquisition_grid(grid).model_dump(mode="json")


@app.get("/api/grids", response_class=JSONResponse)
async def api_list_grids(study_area_id: Optional[str] = None):
    with DataAcquisitionPlanner() as planner:
        grids = planner.list_grids(study_area_id)
        return [g.model_dump(mode="json") for g in grids]


@app.patch("/api/blocks/{block_id}", response_class=JSONResponse)
async def api_update_block(block_id: str, status: str, locked: bool = False):
    with DataAcquisitionPlanner() as planner:
        block_status = BlockStatus(status)
        block = planner.update_block_status(block_id, block_status, locked)
        if not block:
            raise HTTPException(status_code=404, detail="Block not found")
        return block.model_dump(mode="json")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
