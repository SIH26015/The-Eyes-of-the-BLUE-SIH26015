PROJECT_CONTEXT.md describes architectural intent and project rules. Source code and tests are the final authority for current implementation behavior.

# The Eyes of the BLUE — Project Context & AI/Developer Guide

## 1. Instructions for AI Coding Agents

Before modifying any code in this repository:

- Read this file completely.
- Inspect the relevant existing files before changing anything.
- Do not assume the architecture from folder names alone.
- Preserve currently working pipelines unless explicitly asked to replace them.
- Do not create duplicate implementations of existing functionality.
- Do not create a second backend or a separate Module 3 server.
- Do not introduce circular dependencies.
- Do not use `sys.path.append()` or similar path hacks to solve imports.
- Run relevant tests after every meaningful code change.
- Report exactly: what changed, why it changed, files affected, tests run, limitations remaining.
- Do not silently delete old/prototype functionality.
- If existing code conflicts with this architecture, inspect and report the conflict before performing a large refactor.
- Prefer small, testable changes over large speculative rewrites.
- Do not claim a scientific result is valid without checking the input data, CRS, bands, NoData handling, units, and assumptions.
- Do not add new scientific indicators simply because they are available. Every indicator must support the watershed problem being solved.

## 2. Project Identity

**Project Name:** The Eyes of the BLUE

**SIH Problem:** SIH26015 — Application of Geospatial Techniques for Visualization and Analysis to Interpret Geo-Coded Images to Enhance Watershed Development Outcomes

**Organization:** Ministry of Rural Development, Department of Land Resources

**Theme:** Agriculture, FoodTech & Rural Development

**Category:** Software

## 3. What Problem Are We Actually Solving?

Watershed-related spatial data exists across different sources, dates, formats, spatial resolutions, and thematic layers.

The difficulty is not simply that data does not exist. The actual problem is:

- watershed data is fragmented
- datasets come from different sources
- datasets may use different CRS/resolutions
- some datasets are static while others change over time
- historical and current data can be difficult to compare
- field evidence is often disconnected from satellite analysis
- GIS and remote sensing analysis requires significant time and expertise
- decision makers need interpretable spatial insights rather than raw files

The project aims to reduce the effort required to turn heterogeneous geospatial data into useful watershed information.

## 4. Core Product Goal

The final system should help answer:

> Which parts of a watershed show important environmental change or stress signals, what indicators support that observation, and which areas should receive further attention?

The project must NOT claim that a single indicator proves environmental degradation or causation.

**Preferred language:** stress, change, priority, indication, spatial pattern, evidence, observed trend

**Avoid unsupported claims such as:**
- "this caused degradation"
- "AI proved this area is damaged"
- "NDVI decline proves watershed failure"

## 5. Scientific Mental Model

The watershed analysis is divided into two major categories.

**Static Context** (usually do not change significantly year to year):
- DEM, elevation, slope, aspect
- watershed boundary, terrain characteristics
- geology, soil class

These describe the physical setting and vulnerability of the watershed.

**Dynamic Conditions** (change over time):
- vegetation, NDVI
- land use / land cover
- surface water extent
- rainfall, temperature/climate patterns
- field observations, temporal satellite imagery

These are the main monitoring signals.

The long-term intelligence layer will combine static vulnerability with dynamic change.

## 6. High-Level Scientific Pipeline

```
STATIC DATA
DEM → Terrain → Slope → Aspect
        │
        ├──────────────┐
        │              │
        ▼              ▼

DYNAMIC DATA        FIELD EVIDENCE
Satellite           Geo-coded photos
NDVI                Observations
Water indicators
Rainfall
        │
        └──────────────┐
                       ▼

             SPATIAL ANALYSIS
                       │
                       ▼
              TEMPORAL CHANGE
                       │
                       ▼
             ASSESSMENT INDICATORS
                       │
                       ▼
             PRIORITY / INTERPRETATION
                       │
                       ▼
              MODULE 1 WORKSPACE
```

## 7. Current Project Architecture

The project uses four conceptual modules:

- **Module 0** — Data Planning & Acquisition Tracking
- **Module 2** — Data Engine & Backend
- **Module 3** — Geospatial Analysis Engine
- **Module 1** — Visualization & Decision Workspace

The conceptual processing flow is:

