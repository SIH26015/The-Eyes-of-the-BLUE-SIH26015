from typing import Dict, Any, List, Optional


ANALYSIS_REQUIREMENTS = {
    "terrain": {
        "required": ["DEM"],
        "preferred": ["DEM"],
        "description": "Digital Elevation Model for terrain analysis",
    },
    "slope": {
        "required": ["DEM"],
        "preferred": ["DEM"],
        "description": "Digital Elevation Model for slope derivation",
    },
    "drainage": {
        "required": ["DEM"],
        "preferred": ["DEM"],
        "description": "Digital Elevation Model for drainage analysis",
    },
    "vegetation": {
        "required": [],
        "preferred": ["NDVI"],
        "description": "Vegetation indices or satellite imagery",
    },
    "water": {
        "required": [],
        "preferred": ["NDVI", "SATELLITE"],
        "description": "Water body detection",
    },
    "landuse": {
        "required": ["LULC"],
        "preferred": ["LULC"],
        "description": "Land use land cover classification",
    },
    "change_detection": {
        "required": [],
        "preferred": [],
        "description": "Temporal change detection requiring multiple compatible datasets",
        "min_datasets": 2,
    },
}


def get_analysis_requirements(analysis_type: str) -> Optional[Dict[str, Any]]:
    return ANALYSIS_REQUIREMENTS.get(analysis_type)


def get_supported_analyses() -> List[str]:
    return list(ANALYSIS_REQUIREMENTS.keys())
