# The Eyes of the BLUE — SIH26015

Spatial data engineering platform for India. Four-module architecture for data acquisition, visualization, ingestion, and geospatial analysis.

## Architecture

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

| Module | Responsibility |
|--------|---------------|
| `Module_0` | Research & planning — study areas, requirements, acquisition grids |
| `Module_1` | Frontend — Streamlit UI + Express/Leaflet map interface |
| `Module_2` | Backend — FastAPI, dataset ingestion, catalog, API endpoints |
| `Module_3` | Analysis — terrain, vegetation/NDVI, result registry |

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 16+ (for Module 1 Express server)
- PostgreSQL (optional — Module 1 falls back to in-memory store)

### Setup

```bash
# Python dependencies
cd Module_2
pip install -r requirements.txt

# Node dependencies
cd Module_1
npm install
```

### Run

```bash
# Terminal 1 — Module 2 backend
cd Module_2
uvicorn backend.app.main:app --reload --port 8000

# Terminal 2 — Module 1 Express server
cd Module_1
node server.js

# Terminal 3 — Module 0 dashboard (optional)
cd Module_0
pip install -e ".[dev]"
python -m module0.main
```

### Tests

```bash
cd Module_2
pytest
```

## Data

Raw datasets, analysis outputs, and runtime data live under `data/`. Large files are gitignored.

## Documentation

See `docs/` for architecture, API contracts, and team ownership.

## License

MIT
