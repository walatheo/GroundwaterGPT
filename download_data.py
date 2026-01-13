#!/usr/bin/env python3
"""
================================================================================
DOWNLOAD_DATA.PY - Download Extended Climate & Groundwater Data
================================================================================

Downloads 10 years (2014-2023) of ERA5 climate data from Copernicus CDS
and generates corresponding modeled groundwater data.

Usage:
    python download_data.py              # Download all data
    python download_data.py --climate    # Climate only
    python download_data.py --groundwater # Groundwater only (requires climate)
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

# Add parent to path for config
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    TIME_CONFIG, REGIONS, ACTIVE_REGION,
    CDS_API_KEY, CDS_URL,
    DATA_DIR
)


def setup_cds_credentials():
    """Setup CDS API credentials."""
    cdsapi_rc = Path.home() / ".cdsapirc"
    if not cdsapi_rc.exists():
        cdsapi_rc.write_text(f"url: {CDS_URL}\nkey: {CDS_API_KEY}\n")
        print(f"✓ Created {cdsapi_rc}")
    return True


def download_era5_climate(years: list, region: dict) -> pd.DataFrame:
    """
    Download ERA5 climate data from Copernicus CDS.
    
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
    print(f"   Note: Each year takes ~1-5 min depending on CDS queue\n")
    
    for year in years:
        print(f"   Downloading {year}...", end=" ", flush=True)
        
        # Temporary file for this year - use GRIB (faster)
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
                str(temp_file)
            )
            
            # Process GRIB file with cfgrib or fallback
            ds = None
            try:
                ds = xr.open_dataset(temp_file, engine='cfgrib')
            except Exception:
                # Fallback: try netcdf engines (CDS sometimes returns netcdf anyway)
                for engine in ['netcdf4', 'scipy', 'h5netcdf']:
                    try:
                        ds = xr.open_dataset(temp_file, engine=engine)
                        break
                    except Exception:
                        continue
            
            if ds is None:
                raise RuntimeError(f"Could not open {temp_file} with any engine")
            
            # Extract daily means
            df_year = pd.DataFrame({
                "date": pd.to_datetime(ds.time.values),
                "temperature_c": ds["t2m"].mean(dim=["latitude", "longitude"]).values - 273.15,
                "precipitation_mm": ds["tp"].mean(dim=["latitude", "longitude"]).values * 1000,
            })
            
            all_data.append(df_year)
            ds.close()
            
            # Cleanup temp file
            temp_file.unlink()
            
            print(f"✓ {len(df_year)} days")
            
        except Exception as e:
            print(f"✗ Error: {e}")
            if temp_file.exists():
                temp_file.unlink()
            continue
    
    if not all_data:
        raise RuntimeError("Failed to download any ERA5 data")
    
    # Combine all years
    climate_df = pd.concat(all_data, ignore_index=True)
    climate_df = climate_df.sort_values("date").reset_index(drop=True)
    climate_df = climate_df.drop_duplicates(subset=["date"])
    
    print(f"\n✓ Downloaded {len(climate_df)} days of climate data")
    print(f"  Period: {climate_df['date'].min().date()} to {climate_df['date'].max().date()}")
    
    return climate_df


