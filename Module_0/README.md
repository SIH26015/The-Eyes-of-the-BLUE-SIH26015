# Module 0 — Data Acquisition & Research Tracker

Control room for your entire data collection operation. Tracks what data you need, what you have, and what is still missing.

## Architecture

```text
                  MODULE 0
         DATA ACQUISITION & RESEARCH
                   │
       ┌───────────┼───────────┐
       ↓           ↓           ↓
  REQUIREMENTS   COVERAGE    RESEARCH LOG
       │           │           │
       ↓           ↓           ↓
  What do we    What do we   What remains?
  need?         have?
       │           │
       └───────────┼───────────┐
                   ↓           ↓
           ACQUISITION QUEUE   CATALOG
                   │           │
                   ↓           ↓
            [Module 2 stub]   [Module 2 → Module 0 ingest endpoint exists
                                but Module 2 does not yet push data to it]
```

## Status

| Component | Status |
|-----------|--------|
| Study Areas & Requirements | ✅ Implemented |
| Acquisition Grids (1°×1°) | ✅ Implemented |
| Collection Sessions | ✅ Implemented |
| Coverage & Queue Analytics | ✅ Implemented |
| Module 2 → Module 0 Ingest | 🟡 Stub endpoint exists; not yet wired from Module 2 |

## Install

```bash
cd Module_0
pip install -e ".[dev]"
```

## Run

```bash
python -m module0.main
```

Then open: `http://localhost:8000`

## Key Concepts

- **Study Area**: Geographic region of interest (e.g., Chandwad Watershed)
- **Data Requirement**: What datasets you need (DEM, Satellite, Rainfall, etc.)
- **Acquisition Grid**: 1×1 degree blocks for tracking spatial coverage
- **Collection Session**: Records of when and where you collected data
- **Catalog**: Metadata ingested from Module 2 (manual or via stub API)

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/study-areas` | List all study areas |
| POST | `/api/study-areas` | Create a study area |
| GET | `/api/study-areas/{id}` | Get study area details |
| GET | `/api/study-areas/{id}/requirements` | List requirements for area |
| POST | `/api/requirements` | Add a data requirement |
| GET | `/api/study-areas/{id}/coverage` | Calculate coverage stats |
| GET | `/api/study-areas/{id}/queue` | Get acquisition queue |
| POST | `/api/sessions` | Log a collection session |
| GET | `/api/sessions` | List collection sessions |
| POST | `/api/ingest/module2` | Ingest metadata from Module 2 (stub) |
| GET | `/api/catalog` | List catalog entries |
| POST | `/api/grids` | Create acquisition grid |
| GET | `/api/grids` | List grids |
| PATCH | `/api/blocks/{id}` | Update grid block status |
