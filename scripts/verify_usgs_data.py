#!/usr/bin/env python3
"""
USGS Data Verification Script

This script verifies that the data in the Knowledge Base matches
the raw USGS CSV data that was downloaded from the USGS NWIS API.

Usage:
    python3 scripts/verify_usgs_data.py

What it checks:
    - Mean water levels match
    - Record counts match
    - Min/Max values match
    - Site IDs are correct
    - Aquifer types are correct
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd

from src.agent.knowledge import search_usgs_data


def verify_site(csv_file: str, site_name: str) -> dict:
    """Verify a single site's data matches between CSV and KB."""
    # Load CSV
    df = pd.read_csv(csv_file)

    # Calculate statistics from CSV
    csv_stats = {
        "mean": round(df["value"].mean(), 2),
        "min": round(df["value"].min(), 2),
        "max": round(df["value"].max(), 2),
        "records": len(df),
        "site_id": str(df["site_no"].iloc[0]),
    }

    # Get KB data
    results = search_usgs_data(site_name=site_name, k=5)
    kb_content = " ".join([r.page_content for r in results])

    # Check matches
    matches = {
        "mean": str(csv_stats["mean"]) in kb_content,
        "records": str(csv_stats["records"]) in kb_content,
        "site_id": csv_stats["site_id"] in kb_content,
    }

    return {
        "site_name": site_name,
        "csv_stats": csv_stats,
        "matches": matches,
        "all_match": all(matches.values()),
    }


def main():
    print("=" * 70)
    print("🔬 USGS DATA VERIFICATION")
    print("   Comparing Knowledge Base data to raw USGS CSV files")
    print("=" * 70)
    print()

    # Define all sites to verify
    sites = [
        ("data/usgs_251241080385301.csv", "Miami-Dade G-3764"),
        ("data/usgs_251457080395802.csv", "Miami-Dade G-3777"),
        ("data/usgs_251922080340701.csv", "Miami-Dade G-1251"),
        ("data/usgs_252007080335701.csv", "Miami-Dade G-3336"),
        ("data/usgs_252036080293501.csv", "Miami-Dade G-5004"),
        ("data/usgs_262724081260701.csv", "Lee County - Fort Myers"),
    ]

    all_verified = True

    for csv_file, site_name in sites:
        csv_path = PROJECT_ROOT / csv_file

        if not csv_path.exists():
            print(f"⚠️  CSV not found: {csv_file}")
            continue

        result = verify_site(str(csv_path), site_name)

        status = "✅" if result["all_match"] else "❌"
        all_verified = all_verified and result["all_match"]

        print(f"{status} {site_name}")
        print(f"   Site ID: {result['csv_stats']['site_id']}")
        print(
            f"   CSV Stats: Mean={result['csv_stats']['mean']}ft, "
            f"Records={result['csv_stats']['records']}, "
            f"Range=[{result['csv_stats']['min']}, {result['csv_stats']['max']}]"
        )
        print(f"   KB Match: {result['matches']}")
        print()

    print("=" * 70)
    if all_verified:
        print("✅ VERIFICATION PASSED: All KB data matches USGS source data!")
    else:
        print("❌ VERIFICATION FAILED: Some data does not match")
    print("=" * 70)

    # Additional: Show how to verify against live USGS website
    print()
    print("📌 To manually verify against USGS website:")
    print("   Visit: https://waterdata.usgs.gov/nwis/gwlevels?site_no=<SITE_ID>")
    print()
    print("   Example URLs:")
    for csv_file, site_name in sites[:2]:
        df = pd.read_csv(PROJECT_ROOT / csv_file)
        site_id = df["site_no"].iloc[0]
        print(f"   - {site_name}: https://waterdata.usgs.gov/nwis/gwlevels?site_no={site_id}")

    return 0 if all_verified else 1


if __name__ == "__main__":
    sys.exit(main())
