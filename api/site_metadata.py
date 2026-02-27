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
        for site in aq.get("sites", []):
            sid = site["site_id"]
            catalogue[sid] = {
                "id": sid,
                "name": site.get("name", f"Site {sid}"),
                "aquifer": aquifer_name,
                "county": site.get("county", "Florida"),
                "lat": site.get("lat", 26.0),
                "lng": site.get("lng", -81.0),
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
                meta = {
                    "id": sid,
                    "name": df.get("site_name", [f"Site {sid}"])[0],
                    "aquifer": df.get("aquifer", ["Florida Aquifer"])[0],
                    "county": "Florida",
                    "lat": 25.5 + hash(sid) % 100 / 100,
                    "lng": -80.5 + hash(sid) % 100 / 200,
                }
            except Exception:
                meta = {
                    "id": sid,
                    "name": f"Site {sid}",
                    "aquifer": "Florida Aquifer",
                    "county": "Florida",
                    "lat": 25.5,
                    "lng": -80.5,
                }

        meta.setdefault("depth", 50)
        meta.setdefault("description", f"USGS monitoring well {sid}")
        sites[sid] = meta

    return sites


# Module-level cache — imported by route modules
SITE_METADATA = load_site_metadata()
