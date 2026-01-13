"""
================================================================================
CONFIG.PY - All Settings in One Place
================================================================================

Edit this file to change regions, time periods, and data sources.
"""

from pathlib import Path

BASE_DIR = Path(__file__).parent

# ==============================================================================
# STUDY REGIONS
# ==============================================================================

REGIONS = {
    "fort_myers": {
        "name": "Fort Myers, FL",
        "lat": 26.6406,
        "lon": -81.8723,
        "area": [27.0, -82.2, 26.3, -81.5],  # [North, West, South, East]
        "state": "FL",
        "county": "Lee",
    },
}

ACTIVE_REGION = "fort_myers"

# ==============================================================================
# TIME PERIOD
# ==============================================================================

TIME_CONFIG = {
    "start_date": "1994-01-01",
    "end_date": "2023-12-31",
    "years": [str(y) for y in range(1994, 2024)],  # 30 years
}

# ==============================================================================
# ERA5 CLIMATE DATA (Copernicus CDS)
# ==============================================================================

CDS_API_KEY = "20c4a99b-280e-4952-90ee-971bb40a0c52"
CDS_URL = "https://cds.climate.copernicus.eu/api"

ERA5_VARIABLES = [
    "2m_temperature",
    "total_precipitation",
    "volumetric_soil_water_layer_1",
    "sub_surface_runoff",
]

# ==============================================================================
# USGS GROUNDWATER
# ==============================================================================

USGS_PARAMETERS = {
    "72019": "depth_to_water",
    "62610": "water_level_ngvd29",
    "62611": "water_level_navd88",
}

USGS_SITES = []

# ==============================================================================
# PDF DOCUMENTS FOR RAG
# ==============================================================================

PDF_FILES = [
    BASE_DIR / "a-conceptual-overview-of-surface-and-near-surface-brines-and-evaporite-minerals.pdf",
    BASE_DIR / "a-glossary-of-hydrogeology.pdf",
    BASE_DIR / "age-dating-young-groundwater.pdf",
]

RAG_CONFIG = {
    "chunk_size": 512,
    "chunk_overlap": 50,
    "embedding_model": "BAAI/bge-small-en-v1.5",
    "persist_directory": str(BASE_DIR / "chroma_db"),
}

# ==============================================================================
# MODEL TRAINING
# ==============================================================================

MODEL_CONFIG = {
    "test_size": 0.2,
    "random_state": 42,
    "lag_days": [1, 3, 7, 14, 30],
    "rolling_windows": [7, 14, 30],
}

# ==============================================================================
# OUTPUT PATHS
# ==============================================================================

DATA_DIR = BASE_DIR / "data"
PLOTS_DIR = BASE_DIR / "plots"
MODELS_DIR = BASE_DIR / "models"

# ==============================================================================
# HELPERS
# ==============================================================================

def get_region(name=None):
    return REGIONS.get(name or ACTIVE_REGION)

def print_config():
    region = get_region()
    print(f"\n{'='*50}")
    print("CONFIGURATION")
    print(f"{'='*50}")
    print(f"Region: {region['name']}")
    print(f"Period: {TIME_CONFIG['start_date']} to {TIME_CONFIG['end_date']}")
    print(f"{'='*50}\n")
