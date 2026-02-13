"""FastAPI backend for GroundwaterGPT Dashboard.

Serves real USGS groundwater data to the React frontend.
"""

import logging
import sys
import traceback
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="GroundwaterGPT API", version="1.0.0")

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data directory
DATA_DIR = Path(__file__).parent.parent / "data"


def get_site_metadata():
    """Dynamically build site metadata from available CSV files."""
    # Base metadata for known sites
    known_sites = {
        "251241080385301": {
            "name": "Miami-Dade G-3764",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.2114,
            "lng": -80.6481,
        },
        "251457080395802": {
            "name": "Miami-Dade G-3777",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.2492,
            "lng": -80.6661,
        },
        "251922080340701": {
            "name": "Miami-Dade G-1251",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.3228,
            "lng": -80.5686,
        },
        "252007080335701": {
            "name": "Miami-Dade G-3336",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.3353,
            "lng": -80.5658,
        },
        "252036080293501": {
            "name": "Miami-Dade G-5004",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.3433,
            "lng": -80.4931,
        },
        "252332080300501": {
            "name": "Miami-Dade G-3355",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.3922,
            "lng": -80.5014,
        },
        "252502080253901": {
            "name": "Miami-Dade G-3356",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.4172,
            "lng": -80.4275,
        },
        "252612080300701": {
            "name": "Miami-Dade G-864",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.4367,
            "lng": -80.5019,
        },
        "252918080234201": {
            "name": "Miami-Dade G-1183",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.4883,
            "lng": -80.3950,
        },
        "253029080295601": {
            "name": "Miami-Dade S-196A",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.5081,
            "lng": -80.4989,
        },
        "253413080225301": {
            "name": "Miami-Dade G-3969",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.5703,
            "lng": -80.3814,
        },
        "253417080224301": {
            "name": "Miami-Dade G-3968",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.5714,
            "lng": -80.3786,
        },
        "253539080284101": {
            "name": "Miami-Dade G-757AR",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.5942,
            "lng": -80.4781,
        },
        "253539080320501": {
            "name": "Miami-Dade G-3628",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.5942,
            "lng": -80.5347,
        },
        "253640080264701": {
            "name": "Miami-Dade G-1362A",
            "aquifer": "Biscayne Aquifer",
            "county": "Miami-Dade",
            "lat": 25.6111,
            "lng": -80.4464,
        },
        "262724081260701": {
            "name": "Lee County - Fort Myers",
            "aquifer": "Floridan Aquifer",
            "county": "Lee",
            "lat": 26.4567,
            "lng": -81.4353,
        },
        # Lee County (Fort Myers area)
        "261957081432201": {
            "name": "L-2194",
            "aquifer": "Floridan Aquifer",
            "county": "Lee",
            "lat": 26.3325,
            "lng": -81.7228,
        },
        "263532081592201": {
            "name": "L-581",
            "aquifer": "Floridan Aquifer",
            "county": "Lee",
            "lat": 26.5922,
            "lng": -81.9894,
        },
        "263041081433103": {
            "name": "L-1999",
            "aquifer": "Floridan Aquifer",
            "county": "Lee",
            "lat": 26.5114,
            "lng": -81.7253,
        },
        "261957081432202": {
            "name": "L-2195",
            "aquifer": "Floridan Aquifer",
            "county": "Lee",
            "lat": 26.3325,
            "lng": -81.7228,
        },
        "263335081394301": {
            "name": "L-729",
            "aquifer": "Floridan Aquifer",
            "county": "Lee",
            "lat": 26.5597,
            "lng": -81.6619,
        },
        "263440082022001": {
            "name": "L-2644",
            "aquifer": "Floridan Aquifer",
            "county": "Lee",
            "lat": 26.5778,
            "lng": -82.0389,
        },
        "262711081413701": {
            "name": "L-2550",
            "aquifer": "Floridan Aquifer",
            "county": "Lee",
            "lat": 26.4531,
            "lng": -81.6936,
        },
        # Collier County (Naples area)
        "261342081352901": {
            "name": "C-948R",
            "aquifer": "Floridan Aquifer",
            "county": "Collier",
            "lat": 26.2283,
            "lng": -81.5914,
        },
        "261342081352902": {
            "name": "C-951R",
            "aquifer": "Floridan Aquifer",
            "county": "Collier",
            "lat": 26.2283,
            "lng": -81.5914,
        },
        "261342081352903": {
            "name": "C-953R",
            "aquifer": "Floridan Aquifer",
            "county": "Collier",
            "lat": 26.2283,
            "lng": -81.5914,
        },
        "260111081243901": {
            "name": "C-496",
            "aquifer": "Floridan Aquifer",
            "county": "Collier",
            "lat": 26.0197,
            "lng": -81.4108,
        },
        "260405081414101": {
            "name": "C-1224",
            "aquifer": "Floridan Aquifer",
            "county": "Collier",
            "lat": 26.0681,
            "lng": -81.6947,
        },
        # Hendry County
        "262214081113001": {
            "name": "HE-1042",
            "aquifer": "Floridan Aquifer",
            "county": "Hendry",
            "lat": 26.3706,
            "lng": -81.1917,
        },
        "262735081044601": {
            "name": "HE-860",
            "aquifer": "Floridan Aquifer",
            "county": "Hendry",
            "lat": 26.4597,
            "lng": -81.0794,
        },
        "262735081044602": {
            "name": "HE-859",
            "aquifer": "Floridan Aquifer",
            "county": "Hendry",
            "lat": 26.4597,
            "lng": -81.0794,
        },
        "261735080534001": {
            "name": "HE-861",
            "aquifer": "Floridan Aquifer",
            "county": "Hendry",
            "lat": 26.2931,
            "lng": -80.8944,
        },
        # Sarasota County
        "272127082323801": {
            "name": "Sarasota 23rd & Coconut",
            "aquifer": "Floridan Aquifer",
            "county": "Sarasota",
            "lat": 27.3575,
            "lng": -82.5439,
        },
        "272129082330202": {
            "name": "Sarasota Hickory Ave",
            "aquifer": "Floridan Aquifer",
            "county": "Sarasota",
            "lat": 27.3581,
            "lng": -82.5506,
        },
        "272020082194801": {
            "name": "Verna Test Well 0-4",
            "aquifer": "Floridan Aquifer",
            "county": "Sarasota",
            "lat": 27.3389,
            "lng": -82.3300,
        },
        "271619082240201": {
            "name": "Fla Cities Test 1",
            "aquifer": "Floridan Aquifer",
            "county": "Sarasota",
            "lat": 27.2719,
            "lng": -82.4006,
        },
    }

    # Scan for all USGS CSV files
    sites = {}
    for csv_file in DATA_DIR.glob("usgs_*.csv"):
        site_id = csv_file.stem.replace("usgs_", "")

        if site_id in known_sites:
            meta = known_sites[site_id].copy()
        else:
            # Try to extract info from CSV
            try:
                df = pd.read_csv(csv_file, nrows=1)
                meta = {
                    "name": df.get("site_name", [f"Site {site_id}"])[0],
                    "aquifer": df.get("aquifer", ["Florida Aquifer"])[0],
                    "county": "Florida",
                    "lat": 25.5 + hash(site_id) % 100 / 100,
                    "lng": -80.5 + hash(site_id) % 100 / 200,
                }
            except Exception:
                meta = {
                    "name": f"Site {site_id}",
                    "aquifer": "Florida Aquifer",
                    "county": "Florida",
                    "lat": 25.5,
                    "lng": -80.5,
                }

        sites[site_id] = {
            "id": site_id,
            "depth": 50,
            "description": f"USGS monitoring well {site_id}",
            **meta,
        }

    return sites