```
Module 0  →  "What data do we need?"
       ↓
Module 2  →  "Is the data valid and usable?"
       ↓
Module 3  →  "What does the data indicate?"
       ↓
Module 1  →  "How can the user understand it?"
```

The numeric module order is historical and does not represent runtime order.

## 8. Runtime Architecture

There must be **ONE integrated backend runtime**.

The dependency direction is:

```
Module_1  (Frontend)
    │
    │ HTTP
    ▼
Module_2  (FastAPI + Data Engine + APIs)
    │
    │ Python dependency
    ▼
Module_3  (Analysis Engine)
```

**Allowed:**
- Module_1 → Module_2
- Module_2 → Module_3

**Forbidden:**
- Module_1 → Module_3 direct Python import
- Module_3 → Module_2
- Module_3 → Module_1
- Module_2 ↔ Module_3 circular dependency

Module 3 must remain an analysis/library layer. It must NOT:
- start its own FastAPI server
- create duplicate APIs
- depend on Module 2 database internals
- know anything about the frontend

## 9. Module Responsibilities

### MODULE 0 — Data Planning & Acquisition Manager

**Purpose:**
- define study areas
- define required datasets
- track what has been collected
- track what is missing
- track temporal coverage
- support data acquisition planning
- maintain acquisition history

Module 0 should eventually answer:
- What data do we need?
- What data do we already have?
- What locations are missing?
- What dates are missing?
- What should be collected next?

Module 0 is currently a supporting module and is NOT the main runtime dependency for analysis. Do not add major Module 0 features until the core Module 2 → Module 3 → Module 1 pipeline is stable.

### MODULE 1 — Watershed GIS Workspace

**Purpose:**
- interactive map
- analysis visualization
- dataset selection
- layer controls
- result panels
- legends
- spatial interaction
- decision-support presentation

Module 1 should eventually display:
- DEM, slope, aspect
- satellite imagery, NDVI
- temporal change, water indicators
- watershed boundaries, assessment zones, priority zones
- geo-coded evidence

Module 1 should NOT perform scientific raster analysis. It consumes backend APIs.

### MODULE 2 — Geospatial Data Engine

**Purpose:**
- upload/import datasets
- ZIP handling, GeoTIFF validation
- metadata extraction, XML metadata parsing
- classification, file organization, manifest generation
- catalog registration, duplicate detection
- lifecycle management, analysis readiness validation
- API exposure

Module 2 answers: "What data exists, where is it, and is it safe/ready for analysis?"

It is currently the most mature part of the project. Module 2 may call Module 3 for scientific analysis.

### MODULE 3 — Watershed Intelligence / Analysis Engine

**Purpose:**
- terrain analysis, raster processing
- vegetation analysis, temporal analysis
- future water indicators, future assessment logic

**Current/foundation analysis includes:**
- elevation statistics
- slope, aspect, hillshade where supported
- NDVI

**Future functionality may include, only when actually implemented:**
- NDVI temporal change
- NDWI / water change
- rainfall indicators
- spatial assessment units
- composite assessment
- confidence calculation
- prioritization

Do not create future files or APIs until work on those features begins.

## 10. Current Working Vertical Pipelines

### Terrain Pipeline
```
Real Cartosat DEM
    ↓
Module 2 ingestion/catalog
    ↓
Analysis-ready dataset
    ↓
Module 3 terrain analysis
    ↓
Slope / Aspect / Elevation statistics
    ↓
Module 2 API
    ↓
Module 1 map/results UI
```

Terrain analysis was tested against real EPSG:4326 Cartosat DEM data.

**Known validated example:**
- DEM CRS: EPSG:4326
- ~1 arc-second resolution
- slope mean around 8.5°
- slope maximum around 74.8°
- aspect range approximately 0–360°

**Important scientific rule:** Do not treat geographic degree resolution as meters. CRS-aware pixel spacing must be used for slope calculations.

### NDVI Pipeline
```
Satellite Raster
    ↓
RED + NIR bands
    ↓
Module 3 NDVI
    ↓
Module 2 API
    ↓
Module 1 visualization
```

## 11. Data Source Documentation Rules

Every important dataset should ideally record:
- Dataset name, type, source
- Satellite/sensor, acquisition date, temporal period
- Resolution, CRS, bands
- Coverage/bounds, file format
- License/access condition
- Why the dataset is used

The data strategy should distinguish: **STATIC DATA** vs **DYNAMIC DATA**

## 12. Shared Data Policy

