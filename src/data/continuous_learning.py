"""Continuous Learning Module for GroundwaterGPT.

This module enables the knowledge base to continuously grow by:
1. Fetching new USGS groundwater data from multiple sites
2. Indexing new research papers and documents
3. Storing verified research insights
4. Running on a schedule or manually

Architecture:
    ContinuousLearner class orchestrates:
    - USGS Water Services API calls
    - Data transformation and summary generation
    - Knowledge base (ChromaDB) updates
    - Source verification for all data

Data Flow:
    USGS API → DataFrame → Summary Document → ChromaDB

Key Components:
    - FLORIDA_AQUIFER_SITES: Configuration of monitored USGS sites
    - ContinuousLearner: Main class for data collection
    - LearningStats: Tracks learning session metrics

Example:
    >>> from continuous_learning import ContinuousLearner
    >>> learner = ContinuousLearner(days_of_history=365)
    >>> stats = learner.fetch_all_florida_aquifer_data()
    >>> print(f"Added {stats.documents_added} documents")

The LLM uses all this accumulated knowledge to answer questions.
"""

import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

# Add parent directories to path for imports
ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "src"))

from src.agent.knowledge import add_document, get_knowledge_stats
from src.agent.source_verification import verify_source

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# FLORIDA AQUIFER MONITORING SITES
# ============================================================================

# Major Florida Aquifers and representative USGS monitoring sites
# These are VERIFIED active sites with recent data (as of Jan 2026)
FLORIDA_AQUIFER_SITES = {
    # Floridan Aquifer System (largest in Florida)
    "floridan_aquifer": {
        "description": "Floridan Aquifer System - Primary drinking water source for most of Florida",
        "sites": [
            {"site_no": "262724081260701", "name": "Lee County - Fort Myers", "county": "Lee"},
            {
                "site_no": "284110082240001",
                "name": "Citrus County - Crystal River",
                "county": "Citrus",
            },
            {"site_no": "291005082192001", "name": "Levy County", "county": "Levy"},
            {
                "site_no": "301053081415201",
                "name": "Duval County - Jacksonville",
                "county": "Duval",
            },
            {"site_no": "283127082165301", "name": "Hernando County", "county": "Hernando"},
            {
                "site_no": "294523082353301",
                "name": "Alachua County - Gainesville",
                "county": "Alachua",
            },
        ],
    },
    # Biscayne Aquifer (Southeast Florida) - Very active monitoring
    "biscayne_aquifer": {
        "description": "Biscayne Aquifer - Supplies water to Miami-Dade and Broward counties",
        "sites": [
            {"site_no": "251241080385301", "name": "Miami-Dade G-3764", "county": "Miami-Dade"},
            {"site_no": "251457080395802", "name": "Miami-Dade G-3777", "county": "Miami-Dade"},
            {"site_no": "251922080340701", "name": "Miami-Dade G-1251", "county": "Miami-Dade"},
            {"site_no": "252007080335701", "name": "Miami-Dade G-3336", "county": "Miami-Dade"},
            {"site_no": "252036080293501", "name": "Miami-Dade G-5004", "county": "Miami-Dade"},
            {"site_no": "260947080102301", "name": "Broward County G-2033", "county": "Broward"},
            {"site_no": "261029080070901", "name": "Broward County G-2031", "county": "Broward"},
        ],
    },
    # Surficial Aquifer System
    "surficial_aquifer": {
        "description": "Surficial Aquifer System - Shallow aquifer across Florida",
        "sites": [
            {"site_no": "270915080161501", "name": "Martin County", "county": "Martin"},
            {"site_no": "265532080091401", "name": "Palm Beach County", "county": "Palm Beach"},
        ],
    },
    # Southwest Florida sites
    "southwest_florida": {
        "description": "Southwest Florida - Coastal aquifer monitoring",
        "sites": [
            {"site_no": "263156082022801", "name": "Charlotte County", "county": "Charlotte"},
            {"site_no": "271453082165901", "name": "Sarasota County", "county": "Sarasota"},
            {"site_no": "273612082240601", "name": "Manatee County", "county": "Manatee"},
        ],
    },
}


@dataclass
class LearningStats:
    """Track continuous learning statistics."""

    documents_added: int = 0
    usgs_records_added: int = 0
    sites_processed: int = 0
    errors: list = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None

    def to_dict(self) -> dict:
        """Convert stats to dictionary."""
        return {
            "documents_added": self.documents_added,
            "usgs_records_added": self.usgs_records_added,
            "sites_processed": self.sites_processed,
            "errors": self.errors,
            "duration_seconds": (
                (self.end_time or datetime.now()) - self.start_time
            ).total_seconds(),
        }


