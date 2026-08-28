import zipfile
from pathlib import Path
from typing import Dict, Any
import json
import shutil

import pytest
import numpy as np

import rasterio
from rasterio.transform import from_bounds

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.ingestion.metadata.xml_parser import parse_xml, parse_bhuvan_xml
from app.ingestion.metadata.geotiff_reader import read_geotiff_metadata
from app.ingestion.inspector import inspect_dataset
from app.ingestion.classifier import classify_dataset
from app.ingestion.validator import validate_upload, validate_dataset
from app.ingestion.duplicates import is_exact_duplicate
from app.ingestion.organizer import build_destination, organize_files, generate_manifest, write_manifest
from app.ingestion.catalog import init_db, insert_dataset, update_status, get_dataset, list_datasets, query_one
from app.ingestion.pipeline import ingest_dataset
from app.ingestion.name_parser import parse_dataset_name


@pytest.fixture
def tmp_workspace(tmp_path):
    incoming = tmp_path / "data" / "incoming"
    processing = tmp_path / "data" / "processing"
    raw = tmp_path / "data" / "raw"
    quarantine = tmp_path / "data" / "quarantine"
    catalog = tmp_path / "data" / "catalog"
    for d in [incoming, processing, raw, quarantine, catalog]:
        d.mkdir(parents=True, exist_ok=True)
    return tmp_path


class TestXmlParser:
    def test_parse_bhuvan_xml(self, tmp_path):
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <Metadata>
            <Name_of_the_Dataset>OCM2 NDVI</Name_of_the_Dataset>
            <Keywords>DEM, terrain, elevation</Keywords>
            <Coverage>
                <Upper_left>X = 66 E, Y = 40 N</Upper_left>
                <Upper_right>X = 70 E, Y = 40 N</Upper_right>
                <Lower_right>X = 70 E, Y = 36 N</Lower_right>
                <Lower_left>X = 66 E, Y = 36 N</Lower_left>
            </Coverage>
            <Resolution>0.01017 Deg</Resolution>
            <File_Format>Geotiff</File_Format>
            <Original_Source>Bhuvan</Original_Source>
            <For_Image_Data>
                <Name_of_the_Satellite>OCM2</Name_of_the_Satellite>
                <Sensor>OCM</Sensor>
                <Spatial_Resolution>0.01017 Deg</Spatial_Resolution>
                <Number_of_Bands>1</Number_of_Bands>
            </For_Image_Data>
        </Metadata>
        """
        xml_file = tmp_path / "metadata.xml"
        xml_file.write_text(xml_content)
        meta = parse_xml(xml_file)
        assert meta["dataset_name"] == "OCM2 NDVI"
        assert meta["dataset_type"] == "DEM"
        assert meta["min_lon"] == 66.0
        assert meta["max_lon"] == 70.0
        assert meta["min_lat"] == 36.0
        assert meta["max_lat"] == 40.0
        assert meta["resolution"] == "0.01017 Deg"
        assert meta["format"] == "Geotiff"
        assert meta["source"] == "Bhuvan"
        assert meta["satellite"] == "OCM2"
        assert meta["sensor"] == "OCM"
        assert meta["number_of_bands"] == 1

    def test_parse_bounds_not_exposed_from_coverage(self, tmp_path):
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <metadata filename="ocm2_ndvi_jan01to152021_v02_01">
            <Data_Identification_Information>
                <Name_of_the_Dataset>ocm2_ndvi_jan01to152021_v02_01</Name_of_the_Dataset>
                <Keywords>OCM2,VF,NDVI,1080m,India,ISRO,NRSC,Precision</Keywords>
            </Data_Identification_Information>
            <Coverage>
                <Upper_left>X = 66 E, Y = 40 N</Upper_left>
                <Upper_right>X = 102 E, Y = 40 N</Upper_right>
                <Lower_right>X = 102 E, Y = 4 N</Lower_right>
                <Lower_left>X = 66 E, Y = 4 N</Lower_left>
            </Coverage>
        </metadata>
        """
        xml_file = tmp_path / "metadata.xml"
        xml_file.write_text(xml_content)
        meta = parse_xml(xml_file)
        assert meta.get("min_lon") == 66.0
        assert meta.get("max_lon") == 102.0
        assert meta.get("min_lat") == 4.0
        assert meta.get("max_lat") == 40.0

    def test_parse_missing_file(self, tmp_path):
        assert parse_xml(tmp_path / "missing.xml") == {}

    def test_parse_invalid_xml(self, tmp_path):
        xml_file = tmp_path / "bad.xml"
        xml_file.write_text("not xml")
        assert parse_xml(xml_file) == {}


