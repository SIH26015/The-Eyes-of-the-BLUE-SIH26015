import zipfile
from pathlib import Path
from typing import Dict, Any
import json
import pytest
import numpy as np
import rasterio
from rasterio.transform import from_bounds

from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.api import datasets as datasets_module
from backend.app.ingestion.pipeline import ingest_dataset
from backend.app.ingestion.catalog import soft_delete_dataset
from backend.app.integration.analysis_data_provider import (
    get_analysis_dataset,
    DATASET_DIRECTORY_MISSING,
    DATASET_DELETED,
    DATASET_QUARANTINED,
)


@pytest.fixture
def tmp_workspace(tmp_path):
    base = tmp_path / "workspace"
    base.mkdir()
    (base / "data" / "incoming").mkdir(parents=True)
    (base / "data" / "processing").mkdir(parents=True)
    (base / "data" / "catalog").mkdir(parents=True)
    (base / "data" / "raw").mkdir(parents=True)
    return base


def _create_bhuvan_zip(tmp_workspace, name="test.zip", tileno="f43u", theme="Terrain", dtype="Elevation"):
    zip_path = tmp_workspace / "data" / "incoming" / name
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("metadata.xml", f"""<?xml version="1.0"?>
<metadata tileno="{tileno}">
    <Data_Identification_Information>
        <Name_of_the_Dataset>{name.stem if hasattr(name, 'stem') else name.replace('.zip','')}_V1</Name_of_the_Dataset>
        <Theme>{theme}</Theme>
        <Keywords>Cartosat-1,DEM,Stereodata,India,ISRO,NRSC</Keywords>
        <Data_Type>{dtype}</Data_Type>
    </Data_Identification_Information>
    <Coverage>
        <Upper_left>X = 73E, Y = 20N</Upper_left>
        <Upper_right>X = 74E, Y = 20N</Upper_right>
        <Lower_right>X = 74E, Y = 19N</Lower_right>
        <Lower_left>X = 73E, Y = 19N</Lower_left>
    </Coverage>
    <Citation><Lineage><Tile_Name>{tileno}</Tile_Name><Resolution>1 arc sec</Resolution><File_Format>Geotiff</File_Format></Lineage></Citation>
    <Dataset_Topic_Category><Data_Identification_topic_category>Digital Elevation Model</Data_Identification_topic_category></Dataset_Topic_Category>
    <For_Image_Data>
        <Name_of_the_Satellite>Cartosat-1</Name_of_the_Satellite>
        <Sensor>PAN(2.5m) Stereo Data</Sensor>
        <File_Format>geotiff</File_Format>
        <Bits_per_Pixel>16bit</Bits_per_Pixel>
        <Spatial_Resolution>1arc sec</Spatial_Resolution>
    </For_Image_Data>
</metadata>
""")
        data = np.ones((10, 10), dtype=np.float32)
        transform = from_bounds(73.0, 19.0, 74.0, 20.0, 10, 10)
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


