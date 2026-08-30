import zipfile
from pathlib import Path
from typing import Dict, Any
import json
import pytest
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from functools import partial

from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.api import datasets as datasets_module
from backend.app.ingestion.pipeline import ingest_dataset
from Module_3.analysis_engine.engine import AnalysisEngine
from Module_3.analysis_engine.dataset_loader import (
    ANALYSIS_DATASET_NOT_READY,
    PRIMARY_SPATIAL_FILE_MISSING,
    UNSUPPORTED_DATASET_TYPE,
    RASTER_OPEN_FAILED,
)
from Module_3.analysis_engine.registry import (
    AnalysisResultRegistry,
    ANALYSIS_NOT_FOUND,
    ANALYSIS_RESULT_INVALID,
    ANALYSIS_FILE_NOT_ALLOWED,
)
from backend.app.integration.analysis_data_provider import get_analysis_dataset


def _make_engine(base_dir: str, **kwargs) -> AnalysisEngine:
    return AnalysisEngine(base_dir, dataset_provider=partial(get_analysis_dataset, base_dir), **kwargs)


@pytest.fixture
def tmp_workspace(tmp_path):
    base = tmp_path / "workspace"
    base.mkdir()
    (base / "data" / "incoming").mkdir(parents=True)
    (base / "data" / "processing").mkdir(parents=True)
    (base / "data" / "catalog").mkdir(parents=True)
    (base / "data" / "raw").mkdir(parents=True)
    (base / "data" / "analysis").mkdir(parents=True)
    return base


def _create_bhuvan_zip(tmp_workspace, name="analysis_test.zip"):
    zip_path = tmp_workspace / "data" / "incoming" / name
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="e43g">
    <Data_Identification_Information>
        <Name_of_the_Dataset>Analysis_Test_V1</Name_of_the_Dataset>
        <Theme>Terrain</Theme>
        <Keywords>Cartosat-1,DEM,Stereodata,India,ISRO,NRSC</Keywords>
        <Data_Type>Elevation</Data_Type>
    </Data_Identification_Information>
    <Coverage>
        <Upper_left>X = 72E, Y = 19N</Upper_left>
        <Upper_right>X = 73E, Y = 19N</Upper_right>
        <Lower_right>X = 73E, Y = 18N</Lower_right>
        <Lower_left>X = 72E, Y = 18N</Lower_left>
    </Coverage>
    <Citation><Lineage><Tile_Name>e43g</Tile_Name><Resolution>1 arc sec</Resolution><File_Format>Geotiff</File_Format></Lineage></Citation>
    <Dataset_Topic_Category><Data_Identification_topic_category>Digital Elevation Model</Data_Identification_topic_category></Dataset_Topic_Category>
    <For_Image_Data>
        <Name_of_the_Satellite>Cartosat-1</Name_of_the_Satellite>
        <Sensor>PAN(2.5m) Stereo Data</Sensor>
        <File_Format>Geotiff</File_Format>
        <Bits_per_Pixel>16bit</Bits_per_Pixel>
        <Spatial_Resolution>1arc sec</Spatial_Resolution>
    </For_Image_Data>