# Cache site metadata
SITE_METADATA = get_site_metadata()


def load_site_data(site_id: str) -> pd.DataFrame:
    """Load CSV data for a specific site."""
    csv_path = DATA_DIR / f"usgs_{site_id}.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"Data not found for site {site_id}")

    df = pd.read_csv(csv_path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime")
    return df


def calculate_stats(df: pd.DataFrame) -> dict:
    """Calculate statistics for site data."""
    values = df["value"].dropna()

    if len(values) == 0:
        return {"min": 0, "max": 0, "mean": 0, "annualChange": 0, "count": 0}

    # Calculate annual change using linear regression
    df_copy = df.copy()
    df_copy["days"] = (df_copy["datetime"] - df_copy["datetime"].min()).dt.days

    if len(df_copy) > 1:
        # Simple linear regression
        x = df_copy["days"].values
        y = df_copy["value"].values
        n = len(x)
        slope = (n * (x * y).sum() - x.sum() * y.sum()) / (n * (x**2).sum() - x.sum() ** 2)
        annual_change = slope * 365  # Convert daily rate to annual
    else:
        annual_change = 0

    return {
        "min": round(float(values.min()), 2),
        "max": round(float(values.max()), 2),
        "mean": round(float(values.mean()), 2),
        "annualChange": round(float(annual_change), 3),
        "count": int(len(values)),
        "dateRange": {
            "start": df["datetime"].min().isoformat(),
            "end": df["datetime"].max().isoformat(),
        },
    }


@app.get("/")
def root():
    """Return API info."""
    return {"message": "GroundwaterGPT API", "version": "1.0.0"}


@app.get("/api/sites")
def get_sites():
    """Get list of all monitoring sites with metadata."""
    sites = []
    for site_id, metadata in SITE_METADATA.items():
        csv_path = DATA_DIR / f"usgs_{site_id}.csv"
        if csv_path.exists():
            df = pd.read_csv(csv_path)
            metadata_copy = metadata.copy()
            metadata_copy["recordCount"] = len(df)
            sites.append(metadata_copy)
    return {"sites": sites}


@app.get("/api/sites/{site_id}")
def get_site(site_id: str):
    """Get metadata and statistics for a specific site."""
    if site_id not in SITE_METADATA:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")

    df = load_site_data(site_id)
    stats = calculate_stats(df)

    return {"site": SITE_METADATA[site_id], "stats": stats}


@app.get("/api/sites/{site_id}/data")
def get_site_data(site_id: str, start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Get time series data for a specific site."""
    df = load_site_data(site_id)

    # Filter by date range if provided
    if start_date:
        df = df[df["datetime"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["datetime"] <= pd.to_datetime(end_date)]

    # Format data for frontend
    data = []
    for _, row in df.iterrows():
        data.append(
            {
                "date": row["datetime"].isoformat(),
                "level": round(float(row["value"]), 2),
                "year": int(row["year"]),
                "month": row["datetime"].month,
            }
        )

    stats = calculate_stats(df)

    return {"site": SITE_METADATA.get(site_id, {}), "data": data, "stats": stats}


@app.get("/api/sites/{site_id}/heatmap")
def get_heatmap_data(site_id: str):
    """Get heatmap data with monthly averages by year."""
    df = load_site_data(site_id)

    # Calculate monthly averages by year
    df["month"] = df["datetime"].dt.month
    df["year"] = df["datetime"].dt.year

    monthly = df.groupby(["year", "month"])["value"].mean().reset_index()

    heatmap_data = []
    for _, row in monthly.iterrows():
        heatmap_data.append(
            {
                "year": int(row["year"]),
                "month": int(row["month"]),
                "value": round(float(row["value"]), 2),
            }
        )

    # Get min/max for color scale
    values = monthly["value"]

    return {
        "data": heatmap_data,
        "min": round(float(values.min()), 2),
        "max": round(float(values.max()), 2),
    }


@app.get("/api/compare")
def compare_sites(site_ids: str):
    """Compare multiple sites by their statistics."""
    ids = site_ids.split(",")
    comparison = []

    for site_id in ids:
        if site_id.strip() in SITE_METADATA:
            try:
                df = load_site_data(site_id.strip())
                stats = calculate_stats(df)
                comparison.append({"site": SITE_METADATA[site_id.strip()], "stats": stats})
            except HTTPException:
                pass

    return {"comparison": comparison}

    # ============================================================================
    # AI Chat Endpoint (Under Construction)
    # ============================================================================

    return {"comparison": comparison}


# ============================================================================
# Agent Layer — LLM-backed chat and deep research
# ============================================================================

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rule-based fallback KB (used when LLM agent cannot be initialised)
# ---------------------------------------------------------------------------

GROUNDWATER_KB = {
    "irrigation": {
        "keywords": ["irrigat", "water", "crop", "plant", "farm"],
        "info": (
            "Groundwater levels are critical for irrigation planning. "
            "In Florida, the dry season (Nov-May) typically shows lower water tables. "
            "Monitor levels 2-3 weeks before planting to ensure adequate supply."
        ),
    },
    "soil_moisture": {
        "keywords": ["soil", "moisture", "drain", "saturat"],
        "info": (
            "Soil moisture is directly related to groundwater depth. "
            "Shallow water tables (<3ft) may cause waterlogging. "
            "Deep water tables (>10ft) may require irrigation supplementation."
        ),
    },
    "crops": {
        "keywords": ["crop", "plant", "grow", "vegetable", "citrus", "tomato"],
        "info": (
            "Different crops have varying water table tolerances: "
            "Citrus: 3-6ft optimal depth. Tomatoes: 2-4ft optimal. "
            "Sugarcane: tolerates 1-3ft. Most vegetables prefer 2-5ft."
        ),
    },
    "saltwater": {
        "keywords": ["salt", "intrusion", "coastal", "chloride", "brackish"],
        "info": (
            "Saltwater intrusion is a concern in coastal Florida aquifers. "
            "Biscayne Aquifer (Miami-Dade) is particularly vulnerable. "
            "Monitor chloride levels and watch for declining freshwater heads."
        ),
    },
    "seasonal": {
        "keywords": ["season", "wet", "dry", "rain", "hurricane"],
        "info": (
            "Florida has distinct wet (Jun-Oct) and dry (Nov-May) seasons. "
            "Groundwater levels typically peak in Sep-Oct after summer rains. "
            "Lowest levels occur in Apr-May before wet season begins."
        ),
    },
    "aquifer": {
        "keywords": ["aquifer", "floridan", "biscayne", "surficial"],
        "info": (
            "Florida has three main aquifer systems: "
            "1) Surficial (unconfined, shallow) "
            "2) Biscayne (SE Florida, highly productive) "
            "3) Floridan (deep, artesian in some areas)."
        ),
    },
    "well": {
        "keywords": ["well", "pump", "depth", "drill", "permit"],
        "info": (
            "Well permits required from local Water Management District. "
            "Residential wells typically 20-100ft deep. "
            "Agricultural wells may be 100-500ft for Floridan Aquifer access."
        ),
    },
}


def _get_site_context(county: Optional[str] = None) -> str:
    """Get context string about available monitoring sites."""
    sites_by_county: dict[str, list[str]] = {}
    for site_id, meta in SITE_METADATA.items():
        c = meta.get("county", "Unknown")
        sites_by_county.setdefault(c, []).append(meta.get("name", site_id))

    if county and county in sites_by_county:
        sites_list = ", ".join(sites_by_county[county][:5])
        return f"Available monitoring sites in {county}: {sites_list}"

    n_sites = len(SITE_METADATA)
    n_counties = len(sites_by_county)
    return f"Monitoring {n_sites} USGS sites across {n_counties} Florida counties."


def _fallback_response(query: str) -> dict:
    """Rule-based fallback when LLM agent is unavailable."""
    query_lower = query.lower()
    matches = []
    for topic, data in GROUNDWATER_KB.items():
        for kw in data["keywords"]:
            if kw in query_lower:
                matches.append((topic, data["info"]))
                break

    county_mentioned = None
    for county in ["Miami-Dade", "Lee", "Collier", "Sarasota", "Hendry"]:
        if county.lower() in query_lower:
            county_mentioned = county
            break

    if matches:
        response_text = " ".join(m[1] for m in matches[:2])
        sources = [f"GroundwaterGPT KB: {m[0]}" for m in matches]
    else:
        response_text = (
            "I can help with groundwater questions about irrigation, crops, "
            "soil moisture, aquifers, wells, saltwater intrusion, and seasonal patterns. "
            "Try asking about water levels for farming or which crops suit your area."
        )
        sources = ["GroundwaterGPT Knowledge Base"]

    return {
        "response": response_text,
        "context": _get_site_context(county_mentioned),
        "sources": sources,
        "mode": "fallback",
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# Try to initialise real agents (graceful fallback on import/init failure)
# ---------------------------------------------------------------------------

_chat_agent = None
_research_agent = None

try:
    # Ensure src/ is on the path so relative imports inside the agent package work
    _src_dir = str(Path(__file__).parent.parent / "src")
    if _src_dir not in sys.path:
        sys.path.insert(0, _src_dir)

    from src.agent.groundwater_agent import create_agent as _create_chat_agent
    from src.agent.research_agent import DeepResearchAgent

    _chat_agent = _create_chat_agent(verbose=False)
    _research_agent = DeepResearchAgent(
        max_depth=3,
        timeout_seconds=120,
    )
    logger.info("✅ LLM-backed agents initialised successfully")
except Exception as exc:
    logger.warning(
        f"⚠️  Could not initialise LLM agents — " f"falling back to rule-based chat. Reason: {exc}"
    )
    _chat_agent = None
    _research_agent = None


# ---------------------------------------------------------------------------
# POST /api/chat — conversational agent endpoint
# ---------------------------------------------------------------------------


@app.post("/api/chat")
def chat_endpoint(query: dict):
    """AI chat endpoint for groundwater questions.

    Uses the GroundwaterAgent when available; falls back to rule-based KB
    when the LLM provider is not configured or unreachable.

    Request body: { "message": "..." }
    """
    user_query = query.get("message", "")
    if not user_query:
        raise HTTPException(status_code=400, detail="Message is required")

    # --- Try real agent first ---
    if _chat_agent is not None:
        try:
            response_text = _chat_agent.chat(user_query)
            return {
                "response": response_text,
                "context": _get_site_context(),
                "sources": ["GroundwaterGPT Agent (LLM-backed)"],
                "mode": "agent",
                "status": "ok",
            }
        except Exception as exc:
            logger.error(f"Agent chat error: {exc}")
            # Fall through to rule-based fallback

    # --- Fallback ---
    return _fallback_response(user_query)


# ---------------------------------------------------------------------------
# POST /api/research — deep research endpoint
# ---------------------------------------------------------------------------


@app.post("/api/research")
def research_endpoint(query: dict):
    """Deep research endpoint — runs the iterative research agent.

    Request body:
        {
            "question": "...",
            "max_depth": 3,       # optional (default 3)
            "timeout": 120        # optional seconds (default 120)
        }

    Returns a structured research report with sourced insights.
    Falls back to a simple KB lookup when the research agent is unavailable.
    """
    question = query.get("question", "")
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    max_depth = int(query.get("max_depth", 3))
    timeout = float(query.get("timeout", 120))

    if _research_agent is not None:
        try:
            result = _research_agent.research(
                query=question,
                max_depth=max_depth,
                timeout=timeout,
            )
            return {
                "status": "ok",
                "mode": "deep_research",
                "report": result.get("report", ""),
                "insights": result.get("insights", []),
                "sources": result.get("sources", []),
                "search_history": result.get("search_history", []),
                "depth_reached": result.get("depth_reached", 0),
                "elapsed_seconds": result.get("elapsed_seconds", 0),
            }
        except Exception as exc:
            logger.error(f"Research agent error: {exc}\n{traceback.format_exc()}")
            # Fall through to fallback

    # --- Fallback: return whatever the rule-based KB can provide ---
    fb = _fallback_response(question)
    return {
        "status": "ok",
        "mode": "fallback",
        "report": fb["response"],
        "insights": [],
        "sources": fb["sources"],
        "search_history": [],
        "depth_reached": 0,
        "elapsed_seconds": 0,
    }


# ---------------------------------------------------------------------------
# GET /api/chat/status — system health for chat subsystem
# ---------------------------------------------------------------------------


@app.get("/api/chat/status")
def chat_status():
    """Get AI chat and research system status."""
    agent_available = _chat_agent is not None
    research_available = _research_agent is not None
    return {
        "status": "ok" if agent_available else "fallback",
        "version": "1.0.0",
        "agent_available": agent_available,
        "research_available": research_available,
        "features": (
            [
                "Conversational groundwater Q&A",
                "RAG with hydrogeology documents",
                "Seasonal pattern analysis",
                "Anomaly detection",
                "Data quality reports",
                "Deep research with iterative search",
            ]
            if agent_available
            else [
                "Rule-based groundwater Q&A (fallback mode)",
                "Irrigation planning advice",
                "Crop water requirements",
                "Seasonal patterns",
                "Aquifer information",
            ]
        ),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