class TestSpatialDiscovery:
    def test_area_search_full_coverage(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace, "full.zip")
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/datasets/search/area", json={
                "bounds": {"west": 73.0, "south": 19.0, "east": 74.0, "north": 20.0},
                "dataset_types": ["DEM"],
            })
            assert response.status_code == 200
            body = response.json()
            assert len(body["fully_covering"]) > 0
            assert body["fully_covering"][0]["dataset_id"] == dataset_id
            assert body["fully_covering"][0]["coverage_percentage"] >= 99.0
            assert body["fully_covering"][0]["spatial_relation"] == "full_coverage"
        finally:
            datasets_module.BASE_DIR = original_base

    def test_area_search_no_overlap(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace, "no_overlap.zip")
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/datasets/search/area", json={
                "bounds": {"west": 0.0, "south": 0.0, "east": 1.0, "north": 1.0},
                "dataset_types": ["DEM"],
            })
            assert response.status_code == 200
            body = response.json()
            assert len(body["fully_covering"]) == 0
            assert len(body["partially_overlapping"]) == 0
        finally:
            datasets_module.BASE_DIR = original_base

    def test_area_search_partial_overlap(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace, "partial.zip")
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/datasets/search/area", json={
                "bounds": {"west": 73.5, "south": 19.5, "east": 74.5, "north": 20.5},
                "dataset_types": ["DEM"],
                "include_partial_overlap": True,
            })
            assert response.status_code == 200
            body = response.json()
            assert len(body["partially_overlapping"]) > 0
            assert body["partially_overlapping"][0]["coverage_percentage"] < 100.0
        finally:
            datasets_module.BASE_DIR = original_base

    def test_readiness_terrain_analysis(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace, "terrain.zip")
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/datasets/readiness", json={
                "area": {"west": 73.0, "south": 19.0, "east": 74.0, "north": 20.0},
                "analysis": "terrain",
            })
            assert response.status_code == 200
            body = response.json()
            assert body["ready"] is True
            assert body["readiness_score"] > 0
            assert len(body["datasets"]) > 0
            assert body["missing_requirements"] == []
        finally:
            datasets_module.BASE_DIR = original_base

    def test_readiness_unknown_analysis(self, tmp_workspace):
        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/datasets/readiness", json={
                "area": {"west": 73.0, "south": 19.0, "east": 74.0, "north": 20.0},
                "analysis": "unknown_type",
            })
            assert response.status_code == 200
            body = response.json()
            assert body["ready"] is False
            assert "Unknown analysis type" in body["missing_requirements"][0]
        finally:
            datasets_module.BASE_DIR = original_base

    def test_recommendation_ranking(self, tmp_workspace):
        zip1 = _create_bhuvan_zip(tmp_workspace, "rec1.zip")
        zip2 = _create_bhuvan_zip(tmp_workspace, "rec2.zip")
        ingest_dataset(str(zip1), str(tmp_workspace))
        ingest_dataset(str(zip2), str(tmp_workspace))

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/datasets/recommend", json={
                "area": {"west": 73.0, "south": 19.0, "east": 74.0, "north": 20.0},
                "analysis": "terrain",
                "top_n": 2,
            })
            assert response.status_code == 200
            body = response.json()
            assert len(body["recommended"]) <= 2
            if body["recommended"]:
                assert "score" in body["recommended"][0]
                assert "reasons" in body["recommended"][0]
        finally:
            datasets_module.BASE_DIR = original_base

    def test_compatibility_check(self, tmp_workspace):
        zip1 = _create_bhuvan_zip(tmp_workspace, "compat1.zip")
        zip2 = _create_bhuvan_zip(tmp_workspace, "compat2.zip")
        r1 = ingest_dataset(str(zip1), str(tmp_workspace))
        r2 = ingest_dataset(str(zip2), str(tmp_workspace))
        assert r1["status"] == "success"
        assert r2["status"] == "success"

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/datasets/compatibility", json={
                "dataset_ids": [r1["dataset_id"], r2["dataset_id"]],
            })
            assert response.status_code == 200
            body = response.json()
            assert "compatible" in body
            assert "issues" in body
            assert "warnings" in body
            assert "recommendations" in body
        finally:
            datasets_module.BASE_DIR = original_base

    def test_capabilities_api(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace, "caps.zip")
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/datasets/capabilities", json={
                "area": {"west": 73.0, "south": 19.0, "east": 74.0, "north": 20.0},
            })
            assert response.status_code == 200
            body = response.json()
            assert "capabilities" in body
            analyses = [c["analysis"] for c in body["capabilities"]]
            assert "terrain" in analyses
            assert "slope" in analyses
            assert "landuse" in analyses
        finally:
            datasets_module.BASE_DIR = original_base

    def test_prepare_analysis_ready(self, tmp_workspace):
        zip_path = _create_bhuvan_zip(tmp_workspace, "prepare.zip")
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/datasets/prepare-analysis", json={
                "area": {"west": 73.0, "south": 19.0, "east": 74.0, "north": 20.0},
                "analysis": "terrain",
            })
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "ready"
            assert body["analysis"] == "terrain"
            assert len(body["datasets"]) > 0
        finally:
            datasets_module.BASE_DIR = original_base

    def test_prepare_analysis_not_ready(self, tmp_workspace):
        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/datasets/prepare-analysis", json={
                "area": {"west": 0.0, "south": 0.0, "east": 1.0, "north": 1.0},
                "analysis": "terrain",
            })
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "not_ready"
        finally:
            datasets_module.BASE_DIR = original_base

    def test_temporal_pairs(self, tmp_workspace):
        zip1 = _create_bhuvan_zip(tmp_workspace, "temporal1.zip")
        zip2 = _create_bhuvan_zip(tmp_workspace, "temporal2.zip")
        r1 = ingest_dataset(str(zip1), str(tmp_workspace))
        r2 = ingest_dataset(str(zip2), str(tmp_workspace))
        assert r1["status"] == "success"
        assert r2["status"] == "success"

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/datasets/temporal-pairs", json={
                "area": {"west": 73.0, "south": 19.0, "east": 74.0, "north": 20.0},
                "dataset_type": "DEM",
                "min_temporal_difference_days": 0,
            })
            assert response.status_code == 200
            body = response.json()
            assert "pairs" in body
        finally:
            datasets_module.BASE_DIR = original_base

    def test_change_detection_readiness(self, tmp_workspace):
        zip1 = _create_bhuvan_zip(tmp_workspace, "change1.zip")
        zip2 = _create_bhuvan_zip(tmp_workspace, "change2.zip")
        r1 = ingest_dataset(str(zip1), str(tmp_workspace))
        r2 = ingest_dataset(str(zip2), str(tmp_workspace))
        assert r1["status"] == "success"
        assert r2["status"] == "success"

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/datasets/readiness", json={
                "area": {"west": 73.0, "south": 19.0, "east": 74.0, "north": 20.0},
                "analysis": "change_detection",
            })
            assert response.status_code == 200
            body = response.json()
            assert "analysis" in body
            assert "ready" in body
        finally:
            datasets_module.BASE_DIR = original_base


