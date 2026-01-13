#!/usr/bin/env python3
"""Download real USGS groundwater and ERA5 climate data.

Downloads:
1. Real groundwater data from USGS National Water Information System (NWIS)
2. ERA5 climate data from Copernicus CDS (optional)

Usage:
    python download_data.py              # Download USGS groundwater (default)
    python download_data.py --climate    # Also download ERA5 climate data
    python download_data.py --site SITE  # Specify USGS site ID
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import requests

# Add parent to path for config
sys.path.insert(0, str(Path(__file__).parent))

from config import ACTIVE_REGION, CDS_API_KEY, CDS_URL, DATA_DIR, REGIONS, TIME_CONFIG  # noqa: E402

# =============================================================================
# USGS CONFIGURATION
# =============================================================================

# Default USGS site - Lee County, FL (near Fort Myers)
DEFAULT_USGS_SITE = "262724081260701"

# USGS NWIS Web Service
USGS_NWIS_URL = "https://waterservices.usgs.gov/nwis/dv/"

# Parameter codes for groundwater
USGS_PARAMS = {
    "72019": "Depth to water level, ft below land surface",
    "72020": "Water level altitude, ft above datum",
    "62610": "Groundwater level relative to datum, ft",
}


# =============================================================================
# USGS DATA DOWNLOAD
# =============================================================================


def fetch_usgs_groundwater(
    site_id: str = DEFAULT_USGS_SITE,
    start_date: str = "2014-01-01",
    end_date: str = "2023-12-31",
) -> pd.DataFrame:
    """Download real groundwater data from USGS NWIS.

    Args:
        site_id: USGS site identifier (15-digit code)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        DataFrame with columns: date, site_id, water_level_ft
    """
    print("\n💧 Downloading USGS groundwater data...")
    print(f"   Site: {site_id}")
    print(f"   Period: {start_date} to {end_date}")

    # Try multiple parameter codes (sites vary in what they report)
    for param_code, param_name in USGS_PARAMS.items():
        print(f"   Trying parameter {param_code} ({param_name})...", end=" ")

        params = {
            "sites": site_id,
            "parameterCd": param_code,
            "startDT": start_date,
            "endDT": end_date,
            "format": "json",
            "siteStatus": "all",
        }

        try:
            response = requests.get(USGS_NWIS_URL, params=params, timeout=60)
            response.raise_for_status()
            data = response.json()

            # Check if data exists
            time_series = data.get("value", {}).get("timeSeries", [])
            if not time_series:
                print("No data")
                continue

            # Extract values
            values = time_series[0].get("values", [{}])[0].get("value", [])
            if not values:
                print("Empty")
                continue

            print(f"✓ Found {len(values)} records")

            # Parse into DataFrame
            records = []
            for v in values:
                try:
                    date = pd.to_datetime(v["dateTime"]).date()
                    value = float(v["value"])
                    if value > -999:  # USGS uses -999999 for missing
                        records.append({"date": date, "site_id": site_id, "water_level_ft": value})
                except (ValueError, KeyError):
                    continue

            if records:
                df = pd.DataFrame(records)
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").drop_duplicates(subset=["date"])
                df = df.reset_index(drop=True)

                print(f"\n✓ Downloaded {len(df)} days of REAL USGS measurements")
                print(f"  Period: {df['date'].min().date()} to {df['date'].max().date()}")
                print(
                    f"  Water level range: {df['water_level_ft'].min():.2f} "
                    f"to {df['water_level_ft'].max():.2f} ft"
                )

                return df

        except requests.RequestException as e:
            print(f"Error: {e}")
            continue

    # If we get here, no data found
    raise RuntimeError(
        f"Could not fetch groundwater data for site {site_id}. "
        "Try a different site ID or check https://waterdata.usgs.gov/nwis"
    )


def search_usgs_sites(
    state: str = "FL",
    county: str = None,
    site_type: str = "GW",
    limit: int = 10,
) -> pd.DataFrame:
    """Search for USGS groundwater monitoring sites.

    Args:
        state: 2-letter state code
        county: County name (optional)
        site_type: Site type code (GW = groundwater)
        limit: Maximum number of results

    Returns:
        DataFrame with site information
    """
    print(f"\n🔍 Searching for USGS sites in {state}...")

    url = "https://waterservices.usgs.gov/nwis/site/"
    params = {
        "stateCd": state,
        "siteType": site_type,
        "siteStatus": "active",
        "hasDataTypeCd": "dv",  # Daily values available
        "format": "rdb",
    }

    if county:
        params["countyFips"] = county

    try:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()

        # Parse RDB format (tab-separated with comment lines)
        lines = [line for line in response.text.split("\n") if line and not line.startswith("#")]

        if len(lines) < 2:
            print("  No sites found")
            return pd.DataFrame()

        # First line is header, second is format, rest is data
        from io import StringIO

        df = pd.read_csv(
            StringIO("\n".join([lines[0]] + lines[2:])),
            sep="\t",
            dtype=str,
        )

        # Select relevant columns
        cols = ["site_no", "station_nm", "dec_lat_va", "dec_long_va"]
        df = df[[c for c in cols if c in df.columns]].head(limit)

        print(f"  Found {len(df)} sites")
        return df

    except requests.RequestException as e:
        print(f"  Error: {e}")
        return pd.DataFrame()


# =============================================================================
# ERA5 CLIMATE DATA (OPTIONAL)
# =============================================================================


def setup_cds_credentials():
    """Setup CDS API credentials."""
    cdsapi_rc = Path.home() / ".cdsapirc"
    if not cdsapi_rc.exists():
        cdsapi_rc.write_text(f"url: {CDS_URL}\nkey: {CDS_API_KEY}\n")
        print(f"✓ Created {cdsapi_rc}")
    return True


def download_era5_climate(years: list, region: dict) -> pd.DataFrame:
    """Download ERA5 climate data from Copernicus CDS.

    Downloads temperature and precipitation at daily resolution.
    For 10 years, this may take 10-30 minutes depending on CDS queue.
    """
    import cdsapi
    import xarray as xr

    setup_cds_credentials()
    client = cdsapi.Client()

    area = region["area"]  # [N, W, S, E]

    all_data = []

    print(f"\n📡 Downloading ERA5 data for {len(years)} years...")
    print(f"   Region: {region['name']} ({area})")
    print("   Note: Each year takes ~1-5 min depending on CDS queue\n")

    for year in years:
        print(f"   Downloading {year}...", end=" ", flush=True)

        # Temporary file for this year
        temp_file = DATA_DIR / f"era5_{year}_temp.grib"

        try:
            client.retrieve(
                "reanalysis-era5-single-levels",
                {
                    "product_type": "reanalysis",
                    "variable": [
                        "2m_temperature",
                        "total_precipitation",
                    ],
                    "year": year,
                    "month": [f"{m:02d}" for m in range(1, 13)],
                    "day": [f"{d:02d}" for d in range(1, 32)],
                    "time": ["12:00"],
                    "area": area,
                    "data_format": "grib",
                },
                str(temp_file),
            )

            # Process file
            ds = None
            for engine in ["cfgrib", "netcdf4", "scipy", "h5netcdf"]:
                try:
                    ds = xr.open_dataset(temp_file, engine=engine)
                    break
                except Exception:
                    continue

            if ds is None:
                raise RuntimeError(f"Could not open {temp_file}")

            # Extract daily means
            df_year = pd.DataFrame(
                {
                    "date": pd.to_datetime(ds.time.values),
                    "temperature_c": ds["t2m"].mean(dim=["latitude", "longitude"]).values - 273.15,
                    "precipitation_mm": ds["tp"].mean(dim=["latitude", "longitude"]).values * 1000,
                }
            )

            all_data.append(df_year)
            ds.close()
            temp_file.unlink()

            print(f"✓ {len(df_year)} days")

        except Exception as e:
            print(f"✗ Error: {e}")
            if temp_file.exists():
                temp_file.unlink()
            continue

    if not all_data:
        raise RuntimeError("Failed to download any ERA5 data")

    climate_df = pd.concat(all_data, ignore_index=True)
    climate_df = climate_df.sort_values("date").reset_index(drop=True)
    climate_df = climate_df.drop_duplicates(subset=["date"])

    print(f"\n✓ Downloaded {len(climate_df)} days of climate data")
    print(f"  Period: {climate_df['date'].min().date()} to {climate_df['date'].max().date()}")

    return climate_df


# =============================================================================
# MAIN
# =============================================================================


def main():
    """Run the USGS groundwater data download CLI."""
    parser = argparse.ArgumentParser(
        description="Download real USGS groundwater & ERA5 climate data"
    )
    parser.add_argument(
        "--site",
        type=str,
        default=DEFAULT_USGS_SITE,
        help=f"USGS site ID (default: {DEFAULT_USGS_SITE})",
    )
    parser.add_argument(
        "--climate",
        action="store_true",
        help="Also download ERA5 climate data (requires CDS API)",
    )
    parser.add_argument(
        "--search",
        type=str,
        metavar="STATE",
        help="Search for USGS sites in a state (e.g., FL)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=TIME_CONFIG["start_date"],
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=TIME_CONFIG["end_date"],
        help="End date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("   USGS GROUNDWATER DATA DOWNLOAD")
    print("=" * 60)

    DATA_DIR.mkdir(exist_ok=True)

    # Search mode
    if args.search:
        sites = search_usgs_sites(state=args.search)
        if not sites.empty:
            print("\nAvailable sites:")
            print(sites.to_string(index=False))
            print("\nUse: python download_data.py --site <site_no>")
        return

    # Download groundwater
    try:
        groundwater_df = fetch_usgs_groundwater(
            site_id=args.site,
            start_date=args.start,
            end_date=args.end,
        )
        gw_file = DATA_DIR / "groundwater.csv"
        groundwater_df.to_csv(gw_file, index=False)
        print(f"\n💾 Saved: {gw_file}")
    except Exception as e:
        print(f"\n❌ Error downloading groundwater data: {e}")
        return

    # Optionally download climate
    if args.climate:
        try:
            region = REGIONS[ACTIVE_REGION]
            years = TIME_CONFIG["years"]
            climate_df = download_era5_climate(years, region)
            climate_file = DATA_DIR / "climate.csv"
            climate_df.to_csv(climate_file, index=False)
            print(f"💾 Saved: {climate_file}")
        except Exception as e:
            print(f"\n⚠️ Climate download failed: {e}")
            print("  Groundwater data was saved successfully.")

    print("\n" + "=" * 60)
    print("   DOWNLOAD COMPLETE")
    print("=" * 60)
    print("\nData source: USGS National Water Information System (NWIS)")
    print(f"Site ID: {args.site}")
    print(f"URL: https://waterdata.usgs.gov/nwis/uv?site_no={args.site}")
    print("\nNext steps:")
    print("  python train_groundwater.py   # Train prediction model")
    print("  python dashboard.py           # Generate trend dashboard")
    print()


if __name__ == "__main__":
    main()