Large operational datasets must not be casually committed to Git.

**Recommended conceptual structure:**
```
data/
├── sample/       # Small reproducible sample data (intentionally tracked)
├── raw/          # Large downloaded source datasets (normally ignored)
└── derived/      # Generated analysis results (normally ignored)
```

Do not create new random data directories inside modules unless the architecture explicitly requires them.

## 13. Current Project Status

The project is approximately 40–50% complete overall. This is only an estimate.

**Approximate status:**
- Architecture / Problem Understanding: ~85%
- Module 0: ~60%
- Module 1: ~45–50%
- Module 2: ~80–85%
- Module 3 analysis foundation: ~50–60%
- Real DEM integration: Working
- Terrain vertical pipeline: Working
- NDVI algorithm: Working
- Real satellite validation: Partial
- Temporal change detection: Not complete
- Water-change analysis: Not complete
- Composite watershed assessment: Not complete
- Priority-zone decision engine: Not complete
- Final product integration: Partial

Do not artificially inflate these numbers in documentation or presentations.

## 14. Immediate Project Priority

The immediate project priority is NOT adding more features. The current priority is:

```
STABILIZE → CLEAN → VERIFY → DOCUMENT → CREATE GITHUB BASELINE → TEAM PARALLEL DEVELOPMENT
```

Before the next feature phase:
- fix existing broken operations
- remove path fragility
- classify legacy/prototype files
- verify startup commands
- verify full tests
- clean Git artifacts
- document reality
- establish stable collaboration baseline

## 15. Known Technical Debt / Issues

### Module 1
Contains multiple implementations/prototypes. Each must be classified as:
- ACTIVE
- UTILITY
- PROTOTYPE
- DEPRECATED
- UNCERTAIN

Do not add new features to deprecated prototypes.

### Module 2
The ingestion pipeline is large and contains multiple responsibilities. Do not rewrite it simply because it is long. Refactor only when:
- responsibility is clearly separable
- tests protect the behavior
- the refactor solves a real maintainability problem

### Module 0
Database session lifecycle has required stabilization. Future modifications must ensure:
- sessions close correctly
- exceptions do not leak resources
- paths do not depend on current working directory

### Integration
Module 0 and Module 2 integration may currently be partial/stubbed. Do not claim complete integration unless verified in code.

## 16. Scientific Rules

### Terrain
Slope calculations must respect:
- CRS, pixel size, elevation units
- NoData, raster orientation

Do not calculate meters-per-pixel using degree resolution without CRS-aware handling.

### NDVI
Before NDVI:
- verify RED band, NIR band, sensor, band indexing
- handle division by zero
- handle NoData
- verify output range (-1 to +1)

Do not infer watershed health solely from NDVI.

### Temporal Analysis
When implemented, datasets from different dates must be checked for:
- CRS, spatial extent, resolution, alignment
- acquisition season, cloud/data quality, NoData

Comparing unaligned rasters is invalid.

### Composite Assessment
Future priority scoring must not use unexplained arbitrary weights. Weights must eventually be based on:
- literature
- expert reasoning
- documented assumptions
- configurable parameters
- potentially AHP or other accepted decision methods

The system should explain why a zone received a priority level.

## 17. Terminology Rules

**Preferred:**
- Assessment Cell
- Spatial Assessment Unit
- Priority Zone
- Observed Change
- Environmental Stress Indicator
- Potential Concern
- Field Evidence

**Avoid:**
- calling square grid cells "Sub-watersheds" unless they were actually hydrologically delineated
- unsupported causal language

## 18. Git & Collaboration Rules

Do not commit:
- venv/, .venv/, node_modules/
- __pycache__/, .pytest_cache/
- .env, runtime databases
- large raw GeoTIFFs
- generated analysis results
- logs, credentials, API keys

Use feature branches. Do not casually push experimental work directly into the stable branch.

Every meaningful change should include:
- Code
- Tests where relevant
- Documentation update if interface changes
- Integration verification

## 19. Current Test Baseline

Known baseline: Module 2 has 127 tests passing.

Before changing important backend or analysis behavior:
- Run relevant tests
- Run full Module 2 test suite if contracts change
- Run `git diff --check`
- Verify Python imports
- Smoke-test the affected end-to-end pipeline

Do not weaken or delete tests merely to make a change pass.

## 20. API Contract Rule

Frontend code must depend on stable API responses rather than backend internal file structures.