class TestAnalysisIntegration:
    @pytest.fixture
    def tmp_workspace(self, tmp_path):
        base = tmp_path / "workspace"
        base.mkdir()
        (base / "data" / "incoming").mkdir(parents=True)
        (base / "data" / "processing").mkdir(parents=True)
        (base / "data" / "catalog").mkdir(parents=True)
        (base / "data" / "raw").mkdir(parents=True)
        return base

    def test_analysis_dataset_returns_existing_files(self, tmp_workspace):
        from backend.app.integration.analysis_data_provider import get_analysis_dataset

        zip_path = _create_bhuvan_zip(tmp_workspace, "analysis_ok.zip")
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]

        analysis_ds = get_analysis_dataset(str(tmp_workspace), dataset_id)
        assert analysis_ds["dataset_id"] == dataset_id
        assert analysis_ds["ready_for_analysis"] is True
        assert analysis_ds["directory_exists"] is True
        assert len(analysis_ds["files"]) > 0
        for f in analysis_ds["files"]:
            assert f["exists"] is True
            assert f["full_path"] is not None
            assert f["name"] is not None

    def test_analysis_dataset_missing_directory(self, tmp_workspace):
        from backend.app.integration.analysis_data_provider import get_analysis_dataset

        zip_path = _create_bhuvan_zip(tmp_workspace, "analysis_missing_dir.zip")
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]

        import shutil
        dataset_dir = Path(tmp_workspace) / result["location"]
        shutil.rmtree(dataset_dir)

        analysis_ds = get_analysis_dataset(str(tmp_workspace), dataset_id)
        assert analysis_ds["ready_for_analysis"] is False
        assert analysis_ds["directory_exists"] is False
        assert any(e["code"] == DATASET_DIRECTORY_MISSING for e in analysis_ds["errors"])

    def test_analysis_dataset_deleted(self, tmp_workspace):
        from backend.app.integration.analysis_data_provider import get_analysis_dataset

        zip_path = _create_bhuvan_zip(tmp_workspace, "analysis_deleted.zip")
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]

        soft_delete_dataset(str(tmp_workspace), dataset_id)

        analysis_ds = get_analysis_dataset(str(tmp_workspace), dataset_id)
        assert analysis_ds["ready_for_analysis"] is False
        assert any(e["code"] == DATASET_DELETED for e in analysis_ds["errors"])

    def test_analysis_dataset_quarantined(self, tmp_workspace):
        from backend.app.integration.analysis_data_provider import get_analysis_dataset
        from backend.app.ingestion.catalog import update_dataset

        zip_path = _create_bhuvan_zip(tmp_workspace, "analysis_quarantined.zip")
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]

        update_dataset(str(tmp_workspace), dataset_id, {"status": "QUARANTINED"})

        analysis_ds = get_analysis_dataset(str(tmp_workspace), dataset_id)
        assert analysis_ds["ready_for_analysis"] is False
        assert any(e["code"] == DATASET_QUARANTINED for e in analysis_ds["errors"])

    def test_prepare_analysis_returns_stable_contract(self, tmp_workspace):
        from fastapi.testclient import TestClient
        from backend.app.main import app

        zip_path = _create_bhuvan_zip(tmp_workspace, "contract.zip")
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post("/api/datasets/prepare-analysis", json={
                "area": {"west": 72.0, "south": 18.0, "east": 73.0, "north": 19.0},
                "analysis": "terrain",
            })
        finally:
            datasets_module.BASE_DIR = original_base

        assert response.status_code == 200
        body = response.json()
        assert "status" in body
        assert "analysis" in body
        assert "datasets" in body
        if body["status"] == "ready":
            ds = body["datasets"][0]
            assert "dataset_id" in ds
            assert "dataset_name" in ds
            assert "file_path" in ds
            assert "directory_exists" in ds
            assert "manifest_exists" in ds
            assert "manifest_valid" in ds
            assert "files" in ds
            assert "manifest" in ds
            assert "bounds" in ds
            assert "ready_for_analysis" in ds
            assert "errors" in ds
            assert "warnings" in ds
