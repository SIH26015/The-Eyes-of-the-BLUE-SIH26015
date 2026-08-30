# API Contract

## Base URL

```
http://localhost:8000
```

## Dataset Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/datasets/upload` | Upload dataset archive |
| GET | `/api/datasets/` | List datasets |
| GET | `/api/datasets/{id}` | Get dataset detail |
| PUT | `/api/datasets/{id}/classify` | Reclassify dataset |
| PUT | `/api/datasets/{id}/rename` | Rename dataset |
| DELETE | `/api/datasets/{id}` | Soft delete dataset |
| POST | `/api/datasets/{id}/restore` | Restore soft-deleted dataset |
| POST | `/api/datasets/{id}/reprocess` | Reprocess dataset |
| GET | `/api/datasets/{id}/files` | List dataset files |
| GET | `/api/datasets/{id}/history` | Metadata change history |
| GET | `/api/datasets/{id}/quality` | Quality report |
| PUT | `/api/datasets/{id}/move` | Move dataset to new location |

## Search Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/datasets/search/area` | Search by bounding box |
| GET | `/api/datasets/search/overlap` | Find overlapping datasets |
| GET | `/api/datasets/search/temporal` | Search by date range |
| GET | `/api/datasets/readiness` | Evaluate analysis readiness |
| GET | `/api/datasets/recommend` | Get dataset recommendations |
| GET | `/api/datasets/compatibility` | Check dataset compatibility |
| GET | `/api/datasets/temporal-pairs` | Find temporal dataset pairs |
| GET | `/api/datasets/prepare-analysis` | Prepare analysis package |
| GET | `/api/datasets/capabilities` | Get analysis capabilities |

## Analysis Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/analysis/terrain` | Run terrain analysis |
| POST | `/api/analysis/ndvi` | Run NDVI analysis |
| GET | `/api/analysis/results` | List analysis results |
| GET | `/api/analysis/results/{id}` | Get analysis result |
| GET | `/api/analysis/results/{id}/files/{filename}` | Download output file |
| GET | `/api/analysis/results/{id}/preview/{layer}` | Get preview raster |

## Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health check |

## Dataset Contract

Module 2 provides datasets to Module 3 via `get_analysis_dataset()`. The contract includes:
- `dataset_id`, `dataset_name`, `dataset_type`
- `file_path`, `directory_exists`, `manifest_exists`
- `bounds` (west, south, east, north)
- `crs`, `resolution`, `format`
- `files` (list with name, path, type, role, exists, spatial)
- `ready_for_analysis`, `errors`, `warnings`