</metadata>
""")
        data = np.ones((10, 10), dtype=np.float32) * 100
        data[3:7, 3:7] = 500
        transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
        with rasterio.open(
            str(tmp_workspace / "dem.tif"),
            "w",
            driver="GTiff",
            height=10,
            width=10,
            count=1,
            dtype=data.dtype,
            crs="EPSG:4326",
            transform=transform,
        ) as dst:
            dst.write(data, 1)
        with open(str(tmp_workspace / "dem.tif"), "rb") as f:
            zf.writestr("dem.tif", f.read())
    return zip_path


class TestTerrainAnalysis:
    def test_terrain_analysis_returns_elevation_statistics(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain")

        assert analysis["status"] == "completed"
        assert "terrain" in analysis
        elev = analysis["terrain"]["elevation"]
        assert elev["min"] == 100.0
        assert elev["max"] == 500.0
        assert elev["mean"] == pytest.approx(164.0, rel=0.01)
        assert elev["valid_pixels"] == 100

    def test_terrain_analysis_calculates_slope(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain", {"slope": True, "aspect": False, "hillshade": False})

        assert analysis["status"] == "completed"
        assert "slope" in analysis["terrain"]
        slope = analysis["terrain"]["slope"]
        assert slope["min"] is not None
        assert slope["max"] is not None
        assert slope["mean"] is not None

    def test_terrain_analysis_calculates_aspect(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain", {"slope": False, "aspect": True, "hillshade": False})

        assert analysis["status"] == "completed"
        assert "aspect" in analysis["terrain"]
        aspect = analysis["terrain"]["aspect"]
        assert aspect["available"] is True
        assert aspect["min"] >= 0
        assert aspect["max"] <= 360

    def test_terrain_analysis_generates_hillshade(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain", {"slope": True, "aspect": True, "hillshade": True})

        assert analysis["status"] == "completed"
        assert "hillshade" in analysis["terrain"]
        hs = analysis["terrain"]["hillshade"]
        assert hs["available"] is True
        assert 0 <= hs["min"] <= 1
        assert 0 <= hs["max"] <= 1

    def test_analysis_outputs_are_created(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain")

        assert analysis["status"] == "completed"
        assert "outputs" in analysis
        analysis_id = analysis["analysis_id"]
        result_path = tmp_workspace / "data" / "analysis" / analysis_id / "result.json"
        assert result_path.exists()

    def test_analysis_does_not_modify_original_dataset(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        dataset_dir = Path(tmp_workspace) / result["location"]
        original_files = set(p.name for p in dataset_dir.rglob("*") if p.is_file())

        engine = _make_engine(str(tmp_workspace))
        engine.run_analysis(dataset_id, "terrain")

        current_files = set(p.name for p in dataset_dir.rglob("*") if p.is_file())
        assert original_files == current_files

    def test_analysis_rejects_non_ready_dataset(self, tmp_workspace):
        contract = {
            "dataset_id": 999,
            "dataset_name": "Missing",
            "dataset_type": "DEM",
            "ready_for_analysis": False,
            "files": [],
        }
        loader = AnalysisEngine(str(tmp_workspace)).loader
        result = loader.load(contract)
        assert result["success"] is False
        assert result["error"] == ANALYSIS_DATASET_NOT_READY

    def test_analysis_rejects_missing_primary_file(self, tmp_workspace):
        contract = {
            "dataset_id": 1,
            "dataset_name": "Test",
            "dataset_type": "DEM",
            "ready_for_analysis": True,
            "file_path": "data/raw/terrain/DEM/E43G/V1",
            "files": [],
        }
        loader = AnalysisEngine(str(tmp_workspace)).loader
        result = loader.load(contract)
        assert result["success"] is False
        assert result["error"] == PRIMARY_SPATIAL_FILE_MISSING

    def test_analysis_rejects_non_dem_dataset(self, tmp_workspace):
        contract = {
            "dataset_id": 1,
            "dataset_name": "Test",
            "dataset_type": "LULC",
            "ready_for_analysis": True,
            "file_path": "data/raw/terrain/LULC/E43G/V1",
            "files": [],
        }
        loader = AnalysisEngine(str(tmp_workspace)).loader
        result = loader.load(contract)
        assert result["success"] is False
        assert result["error"] == UNSUPPORTED_DATASET_TYPE

    def test_analysis_endpoint_end_to_end(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/analysis/terrain", json={
                "dataset_id": dataset_id,
                "analysis": "terrain",
                "options": {"slope": True, "aspect": True, "hillshade": True},
            })
        finally:
            datasets_module.BASE_DIR = original_base

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["analysis_type"] == "terrain"
        assert "terrain" in body
        assert "spatial" in body
        assert "outputs" in body


class TestPersistedAnalysisOutputs:
    def test_terrain_analysis_creates_slope_tif(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain")
        analysis_id = analysis["analysis_id"]

        slope_path = tmp_workspace / "data" / "analysis" / analysis_id / "slope.tif"
        assert slope_path.exists()

    def test_terrain_analysis_creates_aspect_tif(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain")
        analysis_id = analysis["analysis_id"]

        aspect_path = tmp_workspace / "data" / "analysis" / analysis_id / "aspect.tif"
        assert aspect_path.exists()

    def test_terrain_analysis_creates_hillshade_tif(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain")
        analysis_id = analysis["analysis_id"]

        hillshade_path = tmp_workspace / "data" / "analysis" / analysis_id / "hillshade.tif"
        assert hillshade_path.exists()

    def test_output_rasters_preserve_source_dimensions(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain")
        analysis_id = analysis["analysis_id"]

        analysis_dir = tmp_workspace / "data" / "analysis" / analysis_id
        for filename in ["slope.tif", "aspect.tif", "hillshade.tif"]:
            with rasterio.open(analysis_dir / filename) as src:
                assert src.width == 10
                assert src.height == 10

    def test_output_rasters_preserve_crs(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain")
        analysis_id = analysis["analysis_id"]

        analysis_dir = tmp_workspace / "data" / "analysis" / analysis_id
        for filename in ["slope.tif", "aspect.tif", "hillshade.tif"]:
            with rasterio.open(analysis_dir / filename) as src:
                assert src.crs.to_string() == "EPSG:4326"

    def test_output_rasters_preserve_transform(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain")
        analysis_id = analysis["analysis_id"]

        analysis_dir = tmp_workspace / "data" / "analysis" / analysis_id
        source_transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
        for filename in ["slope.tif", "aspect.tif", "hillshade.tif"]:
            with rasterio.open(analysis_dir / filename) as src:
                assert src.transform == source_transform


class TestAnalysisRegistry:
    def test_result_json_contains_analysis_id(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain")
        analysis_id = analysis["analysis_id"]

        result_path = tmp_workspace / "data" / "analysis" / analysis_id / "result.json"
        saved = json.loads(result_path.read_text())
        assert "analysis_id" in saved
        assert saved["analysis_id"] == analysis_id

    def test_result_json_contains_output_metadata(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain")
        analysis_id = analysis["analysis_id"]

        result_path = tmp_workspace / "data" / "analysis" / analysis_id / "result.json"
        saved = json.loads(result_path.read_text())
        assert "outputs" in saved
        assert "slope" in saved["outputs"]
        assert saved["outputs"]["slope"]["format"] == "GeoTIFF"

    def test_analysis_results_can_be_listed(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        engine.run_analysis(dataset_id, "terrain")

        registry = AnalysisResultRegistry(str(tmp_workspace))
        results = registry.list_results()
        assert len(results) == 1
        assert results[0]["dataset_id"] == dataset_id

    def test_results_can_be_filtered_by_dataset_id(self, tmp_workspace):
        zip1 = _create_bhuvan_zip(tmp_workspace, "test1.zip")
        r1 = ingest_dataset(str(zip1), str(tmp_workspace))
        assert r1["status"] == "success"

        import shutil
        shutil.rmtree(tmp_workspace / "data" / "incoming")
        (tmp_workspace / "data" / "incoming").mkdir(parents=True, exist_ok=True)

        zip2 = tmp_workspace / "data" / "incoming" / "test2.zip"
        with zipfile.ZipFile(zip2, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="f43u">
    <Data_Identification_Information>
        <Name_of_the_Dataset>Analysis_Test_V2</Name_of_the_Dataset>
        <Theme>Terrain</Theme>
        <Keywords>Cartosat-1,DEM,Stereodata,India,ISRO,NRSC</Keywords>
        <Data_Type>Elevation</Data_Type>
    </Data_Identification_Information>
    <Coverage>
        <Upper_left>X = 73E, Y = 20N</Upper_left>
        <Upper_right>X = 74E, Y = 20N</Upper_right>
        <Lower_right>X = 74E, Y = 19N</Lower_right>
        <Lower_left>X = 73E, Y = 19N</Lower_left>
    </Coverage>
    <Citation><Lineage><Tile_Name>f43u</Tile_Name><Resolution>1 arc sec</Resolution><File_Format>Geotiff</File_Format></Lineage></Citation>
    <Dataset_Topic_Category><Data_Identification_topic_category>Digital Elevation Model</Data_Identification_topic_category></Dataset_Topic_Category>
    <For_Image_Data>
        <Name_of_the_Satellite>Cartosat-1</Name_of_the_Satellite>
        <Sensor>PAN(2.5m) Stereo Data</Sensor>
        <File_Format>Geotiff</File_Format>
        <Bits_per_Pixel>16bit</Bits_per_Pixel>
        <Spatial_Resolution>1arc sec</Spatial_Resolution>
    </For_Image_Data>
</metadata>
""")
            data = np.ones((10, 10), dtype=np.float32) * 200
            data[2:8, 2:8] = 800
            transform = from_bounds(73.0, 19.0, 74.0, 20.0, 10, 10)
            with rasterio.open(
                str(tmp_workspace / "dem2.tif"),
                "w",
                driver="GTiff",
                height=10,
                width=10,
                count=1,
                dtype=data.dtype,
                crs="EPSG:4326",
                transform=transform,
            ) as dst:
                dst.write(data, 1)
            with open(str(tmp_workspace / "dem2.tif"), "rb") as f:
                zf.writestr("dem.tif", f.read())

        r2 = ingest_dataset(str(zip2), str(tmp_workspace))
        assert r2["status"] == "success"

        engine = _make_engine(str(tmp_workspace))
        engine.run_analysis(r1["dataset_id"], "terrain")
        engine.run_analysis(r2["dataset_id"], "terrain")

        registry = AnalysisResultRegistry(str(tmp_workspace))
        results = registry.list_results(dataset_id=r1["dataset_id"])
        assert len(results) == 1
        assert results[0]["dataset_id"] == r1["dataset_id"]

    def test_specific_analysis_can_be_retrieved(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain")
        analysis_id = analysis["analysis_id"]

        registry = AnalysisResultRegistry(str(tmp_workspace))
        retrieved = registry.get_result(analysis_id)
        assert retrieved["analysis_id"] == analysis_id
        assert retrieved["dataset_id"] == dataset_id

    def test_unknown_analysis_returns_error(self, tmp_workspace):
        registry = AnalysisResultRegistry(str(tmp_workspace))
        result = registry.get_result("nonexistent-id")
        assert "error" in result
        assert result["error"] == ANALYSIS_NOT_FOUND

    def test_valid_output_file_can_be_retrieved(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain")
        analysis_id = analysis["analysis_id"]

        registry = AnalysisResultRegistry(str(tmp_workspace))
        file_path = registry.get_output_path(analysis_id, "slope.tif")
        assert file_path is not None
        assert Path(file_path).exists()

    def test_path_traversal_is_rejected(self, tmp_workspace):
        registry = AnalysisResultRegistry(str(tmp_workspace))
        file_path = registry.get_output_path("../../../etc/passwd", "slope.tif")
        assert file_path is None

    def test_invalid_filename_is_rejected(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        engine = _make_engine(str(tmp_workspace))
        analysis = engine.run_analysis(dataset_id, "terrain")
        analysis_id = analysis["analysis_id"]

        registry = AnalysisResultRegistry(str(tmp_workspace))
        file_path = registry.get_output_path(analysis_id, "../../../etc/passwd")
        assert file_path is None

    def test_missing_analysis_directory_does_not_crash_listing(self, tmp_workspace):
        registry = AnalysisResultRegistry(str(tmp_workspace))
        results = registry.list_results()
        assert results == []

    def test_api_list_results(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            engine = _make_engine(str(tmp_workspace))
            engine.run_analysis(dataset_id, "terrain")

            response = client.get("/api/analysis/results")
            assert response.status_code == 200
            body = response.json()
            assert "results" in body
            assert len(body["results"]) == 1
        finally:
            datasets_module.BASE_DIR = original_base

    def test_api_get_specific_result(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            engine = _make_engine(str(tmp_workspace))
            analysis = engine.run_analysis(dataset_id, "terrain")
            analysis_id = analysis["analysis_id"]

            client = TestClient(app)
            response = client.get(f"/api/analysis/results/{analysis_id}")
            assert response.status_code == 200
            body = response.json()
            assert body["analysis_id"] == analysis_id
        finally:
            datasets_module.BASE_DIR = original_base

    def test_api_get_unknown_result_returns_404(self, tmp_workspace):
        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.get("/api/analysis/results/nonexistent-id")
            assert response.status_code == 404
        finally:
            datasets_module.BASE_DIR = original_base

    def test_api_get_output_file(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            engine = _make_engine(str(tmp_workspace))
            analysis = engine.run_analysis(dataset_id, "terrain")
            analysis_id = analysis["analysis_id"]

            client = TestClient(app)
            response = client.get(f"/api/analysis/results/{analysis_id}/files/slope.tif")
            assert response.status_code == 200
        finally:
            datasets_module.BASE_DIR = original_base

    def test_api_get_invalid_file_returns_404(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            engine = _make_engine(str(tmp_workspace))
            analysis = engine.run_analysis(dataset_id, "terrain")
            analysis_id = analysis["analysis_id"]

            client = TestClient(app)
            response = client.get(f"/api/analysis/results/{analysis_id}/files/../../../etc/passwd")
            assert response.status_code == 404
        finally:
            datasets_module.BASE_DIR = original_base

    def test_api_get_preview(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            engine = _make_engine(str(tmp_workspace))
            analysis = engine.run_analysis(dataset_id, "terrain")
            analysis_id = analysis["analysis_id"]

            client = TestClient(app)
            response = client.get(f"/api/analysis/results/{analysis_id}/preview/slope")
            assert response.status_code == 200
        finally:
            datasets_module.BASE_DIR = original_base

    def test_api_get_invalid_preview_layer_returns_404(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        dataset_id = result["dataset_id"]

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            engine = _make_engine(str(tmp_workspace))
            analysis = engine.run_analysis(dataset_id, "terrain")
            analysis_id = analysis["analysis_id"]

            client = TestClient(app)
            response = client.get(f"/api/analysis/results/{analysis_id}/preview/invalid_layer")
            assert response.status_code == 404
        finally:
            datasets_module.BASE_DIR = original_base


def _create_satellite_tif(tmp_workspace, name="satellite.tif", bands=4):
    tif_path = tmp_workspace / "data" / "incoming" / name
    data = np.ones((bands, 10, 10), dtype=np.float32)
    data[0] = data[0] * 0.2
    data[1] = data[1] * 0.3
    data[2] = data[2] * 0.5
    data[3] = data[3] * 0.8
    transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
    with rasterio.open(
        str(tif_path),
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=bands,
        dtype=np.float32,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data)
    return tif_path


class TestNdviAnalysis:
    def test_ndvi_calculation_basic(self, tmp_workspace):
        from Module_3.analysis_engine.vegetation import VegetationAnalyzer

        red = np.ones((10, 10), dtype=np.float32) * 0.2
        nir = np.ones((10, 10), dtype=np.float32) * 0.8
        raster_info = {
            "data": {"bands": [red, nir], "count": 2, "dtype": "float32", "primary": red},
            "width": 10,
            "height": 10,
            "resolution": {"x": 0.000278, "y": 0.000278},
            "nodata": None,
            "bounds": {"west": 72.0, "south": 18.0, "east": 73.0, "north": 19.0},
            "crs": "EPSG:4326",
        }
        analyzer = VegetationAnalyzer(raster_info, red_band=1, nir_band=2)
        result = analyzer.analyze()

        assert "ndvi" in result
        ndvi = result["ndvi"]
        assert ndvi["min"] == pytest.approx(0.6, abs=0.01)
        assert ndvi["max"] == pytest.approx(0.6, abs=0.01)
        assert ndvi["mean"] == pytest.approx(0.6, abs=0.01)
        assert ndvi["valid_pixels"] == 100

    def test_ndvi_handles_division_by_zero(self, tmp_workspace):
        from Module_3.analysis_engine.vegetation import VegetationAnalyzer

        red = np.zeros((10, 10), dtype=np.float32)
        nir = np.zeros((10, 10), dtype=np.float32)
        raster_info = {
            "data": {"bands": [red, nir], "count": 2, "dtype": "float32", "primary": red},
            "width": 10,
            "height": 10,
            "resolution": {"x": 0.000278, "y": 0.000278},
            "nodata": None,
            "bounds": {"west": 72.0, "south": 18.0, "east": 73.0, "north": 19.0},
            "crs": "EPSG:4326",
        }
        analyzer = VegetationAnalyzer(raster_info, red_band=1, nir_band=2)
        result = analyzer.analyze()

        assert "ndvi" in result
        ndvi = result["ndvi"]
        assert ndvi["valid_pixels"] == 0

    def test_ndvi_distribution_categories(self, tmp_workspace):
        from Module_3.analysis_engine.vegetation import VegetationAnalyzer

        red = np.ones((10, 10), dtype=np.float32) * 0.3
        nir = np.ones((10, 10), dtype=np.float32) * 0.7
        raster_info = {
            "data": {"bands": [red, nir], "count": 2, "dtype": "float32", "primary": red},
            "width": 10,
            "height": 10,
            "resolution": {"x": 0.000278, "y": 0.000278},
            "nodata": None,
            "bounds": {"west": 72.0, "south": 18.0, "east": 73.0, "north": 19.0},
            "crs": "EPSG:4326",
        }
        analyzer = VegetationAnalyzer(raster_info, red_band=1, nir_band=2)
        result = analyzer.analyze()

        dist = result["distribution"]
        assert "very_low" in dist
        assert "low" in dist
        assert "moderate" in dist
        assert "high" in dist
        assert dist["total_valid"] == 100

    def test_ndvi_analysis_end_to_end(self, tmp_workspace):
        tif_path = _create_satellite_tif(tmp_workspace, "satellite.tif", bands=4)

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            with open(tif_path, "rb") as f:
                response = client.post(
                    "/api/datasets/upload",
                    files={"file": ("satellite.tif", f, "image/tiff")},
                )
            assert response.status_code == 200
            body = response.json()
            assert body["summary"]["processed"] == 1
            dataset_id = body["results"][0]["dataset_id"]

            response = client.post("/api/analysis/ndvi", json={
                "dataset_id": dataset_id,
                "analysis": "ndvi",
            })
        finally:
            datasets_module.BASE_DIR = original_base

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["analysis_type"] == "ndvi"
        assert "statistics" in body
        assert "ndvi" in body["statistics"]
        ndvi_stats = body["statistics"]["ndvi"]
        assert "min" in ndvi_stats
        assert "max" in ndvi_stats
        assert "mean" in ndvi_stats
        assert "median" in ndvi_stats
        assert "std" in ndvi_stats