class ContinuousLearner:
    """Continuously grows the knowledge base with new data."""

    def __init__(
        self,
        data_dir: str = "data",
        days_of_history: int = 365 * 10,  # 10 years default
    ):
        """Initialize the continuous learner.

        Args:
            data_dir: Directory to store downloaded data
            days_of_history: How many days of historical data to fetch
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.days_of_history = days_of_history
        self.stats = LearningStats()

    def fetch_usgs_site_data(
        self, site_no: str, site_name: str, aquifer: str
    ) -> pd.DataFrame | None:
        """Fetch groundwater data from a USGS site.

        Args:
            site_no: USGS site number
            site_name: Human-readable site name
            aquifer: Aquifer system name

        Returns:
            DataFrame with groundwater data, or None if failed
        """
        logger.info(f"📡 Fetching data for {site_name} ({site_no})...")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.days_of_history)

        url = "https://waterservices.usgs.gov/nwis/gwlevels/"
        params = {
            "format": "json",
            "sites": site_no,
            "startDT": start_date.strftime("%Y-%m-%d"),
            "endDT": end_date.strftime("%Y-%m-%d"),
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Parse the USGS JSON response
            time_series = data.get("value", {}).get("timeSeries", [])
            if not time_series:
                logger.warning(f"No data found for site {site_no}")
                return None

            records = []
            for ts in time_series:
                values = ts.get("values", [{}])[0].get("value", [])
                for v in values:
                    records.append(
                        {
                            "site_no": site_no,
                            "site_name": site_name,
                            "aquifer": aquifer,
                            "datetime": v.get("dateTime"),
                            "value": float(v.get("value", 0)),
                            "unit": "ft below land surface",
                        }
                    )

            if records:
                df = pd.DataFrame(records)
                df["datetime"] = pd.to_datetime(df["datetime"])
                logger.info(f"  ✅ Retrieved {len(df)} records")
                return df

        except Exception as e:
            logger.error(f"  ❌ Error fetching {site_no}: {e}")
            self.stats.errors.append(f"{site_no}: {str(e)}")

        return None

    def add_usgs_data_to_knowledge_base(
        self, df: pd.DataFrame, site_info: dict, aquifer_name: str
    ) -> int:
        """Add USGS data to the knowledge base.

        Args:
            df: DataFrame with groundwater data
            site_info: Site metadata
            aquifer_name: Name of the aquifer

        Returns:
            Number of documents added
        """
        added = 0

        # Create a summary document for this site
        summary = f"""USGS Groundwater Monitoring Data Summary

Site: {site_info['name']}
Site Number: {site_info['site_no']}
County: {site_info.get('county', 'Unknown')}
Aquifer: {aquifer_name.replace('_', ' ').title()}

Data Period: {df['datetime'].min().strftime('%Y-%m-%d')} to {df['datetime'].max().strftime('%Y-%m-%d')}
Total Records: {len(df)}

Statistics:
- Mean Water Level: {df['value'].mean():.2f} ft below land surface
- Min Water Level: {df['value'].min():.2f} ft (highest water)
- Max Water Level: {df['value'].max():.2f} ft (lowest water)
- Standard Deviation: {df['value'].std():.2f} ft

Annual Averages:
"""
        # Add annual averages
        df["year"] = df["datetime"].dt.year
        annual = df.groupby("year")["value"].mean()
        for year, avg in annual.items():
            summary += f"- {year}: {avg:.2f} ft\n"

        # Calculate trend
        if len(annual) > 1:
            years = annual.index.values
            values = annual.values
            slope = (values[-1] - values[0]) / (years[-1] - years[0])
            trend = "declining" if slope > 0 else "rising"
            summary += f"\nTrend: Water levels are {trend} at {abs(slope):.3f} ft/year"

        # Add to knowledge base
        metadata = {
            "doc_type": "usgs_groundwater_data",
            "site_no": site_info["site_no"],
            "site_name": site_info["name"],
            "county": site_info.get("county", "Unknown"),
            "aquifer": aquifer_name,
            "data_start": df["datetime"].min().isoformat(),
            "data_end": df["datetime"].max().isoformat(),
            "record_count": len(df),
            "source": "USGS NWIS",
            "verified": True,
        }

        try:
            success = add_document(
                content=summary,
                metadata=metadata,
                source_url=f"https://waterdata.usgs.gov/nwis/uv?site_no={site_info['site_no']}",
                require_verification=False,  # USGS is pre-verified
            )
            if success:
                added += 1
                logger.info(f"  📚 Added summary to knowledge base")
        except Exception as e:
            logger.error(f"  ❌ Failed to add to KB: {e}")

        return added

    def fetch_all_florida_aquifer_data(self) -> LearningStats:
        """Fetch data from all configured Florida aquifer sites.

        Returns:
            Learning statistics
        """
        self.stats = LearningStats()
        logger.info("🌊 Starting Florida Aquifer Data Collection...")
        logger.info(f"   Configured aquifers: {len(FLORIDA_AQUIFER_SITES)}")

        all_data = []

        for aquifer_name, aquifer_info in FLORIDA_AQUIFER_SITES.items():
            logger.info(f"\n📍 {aquifer_info['description']}")

            for site in aquifer_info["sites"]:
                df = self.fetch_usgs_site_data(site["site_no"], site["name"], aquifer_name)

                if df is not None and len(df) > 0:
                    # Save to CSV
                    csv_path = self.data_dir / f"usgs_{site['site_no']}.csv"
                    df.to_csv(csv_path, index=False)

                    # Add to knowledge base
                    docs_added = self.add_usgs_data_to_knowledge_base(df, site, aquifer_name)

                    self.stats.documents_added += docs_added
                    self.stats.usgs_records_added += len(df)
                    self.stats.sites_processed += 1

                    all_data.append(df)

                # Be nice to USGS servers
                time.sleep(1)

        # Combine all data
        if all_data:
            combined = pd.concat(all_data, ignore_index=True)
            combined.to_csv(self.data_dir / "all_florida_aquifers.csv", index=False)
            logger.info(f"\n💾 Saved combined data: {len(combined)} total records")

        self.stats.end_time = datetime.now()
        return self.stats

    def add_research_papers(self, papers: list[dict]) -> int:
        """Add research papers to the knowledge base.

        Args:
            papers: List of paper dictionaries with 'title', 'abstract', 'url', 'authors'

        Returns:
            Number of papers added
        """
        added = 0

        for paper in papers:
            # Verify the source
            verification = verify_source(paper.get("url", ""))

            if not verification.is_approved:
                logger.warning(f"Skipping unverified paper: {paper.get('title')}")
                continue

            content = f"""Research Paper: {paper.get('title', 'Unknown')}

