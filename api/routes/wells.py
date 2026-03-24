"""Wells routes — location, depth, and aquifer information for monitoring wells.

Endpoint:
 • GET /api/wells  — Return monitoring wells with lat, lng, well depth, and
                     aquifer metadata (name, confined/unconfined, zone, description).
                     Supports filtering by aquifer, county, confinement, and
                     proximity (lat/lng bounding radius).
"""

from typing import Optional

from fastapi import APIRouter, Query

from api.site_metadata import SITE_METADATA

router = APIRouter(prefix="/api", tags=["wells"])

# Normalise user input to the aquifer display name substring stored in SITE_METADATA.
# Keys are lowercase query strings; values are substrings to match against site["aquifer"].
_AQUIFER_KEY_MAP: dict[str, str] = {
    # Biscayne
    "biscayne": "biscayne",
    "biscayne aquifer": "biscayne",
    # Surficial / Near-Surface
    "surficial": "surficial",
    "surficial aquifer": "surficial",
    "near-surface": "surficial",
    "water table": "surficial",
    "water-table": "surficial",
    # Tamiami (intermediate)
    "tamiami": "tamiami",
    "tamiami aquifer": "tamiami",
    "lower tamiami": "tamiami",
    "tamiami aquifer system": "tamiami",
    "intermediate": "tamiami",
    "intermediate aquifer": "tamiami",
    # Sand and Shell (Lee County intermediate)
    "sand and shell": "sand and shell",
    "sand shell": "sand and shell",
    # Hawthorn
    "hawthorn": "hawthorn",
    "hawthorn group": "hawthorn",
    "hawthorn formation": "hawthorn",
    # Floridan
    "floridan": "floridan",
    "floridan aquifer": "floridan",
    "floridan aquifer system": "floridan",
    "upper floridan": "upper floridan",
    "lower floridan": "lower floridan",
    "tampa limestone": "tampa limestone",
    "tampa": "tampa limestone",
}

# Substring that must appear in the stored aquifer display name for each normalised value
_AQUIFER_NAME_FILTER: dict[str, str] = {
    "biscayne": "biscayne",
    "surficial": "surficial",
    "tamiami": "tamiami",
    "sand and shell": "sand and shell",
    "hawthorn": "hawthorn",
    "floridan": "floridan",
    "upper floridan": "upper floridan",
    "lower floridan": "lower floridan",
    "tampa limestone": "tampa limestone",
}


def _usgs_site_url(site_id: str) -> str:
    return f"https://waterdata.usgs.gov/monitoring-location/{site_id}/"


def _distance_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return ((lat1 - lat2) ** 2 + (lng1 - lng2) ** 2) ** 0.5


@router.get("/wells")
def get_wells(
    aquifer: Optional[str] = Query(
        None, description="Filter by aquifer: biscayne / floridan / surficial"
    ),
    county: Optional[str] = Query(None, description="Filter by county name (case-insensitive)"),
    lat: Optional[float] = Query(None, description="Reference latitude for proximity sort/filter"),
    lng: Optional[float] = Query(None, description="Reference longitude for proximity sort/filter"),
    radius_deg: float = Query(
        1.0, description="Bounding radius in lat/lng degrees (used only when lat+lng given)"
    ),
    max_results: int = Query(50, ge=1, le=200, description="Maximum wells returned"),
    confined_only: bool = Query(False, description="Return only confined/artesian wells"),
    unconfined_only: bool = Query(False, description="Return only unconfined (water-table) wells"),
):
    """Return monitoring wells with location, depth, and aquifer metadata.

    Filters are cumulative. Proximity sort is applied when ``lat`` and ``lng``
    are both provided. Without coordinates, wells are sorted by county then name.

    Examples::

        GET /api/wells                                   # all 36 wells
        GET /api/wells?aquifer=floridan                  # 17 Floridan wells
        GET /api/wells?confined_only=true                # confined wells only
        GET /api/wells?lat=26.44&lng=-81.81&radius_deg=0.5  # near Estero
        GET /api/wells?county=Lee&aquifer=floridan       # Lee + Floridan
    """
    aquifer_key = _AQUIFER_KEY_MAP.get(aquifer.lower().strip()) if aquifer else None
    county_lower = county.strip().lower() if county else None
    proximity_center = None

    wells = []
    for site_id, meta in SITE_METADATA.items():
        is_confined = meta.get("confined", False)

        # --- confinement filter ---
        if confined_only and not is_confined:
            continue
        if unconfined_only and is_confined:
            continue

        # --- aquifer filter ---
        if aquifer_key:
            needle = _AQUIFER_NAME_FILTER.get(aquifer_key, aquifer_key)
            if needle not in meta.get("aquifer", "").lower():
                continue

        # --- county filter ---
        if county_lower and meta.get("county", "").lower() != county_lower:
            continue

        # --- proximity filter ---
        site_lat = meta.get("lat")
        site_lng = meta.get("lng")
        dist: Optional[float] = None
        if lat is not None and lng is not None and site_lat and site_lng:
            proximity_center = {"lat": lat, "lng": lng}
            dist = _distance_deg(lat, lng, float(site_lat), float(site_lng))
            if dist > radius_deg:
                continue

        wells.append(
            {
                "site_id": site_id,
                "name": meta.get("name", site_id),
                "county": meta.get("county", "Florida"),
                "lat": float(site_lat) if site_lat is not None else None,
                "lng": float(site_lng) if site_lng is not None else None,
                "well_depth_ft": meta.get("well_depth_ft", meta.get("depth", 50)),
                "aquifer": meta.get("aquifer", "Unknown"),
                "aquifer_type": meta.get("aquifer_type", "unconfined"),
                "confined": is_confined,
                "aquifer_zone": meta.get("aquifer_zone", ""),
                "aquifer_zone_depth_range_ft": meta.get("aquifer_zone_depth_range_ft", [0, 100]),
                "aquifer_description": meta.get("aquifer_description", ""),
                "usgs_url": _usgs_site_url(site_id),
                "distance_deg": round(dist, 6) if dist is not None else None,
            }
        )

    # Sort: distance when proximity search active, else county → name
    if proximity_center:
        wells.sort(key=lambda w: w["distance_deg"] if w["distance_deg"] is not None else 9999.0)
    else:
        wells.sort(key=lambda w: (w["county"], w["name"]))

    wells = wells[:max_results]

    return {
        "wells": wells,
        "total": len(wells),
        "filters_applied": {
            "aquifer": aquifer_key,
            "county": county_lower,
            "confined_only": confined_only,
            "unconfined_only": unconfined_only,
            "proximity_center": proximity_center,
            "radius_deg": radius_deg if proximity_center else None,
        },
    }