def generate_modeled_groundwater(climate_df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate physically-realistic groundwater data based on climate.
    
    Model incorporates:
    1. Seasonal cycle (wet season recharge in June-October)
    2. Precipitation lag (7-30 day aquifer response time)
    3. Temperature effects (ET reduces water table)
    4. Long-term trend (slight decline over decade)
    5. Interannual variability
    6. Random noise
    """
    print("\n💧 Generating modeled groundwater data...")
    
    df = climate_df.copy()
    df = df.sort_values("date").reset_index(drop=True)
    
    # Time features
    df["day_of_year"] = df["date"].dt.dayofyear
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    
    # Base year for trend calculation
    base_year = df["year"].min()
    years_elapsed = df["year"] - base_year
    
    # ==========================================================================
    # GROUNDWATER MODEL COMPONENTS
    # ==========================================================================
    
    # 1. Seasonal cycle (peak in late wet season ~October)
    seasonal_phase = 2 * np.pi * (df["day_of_year"] - 100) / 365
    seasonal = 1.2 * np.sin(seasonal_phase)
    
    # 2. Precipitation effect with lag
    precip_lag7 = df["precipitation_mm"].rolling(7, min_periods=1).sum().shift(7).fillna(0)
    precip_lag14 = df["precipitation_mm"].rolling(14, min_periods=1).sum().shift(14).fillna(0)
    precip_lag30 = df["precipitation_mm"].rolling(30, min_periods=1).sum().shift(30).fillna(0)
    
    precip_effect = (0.5 * precip_lag7 + 0.3 * precip_lag14 + 0.2 * precip_lag30)
    precip_effect = (precip_effect - precip_effect.mean()) / precip_effect.std() * 0.8
    
    # 3. Temperature effect (higher temp = lower water table)
    temp_effect = -(df["temperature_c"] - df["temperature_c"].mean()) / df["temperature_c"].std() * 0.4
    
    # 4. Long-term trend (-0.05 ft/year)
    long_term_trend = -0.05 * years_elapsed
    
    # 5. Interannual variability (4-year cycle)
    days_total = (df["date"] - df["date"].min()).dt.days
    interannual = 0.5 * np.sin(2 * np.pi * days_total / (4 * 365))
    
    # 6. Random noise
    np.random.seed(42)
    noise = np.random.normal(0, 0.15, len(df))
    
    # ==========================================================================
    # COMBINE COMPONENTS
    # ==========================================================================
    
    base_level = 5.0  # feet
    
    water_level = (
        base_level +
        seasonal +
        precip_effect +
        temp_effect +
        long_term_trend +
        interannual +
        noise
    )
    
    # Clip to realistic values
    water_level = np.clip(water_level, 1.0, 12.0)
    
    groundwater_df = pd.DataFrame({
        "date": df["date"],
        "site_id": "FM_MODELED_001",
        "water_level_ft": water_level
    })
    
    print(f"✓ Generated {len(groundwater_df)} days of groundwater data")
    print(f"  Water level range: {water_level.min():.2f} to {water_level.max():.2f} ft")
    print(f"  Long-term trend: {long_term_trend.iloc[-1]:.2f} ft over {years_elapsed.max()} years")
    
    return groundwater_df


def main():
    parser = argparse.ArgumentParser(description="Download extended climate & groundwater data")
    parser.add_argument("--climate", action="store_true", help="Download climate only")
    parser.add_argument("--groundwater", action="store_true", help="Generate groundwater only")
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("   EXTENDED DATA DOWNLOAD (10 Years)")
    print("=" * 60)
    
    region = REGIONS[ACTIVE_REGION]
    years = TIME_CONFIG["years"]
    
    print(f"\n📅 Period: {TIME_CONFIG['start_date']} to {TIME_CONFIG['end_date']}")
    print(f"📍 Region: {region['name']}")
    print(f"📊 Years: {len(years)}")
    
    DATA_DIR.mkdir(exist_ok=True)
    
    download_climate = not args.groundwater or args.climate
    generate_gw = not args.climate or args.groundwater
    
    climate_file = DATA_DIR / "climate.csv"
    
    if download_climate:
        climate_df = download_era5_climate(years, region)
        climate_df.to_csv(climate_file, index=False)
        print(f"\n💾 Saved: {climate_file}")
    else:
        if not climate_file.exists():
            print("❌ Climate data required. Run without --groundwater first.")
            return
        climate_df = pd.read_csv(climate_file, parse_dates=["date"])
        print(f"\n📂 Loaded existing climate: {len(climate_df)} records")
    
    if generate_gw:
        groundwater_df = generate_modeled_groundwater(climate_df)
        gw_file = DATA_DIR / "groundwater.csv"
        groundwater_df.to_csv(gw_file, index=False)
        print(f"💾 Saved: {gw_file}")
    
    print("\n" + "=" * 60)
    print("   DOWNLOAD COMPLETE")
    print("=" * 60)
    print("\nNext steps:")
    print("  python main.py           # Run full analysis pipeline")
    print("  python dashboard.py      # Generate trend dashboard")
    print()


if __name__ == "__main__":
    main()