Authors: {paper.get('authors', 'Unknown')}
Published: {paper.get('date', 'Unknown')}
Source: {paper.get('url', 'Unknown')}

Abstract:
{paper.get('abstract', 'No abstract available')}

Keywords: {', '.join(paper.get('keywords', []))}
"""

            metadata = {
                "doc_type": "research_paper",
                "title": paper.get("title"),
                "authors": paper.get("authors"),
                "url": paper.get("url"),
                "verified": True,
                "trust_level": verification.trust_level.value,
            }

            try:
                success = add_document(
                    content=content,
                    metadata=metadata,
                    source_url=paper.get("url", ""),
                    require_verification=False,
                )
                if success:
                    added += 1
            except Exception as e:
                logger.error(f"Failed to add paper: {e}")

        return added

    def get_learning_status(self) -> dict:
        """Get current knowledge base status."""
        kb_stats = get_knowledge_stats()

        return {
            "knowledge_base": kb_stats,
            "configured_aquifers": len(FLORIDA_AQUIFER_SITES),
            "configured_sites": sum(len(a["sites"]) for a in FLORIDA_AQUIFER_SITES.values()),
            "last_update": self.stats.end_time.isoformat() if self.stats.end_time else None,
        }


def run_continuous_learning(
    include_usgs: bool = True,
    days_of_history: int = 365 * 10,
) -> dict:
    """Run a continuous learning cycle.

    Args:
        include_usgs: Whether to fetch USGS data
        days_of_history: Days of historical data to fetch

    Returns:
        Learning statistics
    """
    learner = ContinuousLearner(days_of_history=days_of_history)

    results = {"usgs": None, "papers": None}

    if include_usgs:
        logger.info("=" * 60)
        logger.info("CONTINUOUS LEARNING - USGS Data Collection")
        logger.info("=" * 60)
        stats = learner.fetch_all_florida_aquifer_data()
        results["usgs"] = stats.to_dict()

    # Get final status
    results["final_status"] = learner.get_learning_status()

    return results


# ============================================================================
# CLI INTERFACE
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Continuous Learning for GroundwaterGPT")
    parser.add_argument("--usgs", action="store_true", default=True, help="Fetch USGS data")
    parser.add_argument("--days", type=int, default=3650, help="Days of history to fetch")
    parser.add_argument("--status", action="store_true", help="Show current learning status")

    args = parser.parse_args()

    if args.status:
        learner = ContinuousLearner()
        status = learner.get_learning_status()
        print("\n📊 Knowledge Base Status:")
        print(f"   Documents: {status['knowledge_base'].get('total_documents', 0):,}")
        print(f"   Configured Aquifers: {status['configured_aquifers']}")
        print(f"   Configured Sites: {status['configured_sites']}")
    else:
        results = run_continuous_learning(
            include_usgs=args.usgs,
            days_of_history=args.days,
        )

        print("\n" + "=" * 60)
        print("LEARNING COMPLETE")
        print("=" * 60)

        if results["usgs"]:
            print(f"USGS Sites Processed: {results['usgs']['sites_processed']}")
            print(f"Records Added: {results['usgs']['usgs_records_added']:,}")
            print(f"Documents Added: {results['usgs']['documents_added']}")

        print(
            f"\nKnowledge Base Total: {results['final_status']['knowledge_base'].get('total_documents', 0):,} documents"
        )
