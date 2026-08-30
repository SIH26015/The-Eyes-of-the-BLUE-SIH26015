# Architecture

## Module Boundaries

```text
Module_1 (Frontend & Visualization)
    │ HTTP
    ▼
Module_2 (Backend + Data Engine + API)
    │
    │ Python import
    ▼
Module_3 (Geospatial Analysis Engine)
```

## Module Responsibilities

### Module_0 — Research & Planning
- Study area management
- Data requirements tracking
- Acquisition grid (1°×1°) management
- Collection session logging
- Catalog ingestion bridge (stub)

### Module_1 — Frontend & Visualization
- Streamlit interactive UI (legacy prototype)
- Express + Leaflet map interface (active frontend)
- Map generation utilities
- EXIF photo evidence extraction

### Module_2 — Backend + Data Engine
- FastAPI REST API
- Dataset ingestion pipeline
- Catalog management (SQLite)
- Metadata parsing (Bhuvan XML, GeoTIFF)
- Dataset classification
- Spatial search and discovery
- Analysis API endpoints

### Module_3 — Analysis Engine
- Terrain analysis (DEM/DSM: elevation, slope, aspect, hillshade)
- Vegetation analysis (NDVI)
- Analysis result registry
- Dataset loading abstractions

## Data Flow

1. User uploads dataset via Module 2 API or Module 1 UI
2. Module 2 ingests, validates, classifies, and catalogs the dataset
3. Module 2 stores data under `data/raw/{theme}/{type}/{tile}/{version}/`
4. User requests analysis via Module 2 API
5. Module 2 calls Module 3 analysis engine with dataset contract
6. Module 3 returns analysis results
7. Module 2 stores results under `data/analysis/{analysis_id}/`

## Dependency Rules

- Module 1 → Module 2 (HTTP)
- Module 2 → Module 3 (Python import)
- Module 3 must NOT import Module 2
- Module 0 → Module 2 (stub, not yet wired)
