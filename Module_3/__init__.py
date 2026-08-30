"""Module 3 — Geospatial Analysis Engine.

Provides terrain analysis, vegetation/NDVI analysis, and analysis result management.
Depends only on numpy, rasterio, and pydantic. No FastAPI/HTTP dependency.
"""

from .analysis_engine.interfaces.dataset_provider import DatasetProvider

__all__ = ["DatasetProvider"]
