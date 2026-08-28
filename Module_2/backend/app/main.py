from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from .api import datasets

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
