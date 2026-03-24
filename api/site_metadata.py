"""Site metadata loader — single source of truth.

Reads ``config/usgs_sites.json`` and builds the flat ``{site_id: meta}``
dictionary consumed by all API route modules.  Falls back to a CSV-header
scan when a site appears on disk but is missing from the JSON catalogue.
"""

import json
from pathlib import Path
from typing import Dict

import pandas as pd

CONFIG_DIR = Path(__file__).parent.parent / "config"
DATA_DIR = Path(__file__).parent.parent / "data"

# Map raw CSV aquifer strings (snake_case from USGS) to proper display names
# and their confinement/zone metadata so CSV-only fallback sites get correct info.
_CSV_AQUIFER_NORMALISATION: Dict[str, dict] = {
    "biscayne_aquifer": {
        "aquifer": "Biscayne Aquifer",
        "aquifer_type": "unconfined",
        "confined": False,
        "aquifer_zone": "Biscayne",
        "aquifer_zone_depth_range_ft": [0, 100],
        "well_depth_ft": 50,
    },
    "floridan_aquifer": {
        "aquifer": "Floridan Aquifer System",
        "aquifer_type": "confined",
        "confined": True,
        "aquifer_zone": "Upper Floridan",
        "aquifer_zone_depth_range_ft": [200, 700],
        "well_depth_ft": 400,
    },
    "surficial_aquifer": {
        "aquifer": "Surficial Aquifer",
        "aquifer_type": "unconfined",
        "confined": False,
        "aquifer_zone": "Surficial Sand",
        "aquifer_zone_depth_range_ft": [10, 50],
        "well_depth_ft": 25,
    },
    "florida": {
        "aquifer": "Florida Aquifer",
        "aquifer_type": "unconfined",
        "confined": False,
        "aquifer_zone": "",
        "aquifer_zone_depth_range_ft": [0, 100],
        "well_depth_ft": 50,
    },
}


def _load_json_catalogue() -> Dict[str, dict]:
    """Parse ``config/usgs_sites.json`` into a flat lookup."""
    catalogue: Dict[str, dict] = {}
    json_path = CONFIG_DIR / "usgs_sites.json"
    if not json_path.exists():
        return catalogue

    with open(json_path) as fh:
        raw = json.load(fh)

    for _aquifer_key, aq in raw.get("aquifers", {}).items():
        aquifer_name = aq.get("name", "Florida Aquifer")
        aquifer_type = aq.get("aquifer_type", "unconfined")
        aq_confined = aq.get("confined", False)
        aq_depth_range = aq.get("depth_range_ft", [0, 100])
        aq_description = aq.get("description", "")
        zones_by_name: Dict[str, dict] = {z["zone_name"]: z for z in aq.get("zones", [])}

        for site in aq.get("sites", []):
            sid = site["site_id"]
            site_zone = site.get("aquifer_zone", "")
            zone_detail = zones_by_name.get(site_zone, {})
            catalogue[sid] = {
                "id": sid,
                "name": site.get("name", f"Site {sid}"),
                "aquifer": aquifer_name,
                "aquifer_type": aquifer_type,
                "confined": site.get("confined", aq_confined),
                "aquifer_zone": site_zone,
                "aquifer_zone_depth_range_ft": zone_detail.get("depth_range_ft", aq_depth_range),
                "aquifer_description": zone_detail.get("description", aq_description),
                "county": site.get("county", "Florida"),
                "lat": site.get("lat", 26.0),
                "lng": site.get("lng", -81.0),
                "well_depth_ft": site.get("well_depth_ft", 50),
            }
    return catalogue


def load_site_metadata() -> Dict[str, dict]:
    """Build the complete site metadata dict.

    Merges the JSON catalogue with any extra CSV files found on disk.
    Each value is a dict with keys: id, name, aquifer, county, lat, lng,
    depth, description.
    """
    catalogue = _load_json_catalogue()
    sites: Dict[str, dict] = {}

    for csv_file in sorted(DATA_DIR.glob("usgs_*.csv")):
        sid = csv_file.stem.replace("usgs_", "")

        if sid in catalogue:
            meta = catalogue[sid].copy()
        else:
            # Fallback: try to read CSV header row
            try:
                df = pd.read_csv(csv_file, nrows=1)
                raw_aquifer = str(df.get("aquifer", ["florida"])[0]).lower().strip()
                norm = _CSV_AQUIFER_NORMALISATION.get(
                    raw_aquifer, _CSV_AQUIFER_NORMALISATION["florida"]
                )
                meta = {
                    "id": sid,
                    "name": df.get("site_name", [f"Site {sid}"])[0],
                    "county": "Florida",
                    "lat": 25.5 + hash(sid) % 100 / 100,
                    "lng": -80.5 + hash(sid) % 100 / 200,
                    **norm,
                }
            except Exception:
                meta = {
                    "id": sid,
                    "name": f"Site {sid}",
                    "county": "Florida",
                    "lat": 25.5,
                    "lng": -80.5,
                    **_CSV_AQUIFER_NORMALISATION["florida"],
                }

        meta.setdefault("well_depth_ft", 50)
        meta["depth"] = meta["well_depth_ft"]  # backward-compat alias
        meta.setdefault("aquifer_type", "unconfined")
        meta.setdefault("confined", False)
        meta.setdefault("aquifer_zone", "")
        meta.setdefault("aquifer_zone_depth_range_ft", [0, 100])
        meta.setdefault("aquifer_description", f"USGS monitoring well {sid}")
        meta.setdefault("description", f"USGS monitoring well {sid}")
        sites[sid] = meta

    return sites


# Module-level cache — imported by route modules
SITE_METADATA = load_site_metadata()