Example conceptual flow:
```
Module 1
   ↓
POST /api/analysis/terrain
   ↓
Module 2
   ↓
Module 3 terrain analysis
   ↓
Structured JSON response
```

If an API response changes:
- update `docs/API_CONTRACT.md`
- update frontend consumer
- update tests
- clearly report breaking changes

## 21. Architecture Change Rule

Before any major restructure:
- Identify active runtime
- Identify import dependencies
- Identify data path assumptions
- Identify API consumers
- Identify tests protecting the behavior
- Create a mapping of old path → new path
- Move one logical component at a time
- Run tests after each important move

Never perform a large folder cleanup merely for aesthetics.

## 22. Team Responsibilities

Current 6-person ownership model:

**Module 1 — Frontend**
- Suchali: GIS map, Leaflet, layers, spatial interaction, geospatial visualization
- Punyata: dashboard, user workflow, dataset selection, statistics panels, result presentation, UI/UX

**Module 2 — Backend/Data**
- Abhishek: ingestion, metadata, catalog, dataset lifecycle, classification
- Aadi: FastAPI, APIs, schemas, backend integration, error handling

**Module 3 — Analysis**
- Abhay: terrain analysis, assessment methodology, scientific validation, analysis integration contribution
- Pratik: NDVI, raster analysis, band handling, temporal analysis, analysis testing

Module ownership does NOT mean module isolation. Every milestone must work end-to-end.

## 23. Development Philosophy

The unit of progress is NOT: "Module 3 feature finished"

The unit of progress is:
```
Real Input
    ↓
Module 2
    ↓
Module 3
    ↓
API
    ↓
Module 1
    ↓
Visible, verified result
```

If a feature does not survive this flow, it is not complete.

## 24. Near-Term Roadmap After Stabilization

**Milestone — Real Satellite Validation**
```
Real SRISHTI / Satellite Dataset
    ↓
Module 2 ingestion
    ↓
Metadata + band validation
    ↓
Module 3 NDVI
    ↓
Module 1 visualization
```

**Milestone — Temporal Change**
```
Date A → NDVI A
Date B → NDVI B
    ↓
NDVI Change
    ↓
Change Map
```

**Later:**
- water indicators
- rainfall context
- assessment cells
- indicator normalization
- priority classification
- confidence
- geo-coded evidence
- explainable decision support

Do not start all of these simultaneously.

## 25. Detailed Documentation

Before modifying a subsystem, also inspect:
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/API_CONTRACT.md`
- `docs/DATA_CONTRACT.md`
- `docs/DATA_SOURCES.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/PROJECT_STATUS.md`
- relevant module README.md

This file provides the high-level operating context. Detailed implementation truth belongs in those documents and in the source code/tests.

## 26. Definition of Done

A change is not complete because code was written. A meaningful project feature requires, where applicable:

- Implementation
- Correct scientific behavior
- Tests
- API integration
- Frontend integration
- Documentation
- Real or clearly labeled synthetic validation

If synthetic data is used, it must be explicitly identified as synthetic.

## 27. Final Project Vision

The intended final workflow is:
```
Select Watershed
    ↓
Inspect Available Data
    ↓
Load Terrain + Satellite + Other Relevant Data
    ↓
Run Spatial Analysis
    ↓
Compare Environmental Conditions Over Time
    ↓
Identify Important Spatial Patterns
    ↓
Generate Assessment / Priority Zones
    ↓
Inspect Evidence and Indicators
    ↓
Support Watershed Monitoring and Planning
```

The project is not intended to replace watershed experts. It is intended to reduce the technical effort required to integrate, analyze, visualize, and interpret watershed-related geospatial information.

## 28. Final Rule

When uncertain: **Preserve the working system, inspect the evidence, verify the science, and make the smallest change that moves the real watershed workflow forward.**

## 29. Active Runtime Entry Points

| Component | Entry Point | Command |
|-----------|-------------|---------|
| Module 2 Backend | `backend.app.main:app` | `uvicorn backend.app.main:app --reload --port 8000` |
| Module 1 Express | `server.js` | `node server.js` |
| Module 0 Dashboard | `module0.main:app` | `python -m module0.main` |
| Module 1 Streamlit | `app.py` | `streamlit run app.py` |

**Canonical frontend:** Express + Leaflet (`server.js` → `public/`)

**Legacy/prototype:** Streamlit (`app.py`)