class TestGeotiffReader:
    def test_read_geotiff_metadata(self, tmp_path):
        tif_path = tmp_path / "test.tif"
        data = np.ones((10, 10), dtype=np.float32) * 100.0
        transform = from_bounds(66.0, 36.0, 70.0, 40.0, 10, 10)
        with rasterio.open(
            tif_path,
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

        meta = read_geotiff_metadata(tif_path)
        assert meta["crs"] == "EPSG:4326"
        assert meta["width"] == 10
        assert meta["height"] == 10
        assert meta["count"] == 1
        assert meta["driver"] == "GTiff"
        assert meta["bounds"] == pytest.approx((66.0, 36.0, 70.0, 40.0))

    def test_missing_file(self, tmp_path):
        assert read_geotiff_metadata(tmp_path / "missing.tif") == {"_error": "file_not_found"}


class TestInspector:
    def test_inspect_with_xml_and_tif(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "meta.xml").write_text("<xml/>")
        (pkg / "data.tif").write_bytes(b"fake tif")
        (pkg / "readme.txt").write_text("hello")
        manifest = inspect_dataset(str(pkg))
        assert manifest["supported_files"] == 3
        assert len(manifest["xml_files"]) == 1
        assert len(manifest["primary_files"]) == 1

    def test_inspect_shapefile_group(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "roads.shp").write_bytes(b"shp")
        (pkg / "roads.shx").write_bytes(b"shx")
        (pkg / "roads.dbf").write_bytes(b"dbf")
        (pkg / "roads.prj").write_bytes(b"prj")
        manifest = inspect_dataset(str(pkg))
        assert manifest["supported_files"] == 4
        assert len(manifest["shapefile_groups"]) == 1


class TestClassifier:
    def test_xml_priority(self):
        xml = {"dataset_type": "DSM"}
        gtiff = {}
        result = classify_dataset(xml, gtiff, "random.tif")
        assert result["dataset_type"] == "DSM"
        assert result["confidence"] == "high"

    def test_filename_keyword(self):
        xml = {}
        gtiff = {}
        result = classify_dataset(xml, gtiff, "dem_data.tif")
        assert result["dataset_type"] == "DEM"
        assert result["confidence"] == "medium"

    def test_unknown(self):
        xml = {}
        gtiff = {}
        result = classify_dataset(xml, gtiff, "random.bin")
        assert result["dataset_type"] == "UNKNOWN"
        assert result["confidence"] == "low"


class TestValidator:
    def test_invalid_zip(self, tmp_path):
        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_bytes(b"not a zip")
        res = validate_upload(str(bad_zip))
        assert res["valid"] is False
        assert res["error_reason"] == "CORRUPTED_ARCHIVE"

    def test_valid_zip(self, tmp_path):
        good_zip = tmp_path / "good.zip"
        with zipfile.ZipFile(good_zip, "w") as zf:
            zf.writestr("hello.txt", "hello")
        res = validate_upload(str(good_zip))
        assert res["valid"] is True

    def test_validate_dataset_no_files(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        manifest = inspect_dataset(str(empty))
        res = validate_dataset(empty, manifest)
        assert res["valid"] is False
        assert res["error_reason"] == "NO_SUPPORTED_DATA_FILE"


class TestDuplicates:
    def test_exact_duplicate_by_hash(self, tmp_workspace):
        init_db(str(tmp_workspace))
        insert_dataset(str(tmp_workspace), {
            "dataset_name": "DSM1",
            "dataset_type": "DSM",
            "tile": "F43U",
            "version": "V1",
            "status": "READY",
            "file_path": "data/raw/terrain/DSM/F43U/V1",
            "file_hash": "abc123",
        })
        assert is_exact_duplicate(str(tmp_workspace), "dsm1.zip", "abc123") is True
        assert is_exact_duplicate(str(tmp_workspace), "dsm1_copy.zip", "abc123") is True
        assert is_exact_duplicate(str(tmp_workspace), "dsm1.zip", "different-hash") is False


class TestNameParser:
    def test_f43u_dem_v1(self):
        result = parse_dataset_name("F43U_DEM_V1")
        assert result["tile"] == "F43U"
        assert result["dataset_type"] == "DEM"
        assert result["version"] == "V1"
        assert result["confidence"] == "medium"

    def test_complex_name(self):
        result = parse_dataset_name("C1_DEM_16b_2006-2008_V1_74E20N_F43U")
        assert result["tile"] == "F43U"
        assert result["dataset_type"] == "DEM"
        assert result["version"] == "V1"
        assert result["confidence"] == "medium"

    def test_no_match(self):
        result = parse_dataset_name("random_data_file")
        assert result["tile"] is None
        assert result["dataset_type"] is None
        assert result["version"] is None
        assert result["confidence"] == "low"


class TestOrganizer:
    def test_build_destination(self, tmp_workspace):
        meta = {"theme": "terrain", "dataset_type": "DEM", "tile": "F43U", "version": "V1"}
        dest = build_destination(meta, str(tmp_workspace))
        expected = tmp_workspace / "data" / "raw" / "terrain" / "DEM" / "F43U" / "V1"
        assert dest == expected

    def test_no_overwrite(self, tmp_workspace):
        meta = {"theme": "terrain", "dataset_type": "DEM", "tile": "F43U", "version": "V1"}
        dest = build_destination(meta, str(tmp_workspace))
        dest.mkdir(parents=True)
        (dest / "exists.txt").write_text("x")
        dest2 = build_destination(meta, str(tmp_workspace))
        assert str(dest2) != str(dest)
        assert "_2" in str(dest2)


class TestCatalog:
    def test_insert_and_retrieve(self, tmp_workspace):
        init_db(str(tmp_workspace))
        record = {
            "dataset_name": "TestDS",
            "dataset_type": "DEM",
            "tile": "F43U",
            "version": "V1",
            "status": "READY",
            "file_path": "data/raw/terrain/DEM/F43U/V1",
        }
        ds_id = insert_dataset(str(tmp_workspace), record)
        ds = get_dataset(str(tmp_workspace), ds_id)
        assert ds["dataset_name"] == "TestDS"
        assert ds["dataset_type"] == "DEM"

    def test_list_datasets(self, tmp_workspace):
        init_db(str(tmp_workspace))
        insert_dataset(str(tmp_workspace), {"dataset_name": "A", "dataset_type": "DEM", "tile": "T1", "version": "V1", "status": "READY"})
        insert_dataset(str(tmp_workspace), {"dataset_name": "B", "dataset_type": "DSM", "tile": "T2", "version": "V1", "status": "READY"})
        items = list_datasets(str(tmp_workspace))
        assert len(items) == 2

    def test_update_status(self, tmp_workspace):
        init_db(str(tmp_workspace))
        ds_id = insert_dataset(str(tmp_workspace), {"dataset_name": "X", "dataset_type": "DEM", "tile": "T", "version": "V", "status": "PROCESSING"})
        update_status(str(tmp_workspace), ds_id, "FAILED", error_reason="INVALID_XML")
        ds = get_dataset(str(tmp_workspace), ds_id)
        assert ds["status"] == "FAILED"
        assert ds["error_reason"] == "INVALID_XML"


class TestPipeline:
    def test_end_to_end_zip(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "dem_test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            xml = """<?xml version="1.0"?>
            <Metadata>
                <Name_of_the_Dataset>Test DEM</Name_of_the_Dataset>
                <Keywords>DEM</Keywords>
                <Resolution>30m</Resolution>
                <File_Format>Geotiff</File_Format>
                <Original_Source>Test</Original_Source>
            </Metadata>
            """
            zf.writestr("metadata.xml", xml)
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(66.0, 36.0, 70.0, 40.0, 10, 10)
            with rasterio.open(
                "/tmp/test_raster.tif",
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
            with open("/tmp/test_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "needs_review"
        assert result["dataset_type"] == "DEM"
        assert result["tile"] == "UNKNOWN"
        assert result["version"] == "UNKNOWN"
        assert result["dataset_id"] is not None

    def test_bounds_from_geotiff_not_xml_coverage(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "bounds_test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            xml = """<?xml version="1.0"?>
            <metadata filename="test">
                <Data_Identification_Information>
                    <Name_of_the_Dataset>Test Dataset</Name_of_the_Dataset>
                    <Keywords>DEM</Keywords>
                </Data_Identification_Information>
                <Coverage>
                    <Upper_left>X = 66 E, Y = 40 N</Upper_left>
                    <Upper_right>X = 102 E, Y = 40 N</Upper_right>
                    <Lower_right>X = 102 E, Y = 4 N</Lower_right>
                    <Lower_left>X = 66 E, Y = 4 N</Lower_left>
                </Coverage>
            </metadata>
            """
            zf.writestr("metadata.xml", xml)
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(73.0, 20.0, 74.0, 21.0, 10, 10)
            with rasterio.open(
                "/tmp/test_bounds_raster.tif",
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
            with open("/tmp/test_bounds_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "needs_review"
        assert result["bounds"]["west"] == pytest.approx(73.0)
        assert result["bounds"]["south"] == pytest.approx(20.0)
        assert result["bounds"]["east"] == pytest.approx(74.0)
        assert result["bounds"]["north"] == pytest.approx(21.0)

    def test_provenance_xml_high_confidence(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "prov_xml.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            xml = """<?xml version="1.0"?>
            <Metadata>
                <Name_of_the_Dataset>F43U_DEM_V1</Name_of_the_Dataset>
                <Keywords>DEM</Keywords>
                <Tile>F43U</Tile>
                <Version>V1</Version>
                <Resolution>30m</Resolution>
                <File_Format>Geotiff</File_Format>
                <Original_Source>Bhuvan</Original_Source>
            </Metadata>
            """
            zf.writestr("metadata.xml", xml)
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(73.0, 20.0, 74.0, 21.0, 10, 10)
            with rasterio.open(
                "/tmp/test_prov_raster.tif",
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
            with open("/tmp/test_prov_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        prov = result["metadata_provenance"]
        assert prov["tile"]["value"] == "F43U"
        assert prov["tile"]["source"] == "xml"
        assert prov["tile"]["confidence"] == "high"
        assert prov["version"]["value"] == "V1"
        assert prov["version"]["source"] == "xml"
        assert prov["version"]["confidence"] == "high"
        assert prov["dataset_type"]["value"] == "DEM"
        assert prov["dataset_type"]["source"] == "xml"
        assert prov["dataset_type"]["confidence"] == "high"

    def test_provenance_filename_medium_confidence(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "F43U_DEM_V1.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            xml = """<?xml version="1.0"?>
            <Metadata>
                <Name_of_the_Dataset>Some Dataset</Name_of_the_Dataset>
                <Keywords>unknown</Keywords>
            </Metadata>
            """
            zf.writestr("metadata.xml", xml)
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(73.0, 20.0, 74.0, 21.0, 10, 10)
            with rasterio.open(
                "/tmp/test_prov_file_raster.tif",
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
            with open("/tmp/test_prov_file_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        prov = result["metadata_provenance"]
        assert prov["tile"]["value"] == "F43U"
        assert prov["tile"]["source"] == "filename"
        assert prov["tile"]["confidence"] == "medium"
        assert prov["version"]["value"] == "V1"
        assert prov["version"]["source"] == "filename"
        assert prov["version"]["confidence"] == "medium"
        assert prov["dataset_type"]["value"] == "DEM"
        assert prov["dataset_type"]["source"] == "filename"
        assert prov["dataset_type"]["confidence"] == "medium"

    def test_provenance_unknown_never_high(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "random_data_file.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            xml = """<?xml version="1.0"?>
            <Metadata>
                <Name_of_the_Dataset>random_data_file</Name_of_the_Dataset>
            </Metadata>
            """
            zf.writestr("metadata.xml", xml)
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(73.0, 20.0, 74.0, 21.0, 10, 10)
            with rasterio.open(
                "/tmp/test_prov_unk_raster.tif",
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
            with open("/tmp/test_prov_unk_raster.tif", "rb") as f:
                zf.writestr("random.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "needs_review"
        prov = result["metadata_provenance"]
        assert prov["tile"]["value"] == "UNKNOWN"
        assert prov["tile"]["source"] == "unknown"
        assert prov["tile"]["confidence"] == "unknown"
        assert prov["version"]["value"] == "UNKNOWN"
        assert prov["version"]["source"] == "unknown"
        assert prov["version"]["confidence"] == "unknown"


class TestManifest:
    def test_manifest_generated(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "manifest_test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            xml = """<?xml version="1.0"?>
            <Metadata>
                <Name_of_the_Dataset>F43U_DEM_V1</Name_of_the_Dataset>
                <Keywords>DEM</Keywords>
                <Tile>F43U</Tile>
                <Version>V1</Version>
                <Resolution>30m</Resolution>
                <File_Format>Geotiff</File_Format>
                <Original_Source>Bhuvan</Original_Source>
            </Metadata>
            """
            zf.writestr("metadata.xml", xml)
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(73.0, 20.0, 74.0, 21.0, 10, 10)
            with rasterio.open(
                "/tmp/test_manifest_raster.tif",
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
            with open("/tmp/test_manifest_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        assert result["dataset_type"] == "DEM"
        assert result["tile"] == "F43U"
        assert result["version"] == "V1"
        assert result["dataset_id"] is not None
        dest = Path(result["location"])
        assert dest.exists()
        manifest_path = dest / "manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["dataset_id"] == result["dataset_id"]
        assert manifest["dataset_type"] == "DEM"
        assert manifest["tile"] == "F43U"
        assert manifest["version"] == "V1"
        assert len(manifest["files"]) == 2
        assert manifest["status"] == "READY"

    def test_unknown_dataset_gets_id_folder(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "unknown_test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            xml = """<?xml version="1.0"?>
            <Metadata>
                <Name_of_the_Dataset>random_data_file</Name_of_the_Dataset>
            </Metadata>
            """
            zf.writestr("metadata.xml", xml)
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(73.0, 20.0, 74.0, 21.0, 10, 10)
            with rasterio.open(
                "/tmp/test_unknown_raster.tif",
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
            with open("/tmp/test_unknown_raster.tif", "rb") as f:
                zf.writestr("random.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "needs_review"
        assert result["tile"] == "UNKNOWN"
        assert result["version"] == "UNKNOWN"
        dest = Path(result["location"])
        assert dest.exists()
        assert str(dest).startswith(str(tmp_workspace / "data" / "raw" / "unknown"))
        manifest_path = dest / "manifest.json"
        assert manifest_path.exists()

    def test_manual_classification_moves_dataset(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "reclassify_test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            xml = """<?xml version="1.0"?>
            <Metadata>
                <Name_of_the_Dataset>random_data_file</Name_of_the_Dataset>
            </Metadata>
            """
            zf.writestr("metadata.xml", xml)
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(73.0, 20.0, 74.0, 21.0, 10, 10)
            with rasterio.open(
                "/tmp/test_reclassify_raster.tif",
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
            with open("/tmp/test_reclassify_raster.tif", "rb") as f:
                zf.writestr("random.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "needs_review"
        dataset_id = result["dataset_id"]

        from fastapi.testclient import TestClient
        from backend.app.main import app
        from backend.app.api import datasets as datasets_module

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            classify_response = client.put(
                f"/api/datasets/{dataset_id}/classify",
                json={"theme": "terrain", "dataset_type": "DEM", "tile": "F43U", "version": "V1"}
            )
        finally:
            datasets_module.BASE_DIR = original_base
        assert classify_response.status_code == 200
        classify_result = classify_response.json()
        assert classify_result["status"] == "success"
        assert "terrain/DEM/F43U/V1" in classify_result["dataset"]["location"]

    def test_storage_integrity_check(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "integrity_test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            xml = """<?xml version="1.0"?>
            <Metadata>
                <Name_of_the_Dataset>F43U_DEM_V1</Name_of_the_Dataset>
                <Keywords>DEM</Keywords>
                <Tile>F43U</Tile>
                <Version>V1</Version>
                <Resolution>30m</Resolution>
                <File_Format>Geotiff</File_Format>
                <Original_Source>Bhuvan</Original_Source>
            </Metadata>
            """
            zf.writestr("metadata.xml", xml)
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(73.0, 20.0, 74.0, 21.0, 10, 10)
            with rasterio.open(
                "/tmp/test_integrity_raster.tif",
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
            with open("/tmp/test_integrity_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        assert result["dataset_id"] is not None

        from fastapi.testclient import TestClient
        from backend.app.main import app
        from backend.app.api import datasets as datasets_module

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            integrity_response = client.get(f"/api/datasets/integrity/check/{result['dataset_id']}")
        finally:
            datasets_module.BASE_DIR = original_base
        assert integrity_response.status_code == 200
        integrity = integrity_response.json()
        assert integrity["status"] == "healthy"


class TestSorting:
    def test_complete_metadata_organizes_to_typed_path(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "F43U_DEM_V1.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<Metadata>
    <Name_of_the_Dataset>F43U_DEM_V1</Name_of_the_Dataset>
    <Keywords>DEM</Keywords>
    <Tile>F43U</Tile>
    <Version>V1</Version>
    <Resolution>30m</Resolution>
    <File_Format>Geotiff</File_Format>
    <Original_Source>Bhuvan</Original_Source>
</Metadata>""")
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(73.0, 20.0, 74.0, 21.0, 10, 10)
            with rasterio.open(
                "/tmp/test_sort_raster.tif",
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
            with open("/tmp/test_sort_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        assert result["dataset_type"] == "DEM"
        assert result["tile"] == "F43U"
        assert result["version"] == "V1"
        dest = Path(result["location"])
        assert dest.exists()
        assert str(dest).endswith(str(Path("data") / "raw" / "terrain" / "DEM" / "F43U" / "V1"))
        assert (dest / "manifest.json").exists()
        assert (dest / "metadata.xml").exists()
        assert (dest / "dem.tif").exists()

    def test_insufficient_metadata_goes_to_unknown_id_folder(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "random_dataset.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<Metadata>
    <Name_of_the_Dataset>random_data_file</Name_of_the_Dataset>
</Metadata>""")
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(73.0, 20.0, 74.0, 21.0, 10, 10)
            with rasterio.open(
                "/tmp/test_unknown_sort_raster.tif",
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
            with open("/tmp/test_unknown_sort_raster.tif", "rb") as f:
                zf.writestr("random.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "needs_review"
        assert result["dataset_type"] == "UNKNOWN"
        assert result["tile"] == "UNKNOWN"
        assert result["version"] == "UNKNOWN"
        dest = Path(result["location"])
        assert dest.exists()
        assert str(dest).startswith(str(tmp_workspace / "data" / "raw" / "unknown"))
        assert (dest / "manifest.json").exists()
        manifest = json.loads((dest / "manifest.json").read_text())
        assert manifest["status"] == "NEEDS_REVIEW"


class TestBhuvanRealXml:
    def test_full_bhuvan_dem_parsing_and_organization(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "random_bhuvan_download.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0" encoding="UTF-8"?>
<metadata tileno="e43g">

    <Data_Identification_Information>

        <Name_of_the_Dataset>
        C1_DEM_16b_2006-2008_v1_72E18N_e43g
        </Name_of_the_Dataset>

        <Theme>Terrain</Theme>

        <Keywords>
        Cartosat-1,DEM,Stereodata,India,ISRO,NRSC
        </Keywords>

        <Data_Type>Elevation</Data_Type>

    </Data_Identification_Information>

    <Coverage>

        <Upper_left>X = 72E, Y = 19N</Upper_left>
        <Upper_right>X = 73E, Y = 19N</Upper_right>
        <Lower_right>X = 73E, Y = 18N</Lower_right>
        <Lower_left>X = 72E, Y = 18N</Lower_left>

    </Coverage>

    <Citation>

        <Lineage>

            <Tile_Name>e43g</Tile_Name>

            <Resolution>1 arc sec</Resolution>

            <File_Format>Geotiff</File_Format>

        </Lineage>

    </Citation>

    <Dataset_Topic_Category>

        <Data_Identification_topic_category>
        Digital Elevation Model
        </Data_Identification_topic_category>

    </Dataset_Topic_Category>

    <For_Image_Data>

        <Name_of_the_Satellite>
        Cartosat-1
        </Name_of_the_Satellite>

        <Sensor>
        PAN(2.5m) Stereo Data
        </Sensor>

        <File_Format>Geotiff</File_Format>

        <Bits_per_Pixel>16bit</Bits_per_Pixel>

        <Spatial_Resolution>
        1arc sec
        </Spatial_Resolution>

    </For_Image_Data>

</metadata>
""")
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
            with rasterio.open(
                "/tmp/test_bhuvan_raster.tif",
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
            with open("/tmp/test_bhuvan_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        assert result["dataset_type"] == "DEM"
        assert result["tile"] == "E43G"
        assert result["version"] == "V1"
        assert result["theme"] == "terrain"
        assert result["resolution"] == "1arc sec"
        assert result["format"] == "Geotiff"
        assert result["source"] == "Bhuvan / NRSC / ISRO"
        assert result["platform"] == "Cartosat-1"
        assert result["sensor"] == "PAN(2.5m) Stereo Data"
        assert result["bits_per_pixel"] == "16bit"

        dest = Path(result["location"])
        assert dest.exists()
        assert str(dest).endswith(str(Path("data") / "raw" / "terrain" / "DEM" / "E43G" / "V1"))
        assert (dest / "manifest.json").exists()
        assert (dest / "metadata.xml").exists()
        assert (dest / "dem.tif").exists()

        manifest = json.loads((dest / "manifest.json").read_text())
        assert manifest["dataset_type"] == "DEM"
        assert manifest["tile"] == "E43G"
        assert manifest["version"] == "V1"
        assert manifest["theme"] == "terrain"
        assert manifest["status"] == "READY"
        assert manifest["source"] == "Bhuvan / NRSC / ISRO"

        prov = result["metadata_provenance"]
        assert prov["tile"]["value"] == "E43G"
        assert prov["tile"]["source"] == "xml"
        assert prov["tile"]["confidence"] == "high"
        assert prov["version"]["value"] == "V1"
        assert prov["version"]["source"] == "xml"
        assert prov["version"]["confidence"] == "high"
        assert prov["dataset_type"]["value"] == "DEM"
        assert prov["dataset_type"]["source"] == "xml"
        assert prov["dataset_type"]["confidence"] == "high"

        assert result["bounds"]["west"] == pytest.approx(72.0)
        assert result["bounds"]["south"] == pytest.approx(18.0)
        assert result["bounds"]["east"] == pytest.approx(73.0)
        assert result["bounds"]["north"] == pytest.approx(19.0)


class TestLifecycle:
    def test_delete_dataset_removes_files_and_catalog(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "delete_me.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="e43g">
    <Data_Identification_Information>
        <Name_of_the_Dataset>C1_DEM_16b_2006-2008_v1_72E18N_e43g</Name_of_the_Dataset>
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
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
            with rasterio.open(
                "/tmp/test_delete_raster.tif",
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
            with open("/tmp/test_delete_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]
        dest = Path(result["location"])
        assert dest.exists()

        from backend.app.ingestion.catalog import delete_dataset, get_dataset
        delete_result = delete_dataset(str(tmp_workspace), dataset_id, permanent=True)
        assert delete_result["deleted"] is True
        assert not dest.exists()
        assert get_dataset(str(tmp_workspace), dataset_id) is None

    def test_reprocess_keeps_dataset_organized(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "review_me.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata>
    <Data_Identification_Information>
        <Name_of_the_Dataset>Some Random Dataset</Name_of_the_Dataset>
        <Theme>Terrain</Theme>
        <Keywords>DEM</Keywords>
        <Data_Type>Elevation</Data_Type>
    </Data_Identification_Information>
    <Coverage>
        <Upper_left>X = 66 E, Y = 40 N</Upper_left>
        <Upper_right>X = 70 E, Y = 40 N</Upper_right>
        <Lower_right>X = 70 E, Y = 36 N</Lower_right>
        <Lower_left>X = 66 E, Y = 36 N</Lower_left>
    </Coverage>
</metadata>
""")
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(66.0, 36.0, 70.0, 40.0, 10, 10)
            with rasterio.open(
                "/tmp/test_reprocess_raster.tif",
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
            with open("/tmp/test_reprocess_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "needs_review"
        dataset_id = result["dataset_id"]
        old_location = Path(result["location"])
        assert old_location.exists()
        assert str(old_location).startswith(str(tmp_workspace / "data" / "raw" / "unknown"))

        import zipfile as zf_mod
        temp_zip = tmp_workspace / "data" / "processing" / f"reprocess_{dataset_id}.zip"
        with zf_mod.ZipFile(temp_zip, "w", zf_mod.ZIP_DEFLATED) as zf:
            for f in old_location.iterdir():
                if f.is_file():
                    zf.write(f, f.name)

        shutil.rmtree(old_location)

        reprocess_result = ingest_dataset(str(temp_zip), str(tmp_workspace))
        assert reprocess_result["status"] == "needs_review"
        new_location = Path(reprocess_result["location"])
        assert new_location.exists()
        assert reprocess_result["dataset_type"] == "DEM"
        assert reprocess_result["tile"] == "UNKNOWN"
        assert reprocess_result["version"] == "UNKNOWN"

    def test_reclassify_dataset_moves_directory(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "reclassify_me.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="e43g">
    <Data_Identification_Information>
        <Name_of_the_Dataset>C1_DEM_16b_2006-2008_v1_72E18N_e43g</Name_of_the_Dataset>
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
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
            with rasterio.open(
                "/tmp/test_reclassify_raster.tif",
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
            with open("/tmp/test_reclassify_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]
        old_location = Path(result["location"])
        assert old_location.exists()
        assert str(old_location).endswith(str(Path("data") / "raw" / "terrain" / "DEM" / "E43G" / "V1"))

        from backend.app.ingestion.catalog import get_dataset, update_dataset
        from backend.app.ingestion.organizer import build_destination, organize_files, generate_manifest, write_manifest
        import shutil

        ds = get_dataset(str(tmp_workspace), dataset_id)
        metadata = {
            "theme": "terrain",
            "dataset_type": "LULC",
            "tile": "E43G",
            "version": "V2",
            "dataset_name": ds.get("dataset_name"),
            "resolution": ds.get("resolution"),
            "format": ds.get("format"),
            "source": ds.get("source"),
            "min_lon": ds.get("min_lon"),
            "max_lon": ds.get("max_lon"),
            "min_lat": ds.get("min_lat"),
            "max_lat": ds.get("max_lat"),
        }

        new_destination = build_destination(metadata, str(tmp_workspace), dataset_id=dataset_id)
        new_destination.mkdir(parents=True, exist_ok=True)
        for item in old_location.iterdir():
            target = new_destination / item.name
            if target.exists():
                base = target.stem
                suffix = target.suffix
                i = 2
                while target.exists():
                    target = new_destination / f"{base}_{i}{suffix}"
                    i += 1
            shutil.move(str(item), str(target))
        shutil.rmtree(old_location)

        rel_path = new_destination.relative_to(Path(tmp_workspace))
        update_dataset(str(tmp_workspace), dataset_id, {
            "theme": "terrain",
            "dataset_type": "LULC",
            "tile": "E43G",
            "version": "V2",
            "file_path": str(rel_path),
            "status": "READY",
        })

        manifest = generate_manifest(new_destination, metadata, dataset_id, ds.get("original_filename", ""), "READY")
        write_manifest(new_destination, manifest)

        ds_updated = get_dataset(str(tmp_workspace), dataset_id)
        assert ds_updated["dataset_type"] == "LULC"
        assert ds_updated["version"] == "V2"
        assert ds_updated["theme"] == "terrain"
        assert new_destination.exists()
        assert (new_destination / "manifest.json").exists()
        assert (new_destination / "dem.tif").exists()

    def test_rename_dataset_updates_manifest(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "rename_me.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="e43g">
    <Data_Identification_Information>
        <Name_of_the_Dataset>C1_DEM_16b_2006-2008_v1_72E18N_e43g</Name_of_the_Dataset>
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
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
            with rasterio.open(
                "/tmp/test_rename_raster.tif",
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
            with open("/tmp/test_rename_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]
        dest = Path(result["location"])

        from backend.app.ingestion.catalog import get_dataset, update_dataset
        from backend.app.ingestion.organizer import generate_manifest, write_manifest
        import json

        update_dataset(str(tmp_workspace), dataset_id, {"dataset_name": "Renamed Dataset"})
        manifest_path = dest / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            manifest["dataset_name"] = "Renamed Dataset"
            write_manifest(dest, manifest)

        ds = get_dataset(str(tmp_workspace), dataset_id)
        assert ds["dataset_name"] == "Renamed Dataset"
        manifest = json.loads((dest / "manifest.json").read_text())
        assert manifest["dataset_name"] == "Renamed Dataset"

    def test_file_management_delete_and_update_role(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "files.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="e43g">
    <Data_Identification_Information>
        <Name_of_the_Dataset>C1_DEM_16b_2006-2008_v1_72E18N_e43g</Name_of_the_Dataset>
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
            zf.writestr("readme.txt", "This is a test dataset.")
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
            with rasterio.open(
                "/tmp/test_files_raster.tif",
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
            with open("/tmp/test_files_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]
        dest = Path(result["location"])

        from backend.app.ingestion.catalog import get_dataset
        from backend.app.ingestion.organizer import write_manifest
        import json

        ds = get_dataset(str(tmp_workspace), dataset_id)
        readme_path = dest / "readme.txt"
        assert readme_path.exists()

        readme_path.unlink()
        manifest_path = dest / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            manifest["files"] = [f for f in manifest.get("files", []) if f.get("name") != "readme.txt"]
            write_manifest(dest, manifest)

        assert not readme_path.exists()
        assert (dest / "dem.tif").exists()
        assert (dest / "metadata.xml").exists()

        manifest = json.loads((dest / "manifest.json").read_text())
        file_names = [f["name"] for f in manifest.get("files", [])]
        assert "readme.txt" not in file_names

    def test_integrity_check_healthy_dataset(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "healthy.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="e43g">
    <Data_Identification_Information>
        <Name_of_the_Dataset>C1_DEM_16b_2006-2008_v1_72E18N_e43g</Name_of_the_Dataset>
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
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
            with rasterio.open(
                "/tmp/test_healthy_raster.tif",
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
            with open("/tmp/test_healthy_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]

        from backend.app.api.datasets import check_dataset_integrity
        from backend.app.api import datasets as datasets_module

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            integrity = check_dataset_integrity(dataset_id)
        finally:
            datasets_module.BASE_DIR = original_base
        assert integrity["status"] == "healthy"
        assert len(integrity["issues"]) == 0

    def test_ndvi_classification_from_xml(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "ndvi_test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata>
    <Data_Identification_Information>
        <Name_of_the_Dataset>OCM2_NDVI_2021_V1</Name_of_the_Dataset>
        <Theme>Landcover</Theme>
        <Keywords>OCM2,NDVI,1080m,India,ISRO,NRSC</Keywords>
        <Data_Type>NDVI</Data_Type>
    </Data_Identification_Information>
    <Coverage>
        <Upper_left>X = 66 E, Y = 40 N</Upper_left>
        <Upper_right>X = 102 E, Y = 40 N</Upper_right>
        <Lower_right>X = 102 E, Y = 4 N</Lower_right>
        <Lower_left>X = 66 E, Y = 4 N</Lower_left>
    </Coverage>
</metadata>
""")
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(66.0, 4.0, 102.0, 40.0, 10, 10)
            with rasterio.open(
                "/tmp/test_ndvi_raster.tif",
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
            with open("/tmp/test_ndvi_raster.tif", "rb") as f:
                zf.writestr("ndvi.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["dataset_type"] == "NDVI"
        assert result["confidence"] == "high"
        assert len(result["classification"]["evidence"]) > 0
        dest = Path(result["location"])
        assert dest.exists()
        assert str(dest).endswith(str(Path("data") / "raw" / "landcover" / "NDVI" / "UNKNOWN" / "V1"))

    def test_lulc_classification_from_xml(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "lulc_test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata>
    <Data_Identification_Information>
        <Name_of_the_Dataset>LULC_India_V2</Name_of_the_Dataset>
        <Theme>Landcover</Theme>
        <Keywords>Land Use Land Cover,India,ISRO,NRSC</Keywords>
        <Data_Type>Land Cover</Data_Type>
    </Data_Identification_Information>
    <Coverage>
        <Upper_left>X = 68 E, Y = 37 N</Upper_left>
        <Upper_right>X = 97 E, Y = 37 N</Upper_right>
        <Lower_right>X = 97 E, Y = 6 N</Lower_right>
        <Lower_left>X = 68 E, Y = 6 N</Lower_left>
    </Coverage>
    <Dataset_Topic_Category><Data_Identification_topic_category>Land Cover/Land Use</Data_Identification_topic_category></Dataset_Topic_Category>
</metadata>
""")
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(68.0, 6.0, 97.0, 37.0, 10, 10)
            with rasterio.open(
                "/tmp/test_lulc_raster.tif",
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
            with open("/tmp/test_lulc_raster.tif", "rb") as f:
                zf.writestr("lulc.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["dataset_type"] == "LULC"
        assert result["confidence"] == "high"
        assert len(result["classification"]["evidence"]) > 0
        dest = Path(result["location"])
        assert dest.exists()
        assert str(dest).endswith(str(Path("data") / "raw" / "landcover" / "LULC" / "UNKNOWN" / "V2"))

    def test_multi_file_dataset_inventory(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "multi_file.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="e43g">
    <Data_Identification_Information>
        <Name_of_the_Dataset>MultiFile_DEM_V1</Name_of_the_Dataset>
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
            zf.writestr("readme.txt", "Test dataset")
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
            with rasterio.open(
                "/tmp/test_multi_raster1.tif",
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
            with open("/tmp/test_multi_raster1.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

            data2 = np.ones((10, 10), dtype=np.float32) * 2
            with rasterio.open(
                "/tmp/test_multi_raster2.tif",
                "w",
                driver="GTiff",
                height=10,
                width=10,
                count=1,
                dtype=data2.dtype,
                crs="EPSG:4326",
                transform=transform,
            ) as dst:
                dst.write(data2, 1)
            with open("/tmp/test_multi_raster2.tif", "rb") as f:
                zf.writestr("slope.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]
        dest = Path(result["location"])
        assert dest.exists()
        assert (dest / "dem.tif").exists()
        assert (dest / "slope.tif").exists()
        assert (dest / "readme.txt").exists()
        assert (dest / "metadata.xml").exists()
        assert (dest / "manifest.json").exists()

        files = result["files"]
        file_names = [f["name"] for f in files]
        assert "dem.tif" in file_names
        assert "slope.tif" in file_names
        assert "readme.txt" in file_names
        assert "metadata.xml" in file_names

        from backend.app.ingestion.catalog import get_dataset_files
        db_files = get_dataset_files(str(tmp_workspace), dataset_id)
        db_file_names = [f["file_name"] for f in db_files]
        assert "dem.tif" in db_file_names
        assert "slope.tif" in db_file_names
        assert "readme.txt" in db_file_names
        assert "metadata.xml" in db_file_names

        spatial_files = [f for f in db_files if f.get("spatial")]
        assert len(spatial_files) == 2

    def test_search_and_filter(self, tmp_workspace):
        zip1 = tmp_workspace / "data" / "incoming" / "search_dem1.zip"
        with zipfile.ZipFile(zip1, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="e43g">
    <Data_Identification_Information>
        <Name_of_the_Dataset>Search_DEM_E43G_V1</Name_of_the_Dataset>
        <Theme>Terrain</Theme>
        <Keywords>DEM</Keywords>
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
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
            with rasterio.open("/tmp/test_search_raster1.tif", "w", driver="GTiff", height=10, width=10, count=1, dtype=data.dtype, crs="EPSG:4326", transform=transform) as dst:
                dst.write(data, 1)
            with open("/tmp/test_search_raster1.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())
        ingest_dataset(str(zip1), str(tmp_workspace))

        zip2 = tmp_workspace / "data" / "incoming" / "search_lulc.zip"
        with zipfile.ZipFile(zip2, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata>
    <Data_Identification_Information>
        <Name_of_the_Dataset>Search_LULC_India_V1</Name_of_the_Dataset>
        <Theme>Landcover</Theme>
        <Keywords>Land Use Land Cover,India,ISRO,NRSC</Keywords>
        <Data_Type>Land Cover</Data_Type>
    </Data_Identification_Information>
    <Coverage>
        <Upper_left>X = 68 E, Y = 37 N</Upper_left>
        <Upper_right>X = 97 E, Y = 37 N</Upper_right>
        <Lower_right>X = 97 E, Y = 6 N</Lower_right>
        <Lower_left>X = 68 E, Y = 6 N</Lower_left>
    </Coverage>
    <Dataset_Topic_Category><Data_Identification_topic_category>Land Cover/Land Use</Data_Identification_topic_category></Dataset_Topic_Category>
</metadata>
""")
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(68.0, 6.0, 97.0, 37.0, 10, 10)
            with rasterio.open("/tmp/test_search_raster2.tif", "w", driver="GTiff", height=10, width=10, count=1, dtype=data.dtype, crs="EPSG:4326", transform=transform) as dst:
                dst.write(data, 1)
            with open("/tmp/test_search_raster2.tif", "rb") as f:
                zf.writestr("lulc.tif", f.read())
        ingest_dataset(str(zip2), str(tmp_workspace))

        from backend.app.ingestion.catalog import search_datasets
        dem_results = search_datasets(str(tmp_workspace), {"dataset_type": "DEM"})
        assert len(dem_results) == 1
        assert dem_results[0]["dataset_type"] == "DEM"

        lulc_results = search_datasets(str(tmp_workspace), {"dataset_type": "LULC"})
        assert len(lulc_results) == 1
        assert lulc_results[0]["dataset_type"] == "LULC"

        theme_results = search_datasets(str(tmp_workspace), {"theme": "terrain"})
        assert len(theme_results) == 1

        name_results = search_datasets(str(tmp_workspace), {"dataset_name": "Search"})
        assert len(name_results) == 2

    def test_spatial_overlap_detection(self, tmp_workspace):
        zip1 = tmp_workspace / "data" / "incoming" / "overlap_a.zip"
        with zipfile.ZipFile(zip1, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="e43g">
    <Data_Identification_Information>
        <Name_of_the_Dataset>Overlap_A_V1</Name_of_the_Dataset>
        <Theme>Terrain</Theme>
        <Keywords>DEM</Keywords>
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
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
            with rasterio.open("/tmp/test_overlap_a.tif", "w", driver="GTiff", height=10, width=10, count=1, dtype=data.dtype, crs="EPSG:4326", transform=transform) as dst:
                dst.write(data, 1)
            with open("/tmp/test_overlap_a.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())
        result_a = ingest_dataset(str(zip1), str(tmp_workspace))
        assert result_a["status"] == "success"

        from backend.app.ingestion.catalog import check_spatial_overlap
        overlaps = check_spatial_overlap(str(tmp_workspace), "DEM", {
            "west": 72.0, "south": 18.0, "east": 73.0, "north": 19.0,
        }, exclude_dataset_id=result_a["dataset_id"])
        assert len(overlaps) == 0

        overlaps_all = check_spatial_overlap(str(tmp_workspace), "DEM", {
            "west": 72.0, "south": 18.0, "east": 73.0, "north": 19.0,
        })
        assert len(overlaps_all) == 1

    def test_dataset_relationships(self, tmp_workspace):
        zip1 = tmp_workspace / "data" / "incoming" / "rel_source.zip"
        with zipfile.ZipFile(zip1, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="e43g">
    <Data_Identification_Information>
        <Name_of_the_Dataset>Rel_Source_V1</Name_of_the_Dataset>
        <Theme>Terrain</Theme>
        <Keywords>DEM</Keywords>
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
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
            with rasterio.open("/tmp/test_rel_source.tif", "w", driver="GTiff", height=10, width=10, count=1, dtype=data.dtype, crs="EPSG:4326", transform=transform) as dst:
                dst.write(data, 1)
            with open("/tmp/test_rel_source.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())
        result_source = ingest_dataset(str(zip1), str(tmp_workspace))
        assert result_source["status"] == "success"

        zip2 = tmp_workspace / "data" / "incoming" / "rel_derived.zip"
        with zipfile.ZipFile(zip2, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="e43g">
    <Data_Identification_Information>
        <Name_of_the_Dataset>Rel_Derived_Slope_V1</Name_of_the_Dataset>
        <Theme>Terrain</Theme>
        <Keywords>DEM</Keywords>
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
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
            with rasterio.open("/tmp/test_rel_derived.tif", "w", driver="GTiff", height=10, width=10, count=1, dtype=data.dtype, crs="EPSG:4326", transform=transform) as dst:
                dst.write(data, 1)
            with open("/tmp/test_rel_derived.tif", "rb") as f:
                zf.writestr("slope.tif", f.read())
        result_derived = ingest_dataset(str(zip2), str(tmp_workspace))
        assert result_derived["status"] == "success"

        from backend.app.ingestion.catalog import insert_dataset_relationship, get_dataset_relationships
        insert_dataset_relationship(str(tmp_workspace), result_derived["dataset_id"], result_source["dataset_id"], "derived_from")

        rels = get_dataset_relationships(str(tmp_workspace), result_derived["dataset_id"])
        assert len(rels) == 1
        assert rels[0]["relationship_type"] == "derived_from"
        assert rels[0]["related_dataset_id"] == result_source["dataset_id"]

    def test_quality_report_generated(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "quality_report.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="e43g">
    <Data_Identification_Information>
        <Name_of_the_Dataset>Quality_Report_Test_V1</Name_of_the_Dataset>
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
            zf.writestr("readme.txt", "Test dataset")
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(72.0, 18.0, 73.0, 19.0, 10, 10)
            with rasterio.open(
                "/tmp/test_quality_raster.tif",
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
            with open("/tmp/test_quality_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        assert "quality" in result
        quality = result["quality"]
        assert "score" in quality
        assert "missing_fields" in quality
        assert "spatial_quality" in quality
        assert "file_quality" in quality
        assert "classification" in quality
        assert quality["spatial_quality"]["has_bounds"] is True
        assert quality["file_quality"]["total_files"] >= 2

    def test_metadata_history_tracks_changes(self, tmp_workspace):
        zip_path = tmp_workspace / "data" / "incoming" / "history_test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata>
    <Data_Identification_Information>
        <Name_of_the_Dataset>History_Test_V1</Name_of_the_Dataset>
        <Theme>Terrain</Theme>
        <Keywords>DEM</Keywords>
        <Data_Type>Elevation</Data_Type>
    </Data_Identification_Information>
    <Coverage>
        <Upper_left>X = 66 E, Y = 40 N</Upper_left>
        <Upper_right>X = 70 E, Y = 40 N</Upper_right>
        <Lower_right>X = 70 E, Y = 36 N</Lower_right>
        <Lower_left>X = 66 E, Y = 36 N</Lower_left>
    </Coverage>
</metadata>
""")
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(66.0, 36.0, 70.0, 40.0, 10, 10)
            with rasterio.open(
                "/tmp/test_history_raster.tif",
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
            with open("/tmp/test_history_raster.tif", "rb") as f:
                zf.writestr("dem.tif", f.read())

        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "needs_review"
        dataset_id = result["dataset_id"]

        from backend.app.ingestion.catalog import record_metadata_history, get_metadata_history, get_dataset, update_dataset
        from backend.app.ingestion.organizer import generate_manifest, write_manifest
        import json

        ds = get_dataset(str(tmp_workspace), dataset_id)
        old_tile = ds.get("tile", "UNKNOWN")
        record_metadata_history(str(tmp_workspace), dataset_id, "tile", old_tile, "E43G", "manual")
        update_dataset(str(tmp_workspace), dataset_id, {"tile": "E43G"})

        dest = Path(result["location"])
        manifest_path = dest / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            manifest["tile"] = "E43G"
            write_manifest(dest, manifest)

        history = get_metadata_history(str(tmp_workspace), dataset_id)
        assert len(history) == 1
        assert history[0]["field"] == "tile"
        assert history[0]["old_value"] == old_tile
        assert history[0]["new_value"] == "E43G"
        assert history[0]["source"] == "manual"


class TestDatasetManagementAPI:
    @pytest.fixture
    def tmp_workspace(self, tmp_path):
        base = tmp_path / "workspace"
        base.mkdir()
        (base / "data" / "incoming").mkdir(parents=True)
        (base / "data" / "processing").mkdir(parents=True)
        (base / "data" / "catalog").mkdir(parents=True)
        (base / "data" / "raw").mkdir(parents=True)
        return base

    def _create_real_bhuvan_zip(self, tmp_workspace, name="test_bhuvan.zip"):
        zip_path = tmp_workspace / "data" / "incoming" / name
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="e43g">
    <Data_Identification_Information>
        <Name_of_the_Dataset>API_Test_V1</Name_of_the_Dataset>
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
    <Citation>
        <Lineage>
            <Tile_Name>e43g</Tile_Name>
            <Resolution>1 arc sec</Resolution>
            <File_Format>Geotiff</File_Format>
        </Lineage>
    </Citation>
    <Dataset_Topic_Category>
        <Data_Identification_topic_category>Digital Elevation Model</Data_Identification_topic_category>
    </Dataset_Topic_Category>
    <For_Image_Data>
        <Name_of_the_Satellite>Cartosat-1</Name_of_the_Satellite>
        <Sensor>PAN(2.5m) Stereo Data</Sensor>
        <File_Format>Geotiff</File_Format>
        <Bits_per_Pixel>16bit</Bits_per_Pixel>
        <Spatial_Resolution>1arc sec</Spatial_Resolution>
    </For_Image_Data>
</metadata>
""")
            data = np.ones((10, 10), dtype=np.float32)
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

    def test_rename_api(self, tmp_workspace):
        from fastapi.testclient import TestClient
        from backend.app.main import app
        from backend.app.api import datasets as datasets_module

        zip_path = self._create_real_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.put(
                f"/api/datasets/{dataset_id}/rename",
                json={"dataset_name": "Renamed_Dataset"}
            )
        finally:
            datasets_module.BASE_DIR = original_base
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["operation"] == "rename"
        assert body["dataset"]["dataset_name"] == "Renamed_Dataset"
        assert body["dataset"]["id"] == dataset_id

        ds = get_dataset(str(tmp_workspace), dataset_id)
        assert ds["dataset_name"] == "Renamed_Dataset"

    def test_classify_api(self, tmp_workspace):
        from fastapi.testclient import TestClient
        from backend.app.main import app
        from backend.app.api import datasets as datasets_module

        zip_path = self._create_real_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.put(
                f"/api/datasets/{dataset_id}/classify",
                json={"dataset_type": "DSM", "theme": "satellite"}
            )
        finally:
            datasets_module.BASE_DIR = original_base
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["operation"] == "classify"
        assert body["dataset"]["dataset_type"] == "DSM"
        assert body["dataset"]["theme"] == "satellite"
        assert "E43G" in body["dataset"]["location"]

        ds = get_dataset(str(tmp_workspace), dataset_id)
        assert ds["dataset_type"] == "DSM"
        assert ds["theme"] == "satellite"

    def test_reprocess_api(self, tmp_workspace):
        from fastapi.testclient import TestClient
        from backend.app.main import app
        from backend.app.api import datasets as datasets_module

        zip_path = self._create_real_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]
        original_count = len(datasets_module.search_datasets(str(tmp_workspace), {}))

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.post(f"/api/datasets/{dataset_id}/reprocess")
        finally:
            datasets_module.BASE_DIR = original_base
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["operation"] == "reprocess"
        assert body["dataset"]["dataset_type"] == "DEM"
        assert body["dataset"]["tile"] == "E43G"
        assert body["dataset"]["id"] == dataset_id

        new_count = len(datasets_module.search_datasets(str(tmp_workspace), {}))
        assert new_count == original_count

    def test_delete_permanent_api(self, tmp_workspace):
        from fastapi.testclient import TestClient
        from backend.app.main import app
        from backend.app.api import datasets as datasets_module

        zip_path = self._create_real_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)
            response = client.delete(f"/api/datasets/{dataset_id}?permanent=true")
        finally:
            datasets_module.BASE_DIR = original_base
        assert response.status_code == 200
        body = response.json()
        assert body["deleted"] is True
        assert body["mode"] == "permanent"

        assert get_dataset(str(tmp_workspace), dataset_id) is None

    def test_soft_delete_and_restore_api(self, tmp_workspace):
        from fastapi.testclient import TestClient
        from backend.app.main import app
        from backend.app.api import datasets as datasets_module

        zip_path = self._create_real_bhuvan_zip(tmp_workspace)
        result = ingest_dataset(str(zip_path), str(tmp_workspace))
        assert result["status"] == "success"
        dataset_id = result["dataset_id"]

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)

            response = client.delete(f"/api/datasets/{dataset_id}")
            assert response.status_code == 200
            assert response.json()["deleted"] is True

            assert get_dataset(str(tmp_workspace), dataset_id) is None

            response = client.post(f"/api/datasets/{dataset_id}/restore")
            assert response.status_code == 200
            assert response.json()["restored"] is True

            ds = get_dataset(str(tmp_workspace), dataset_id)
            assert ds is not None
        finally:
            datasets_module.BASE_DIR = original_base


class TestEndToEndDatasetLifecycle:
    @pytest.fixture
    def tmp_workspace(self, tmp_path):
        base = tmp_path / "workspace"
        base.mkdir()
        (base / "data" / "incoming").mkdir(parents=True)
        (base / "data" / "processing").mkdir(parents=True)
        (base / "data" / "catalog").mkdir(parents=True)
        (base / "data" / "raw").mkdir(parents=True)
        return base

    def test_full_dataset_lifecycle(self, tmp_workspace):
        from fastapi.testclient import TestClient
        from backend.app.main import app
        from backend.app.api import datasets as datasets_module

        zip_path = tmp_workspace / "data" / "incoming" / "lifecycle_test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("metadata.xml", """<?xml version="1.0"?>
<metadata tileno="f43u">
    <Data_Identification_Information>
        <Name_of_the_Dataset>Lifecycle_Test_V1</Name_of_the_Dataset>
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
            zf.writestr("readme.txt", "Test dataset for lifecycle")
            data = np.ones((10, 10), dtype=np.float32)
            transform = from_bounds(73.0, 19.0, 74.0, 20.0, 10, 10)
            with rasterio.open(
                str(tmp_workspace / "dem1.tif"),
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
            with open(str(tmp_workspace / "dem1.tif"), "rb") as f:
                zf.writestr("dem1.tif", f.read())
            data2 = np.ones((10, 10), dtype=np.float32) * 2
            with rasterio.open(
                str(tmp_workspace / "dem2.tif"),
                "w",
                driver="GTiff",
                height=10,
                width=10,
                count=1,
                dtype=data2.dtype,
                crs="EPSG:4326",
                transform=transform,
            ) as dst:
                dst.write(data2, 1)
            with open(str(tmp_workspace / "dem2.tif"), "rb") as f:
                zf.writestr("dem2.tif", f.read())

        original_base = datasets_module.BASE_DIR
        datasets_module.BASE_DIR = Path(str(tmp_workspace))
        try:
            client = TestClient(app)

            response = client.post(
                "/api/datasets/upload",
                files={"file": ("lifecycle_test.zip", zip_path.open("rb"), "application/zip")},
            )
            assert response.status_code == 200
            upload_result = response.json()
            assert upload_result["summary"]["processed"] == 1
            assert upload_result["summary"]["errors"] == 0
            dataset_id = upload_result["results"][0]["dataset_id"]

            initial_count = len(datasets_module.search_datasets(str(tmp_workspace), {}))
            assert initial_count == 1

            detail_response = client.get(f"/api/datasets/{dataset_id}")
            assert detail_response.status_code == 200
            detail = detail_response.json()
            assert detail["dataset_name"] == "Lifecycle_Test_V1"
            assert detail["dataset_type"] == "DEM"
            assert detail["theme"] == "terrain"
            assert detail["tile"] == "F43U"
            assert detail["version"] == "V1"
            assert detail["platform"] == "Cartosat-1"
            assert detail["sensor"] == "PAN(2.5m) Stereo Data"
            assert detail["source"] == "Bhuvan / NRSC / ISRO"
            assert len(detail["files"]) >= 2
            spatial_files = [f for f in detail["files"] if f["spatial"]]
            assert len(spatial_files) == 2
            assert detail["bounds"] is not None
            assert detail["classification"]["dataset_type"] == "DEM"

            rename_response = client.put(
                f"/api/datasets/{dataset_id}/rename",
                json={"dataset_name": "Renamed_Lifecycle_Test"}
            )
            assert rename_response.status_code == 200
            rename_body = rename_response.json()
            assert rename_body["operation"] == "rename"
            assert rename_body["dataset"]["dataset_name"] == "Renamed_Lifecycle_Test"
            assert rename_body["dataset"]["id"] == dataset_id

            classify_response = client.put(
                f"/api/datasets/{dataset_id}/classify",
                json={"dataset_type": "DSM", "theme": "satellite", "tile": "F43U", "version": "V2"}
            )
            assert classify_response.status_code == 200
            classify_body = classify_response.json()
            assert classify_body["operation"] == "classify"
            assert classify_body["dataset"]["dataset_type"] == "DSM"
            assert classify_body["dataset"]["theme"] == "satellite"
            assert classify_body["dataset"]["tile"] == "F43U"
            assert classify_body["dataset"]["version"] == "V2"
            assert "F43U/V2" in classify_body["dataset"]["location"]

            new_path = Path(tmp_workspace) / classify_body["dataset"]["location"]
            assert new_path.exists()
            assert (new_path / "dem1.tif").exists()
            assert (new_path / "dem2.tif").exists()
            assert (new_path / "metadata.xml").exists()
            assert (new_path / "readme.txt").exists()

            count_after_classify = len(datasets_module.search_datasets(str(tmp_workspace), {}))
            assert count_after_classify == initial_count

            reprocess_response = client.post(f"/api/datasets/{dataset_id}/reprocess")
            assert reprocess_response.status_code == 200
            reprocess_body = reprocess_response.json()
            assert reprocess_body["status"] == "success"
            assert reprocess_body["operation"] == "reprocess"
            assert reprocess_body["dataset"]["id"] == dataset_id
            assert reprocess_body["dataset"]["dataset_type"] == "DEM"
            assert reprocess_body["dataset"]["tile"] == "F43U"

            count_after_reprocess = len(datasets_module.search_datasets(str(tmp_workspace), {}))
            assert count_after_reprocess == initial_count

            soft_delete_response = client.delete(f"/api/datasets/{dataset_id}")
            assert soft_delete_response.status_code == 200
            assert soft_delete_response.json()["deleted"] is True

            visible_after_soft = len(datasets_module.search_datasets(str(tmp_workspace), {}))
            assert visible_after_soft == 0

            restore_response = client.post(f"/api/datasets/{dataset_id}/restore")
            assert restore_response.status_code == 200
            assert restore_response.json()["restored"] is True

            visible_after_restore = len(datasets_module.search_datasets(str(tmp_workspace), {}))
            assert visible_after_restore == initial_count

            perm_delete_response = client.delete(f"/api/datasets/{dataset_id}?permanent=true")
            assert perm_delete_response.status_code == 200
            perm_body = perm_delete_response.json()
            assert perm_body["deleted"] is True
            assert perm_body["mode"] == "permanent"
            assert len(perm_body["deleted_files"]) > 0

            assert get_dataset(str(tmp_workspace), dataset_id) is None
            assert not new_path.exists()

            final_count = len(datasets_module.search_datasets(str(tmp_workspace), {}))
            assert final_count == 0
        finally:
            datasets_module.BASE_DIR = original_base
