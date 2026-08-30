# Data Contract

## Directory Structure

```
data/
├── raw/                    # Source datasets
│   └── {theme}/{type}/{tile}/{version}/
│       ├── manifest.json
│       ├── metadata.xml (optional)
│       └── {dataset_files}
├── incoming/               # Upload staging area
├── processing/             # Temporary unzip/processing workspace
├── quarantine/             # Failed validation holding area
├── analysis/               # Analysis outputs
│   └── {analysis_id}/
│       ├── result.json
│       └── {output_rasters}
├── catalog/                # SQLite catalog database
└── sample/                 # Test fixtures and demo data
```

## Manifest Schema

Every dataset directory must contain a `manifest.json` with:
- `dataset_id`, `dataset_name`, `dataset_type`
- `theme`, `tile`, `version`
- `spatial_metadata` (bounds, crs, resolution, format)
- `platform`, `sensor`, `bits_per_pixel`
- `files` (inventory with roles and checksums)
- `classification` (type, confidence, evidence)
- `quality` (score, missing_fields, spatial_quality, file_quality)
- `metadata_provenance` (source tracking for each field)

## File Roles

- `primary` — Main data file (GeoTIFF, shapefile, etc.)
- `metadata` — XML, JSON, or text metadata
- `supporting` — Auxiliary files
- `documentation` — Readme, license, policy

## Status Values

- `READY` — Fully ingested and cataloged
- `NEEDS_REVIEW` — Insufficient metadata, manual review required
- `PROCESSING` — Currently being ingested
- `QUARANTINED` — Failed validation
- `DELETED` — Soft deleted
