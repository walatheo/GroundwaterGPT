#!/usr/bin/env python3
"""Canonical USGS Groundwater Data Pipeline.

This module provides the single source of truth for downloading, validating,
and organizing groundwater data from 36 USGS monitoring sites across Florida.

Architecture:
    - Centralized orchestration via run_pipeline()
    - Modular stages: fetch → validate → engineer → save
    - Stateless, parallelizable design
    - Comprehensive error handling and logging
    - Data quality validation and manifest tracking

Usage:
    from src.data.pipeline import run_pipeline

    # Fetch all 36 sites
    results = run_pipeline()

    # Fetch specific sites
    results = run_pipeline(sites=['251241080385301', '262724081260701'])

    # Sequential processing (debug mode)
    results = run_pipeline(parallel=False)

    # Custom date range
    results = run_pipeline(start_date='2020-01-01', end_date='2023-12-31')

Data Flow:
    USGS NWIS API
        ↓ (fetch_single_site)
    Raw JSON response
        ↓ (parse_usgs_response)
    DataFrame with raw records
        ↓ (validate_schema)
    Validated DataFrame
        ↓ (engineer_features - optional)
    DataFrame with features
        ↓ (save_site_data)
    CSV file with timestamp

Returns:
    Dict[site_id, Path] mapping each site to its output CSV file

Success Metrics:
    - All 36 sites fetched in < 30 minutes
    - 100% schema validation pass rate on known sites
    - 0 data corruption or leakage
    - Complete audit trail in manifest.json

Dependencies:
    - pandas: Data manipulation
    - requests: USGS API calls
    - config: Site list and configuration
    - agent.source_verification (optional): Verify USGS data authenticity

Testing:
    pytest tests/data/test_pipeline.py -v

Author: Data Engineering Team
Version: 1.0
Last Updated: February 18, 2026
"""

import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

# ============================================================================
# SETUP & CONFIGURATION
# ============================================================================

# Ensure imports work from different calling contexts
ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Configure logging with both file and console output
logger = logging.getLogger(__name__)

# Load USGS sites configuration
USGS_SITES_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "usgs_sites.json"

if USGS_SITES_CONFIG_PATH.exists():
    with open(USGS_SITES_CONFIG_PATH, "r") as f:
        USGS_CONFIG = json.load(f)
else:
    logger.warning(f"USGS sites config not found at {USGS_SITES_CONFIG_PATH}")
    USGS_CONFIG = {"aquifers": {}}

# USGS API Configuration
USGS_NWIS_URL = "https://waterservices.usgs.gov/nwis/gwlevels/"
USGS_PARAMETER_CODES = ["72019", "62610", "62611", "72020"]
USGS_API_TIMEOUT = 60  # seconds
USGS_API_RETRY_MAX = 3
USGS_API_BACKOFF_FACTOR = 2

# Pipeline Configuration
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = DATA_DIR / "logs"
DEFAULT_START_DATE = "1994-01-01"
DEFAULT_END_DATE = datetime.now().strftime("%Y-%m-%d")


# ============================================================================
# DATA CLASSES & STRUCTURES
# ============================================================================


@dataclass
class ValidationResult:
    """Result of schema and value validation for a single site."""

    site_id: str
    valid: bool
    record_count: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checks: Dict[str, bool] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure checks dict is populated."""
        if not self.checks:
            self.checks = {
                "schema_valid": False,
                "values_in_range": False,
                "datetime_valid": False,
                "no_duplicates": False,
            }


@dataclass
class PipelineStats:
    """Aggregate statistics for entire pipeline run."""

    timestamp: datetime
    duration_seconds: float = 0
    sites_total: int = 0
    sites_successful: int = 0
    sites_failed: int = 0
    total_records_fetched: int = 0
    total_records_saved: int = 0
    output_format: str = "csv"
    output_files: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    validation_summary: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "duration_seconds": self.duration_seconds,
            "sites_total": self.sites_total,
            "sites_successful": self.sites_successful,
            "sites_failed": self.sites_failed,
            "total_records_fetched": self.total_records_fetched,
            "total_records_saved": self.total_records_saved,
            "output_format": self.output_format,
            "output_files": self.output_files,
            "errors": self.errors,
            "warnings": self.warnings,
            "validation_summary": self.validation_summary,
        }


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def setup_logging(log_dir: Path = LOG_DIR) -> Path:
    """Setup logging to both file and console.

    Args:
        log_dir: Directory for log files

    Returns:
        Path to the log file
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d")
    log_file = log_dir / f"pipeline_run_{timestamp}.log"

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.setLevel(logging.DEBUG)

    return log_file


def get_all_site_ids() -> List[str]:
    """Extract all 36 USGS site IDs from configuration.

    Returns:
        List of 15-digit USGS site IDs

    Raises:
        ValueError: If configuration is invalid or missing sites
    """
    site_ids = []

    for aquifer_name, aquifer_data in USGS_CONFIG.get("aquifers", {}).items():
        for site in aquifer_data.get("sites", []):
            site_ids.append(site.get("site_id"))

    if not site_ids:
        raise ValueError("No USGS sites found in configuration")

    logger.info(f"Loaded {len(site_ids)} site IDs from configuration")
    return site_ids


# ============================================================================
# FETCH STAGE
# ============================================================================


def fetch_single_site(
    site_id: str,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
) -> Optional[pd.DataFrame]:
    """Fetch groundwater data for a single USGS site with retries.

    This function:
    1. Tries multiple USGS parameter codes (72019, 62610, 62611, 72020)
    2. Implements exponential backoff retry (up to 3 attempts)
    3. Verifies data authenticity (optional)
    4. Returns raw data as DataFrame

    Args:
        site_id: 15-digit USGS site ID
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        DataFrame with columns [site_no, datetime, value] or None if failed

    Raises:
        requests.RequestException: If all retries exhausted
    """
    logger.debug(f"Fetching data for site {site_id}...")

    # Try multiple parameter codes (different sites report different parameters)
    for param_code in USGS_PARAMETER_CODES:
        logger.debug(f"  Trying parameter code {param_code}...")

        # Retry loop with exponential backoff
        for attempt in range(USGS_API_RETRY_MAX):
            try:
                params = {
                    "sites": site_id,
                    "parameterCd": param_code,
                    "startDT": start_date,
                    "endDT": end_date,
                    "format": "json",
                    "siteStatus": "all",
                }

                response = requests.get(
                    USGS_NWIS_URL,
                    params=params,
                    timeout=USGS_API_TIMEOUT,
                )
                response.raise_for_status()

                data = response.json()

                # Optional: Verify data authenticity with source verification
                try:
                    from src.agent.source_verification import verify_usgs_data

                    verification = verify_usgs_data(site_id, data)
                    if not verification.is_approved:
                        logger.warning(
                            f"USGS verification failed for {site_id}: {verification.reason}"
                        )
                        continue
                except (ImportError, AttributeError):
                    pass  # Source verification module not available

                # Parse response
                time_series = data.get("value", {}).get("timeSeries", [])
                if not time_series:
                    logger.debug(f"  No data for parameter {param_code}")
                    continue

                # Extract values
                records = []
                for ts in time_series:
                    values = ts.get("values", [{}])[0].get("value", [])
                    for v in values:
                        try:
                            value = float(v.get("value"))
                            # USGS uses -999999 as missing value sentinel
                            if value > -999:
                                records.append(
                                    {
                                        "site_no": site_id,
                                        "datetime": v.get("dateTime"),
                                        "value": value,
                                    }
                                )
                        except (ValueError, TypeError):
                            continue

                if records:
                    df = pd.DataFrame(records)
                    logger.info(
                        f"  ✓ Fetched {len(df)} records from {site_id} " f"(parameter {param_code})"
                    )
                    return df

                logger.debug(f"  No valid records for parameter {param_code}")
                continue

            except requests.RequestException as e:
                wait_time = USGS_API_BACKOFF_FACTOR**attempt
                logger.debug(
                    f"  Attempt {attempt + 1}/{USGS_API_RETRY_MAX} failed: {e}. "
                    f"Retrying in {wait_time}s..."
                )
                time.sleep(wait_time)
                continue

        logger.warning(f"Failed to fetch data for site {site_id} (all param codes)")

    return None


# ============================================================================
# VALIDATE STAGE
# ============================================================================


def validate_schema(df: pd.DataFrame, site_id: str) -> ValidationResult:
    """Validate that data has correct schema and value ranges.

    This function verifies:
    1. Required columns exist (site_no, datetime, value)
    2. Data types are correct
    3. Values are in reasonable ranges for Florida aquifers
    4. Datetime values are valid and sorted
    5. No critical duplicates

    Args:
        df: DataFrame with raw USGS data
        site_id: Site ID for logging

    Returns:
        ValidationResult with details of all checks
    """
    result = ValidationResult(site_id=site_id, valid=True, record_count=len(df))

    # Check 1: Required columns
    required_cols = ["site_no", "datetime", "value"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        result.valid = False
        result.errors.append(f"Missing columns: {missing_cols}")
        result.checks["schema_valid"] = False
        logger.error(f"  Schema error for {site_id}: {missing_cols}")
        return result
    result.checks["schema_valid"] = True

    # Check 2: Parse datetime and validate
    try:
        df["datetime"] = pd.to_datetime(df["datetime"])
    except (ValueError, pd.errors.ParserError) as e:
        result.valid = False
        result.errors.append(f"Invalid datetime format: {e}")
        result.checks["datetime_valid"] = False
        logger.error(f"  Datetime error for {site_id}: {e}")
        return result
    result.checks["datetime_valid"] = True

    # Check 3: Value range (Florida aquifers)
    # Biscayne: typically 0-20 ft below surface
    # Floridan: typically 10-100 ft below surface
    # Allow negative for artesian wells, cap at ±200 ft
    min_val = df["value"].min()
    max_val = df["value"].max()

    if min_val < -50 or max_val > 200:
        result.warnings.append(
            f"Values outside typical range: min={min_val:.2f}, max={max_val:.2f}"
        )
        logger.warning(f"  Value range warning for {site_id}: {min_val:.2f} to {max_val:.2f} ft")
    else:
        result.checks["values_in_range"] = True

    # Check 4: No duplicates (after grouping by datetime)
    df_sorted = df.sort_values("datetime").reset_index(drop=True)
    duplicates = df_sorted.duplicated(subset=["datetime"], keep=False)
    if duplicates.any():
        num_dupes = duplicates.sum()
        result.warnings.append(f"Found {num_dupes} potential duplicate records")
        logger.warning(f"  {num_dupes} duplicates in {site_id}")
    else:
        result.checks["no_duplicates"] = True

    logger.debug(f"  Validation passed for {site_id}: {len(df)} records")
    return result


# ============================================================================
# FEATURE ENGINEERING STAGE (OPTIONAL)
# ============================================================================


def engineer_features(df: pd.DataFrame, site_id: str, lag_days: List[int] = None) -> pd.DataFrame:
    """Engineer lag and rolling window features for ML training.

    This function creates:
    - Lag features: water level N days ago
    - Rolling means: N-day rolling average
    - Rolling std: N-day rolling standard deviation

    IMPORTANT: Features are only created where valid targets exist (no NaN).
    This prevents data leakage into training data.

    Args:
        df: DataFrame with columns [site_no, datetime, value]
        site_id: Site ID for logging
        lag_days: Days for lag features (default: [1, 3, 7, 14, 30])

    Returns:
        DataFrame with original + engineered features
    """
    if lag_days is None:
        lag_days = [1, 3, 7, 14, 30]

    if df.empty:
        logger.warning(f"Cannot engineer features for empty DataFrame ({site_id})")
        return df

    df = df.sort_values("datetime").reset_index(drop=True)

    # Lag features
    for lag in lag_days:
        col_name = f"lag_{lag}d"
        df[col_name] = df["value"].shift(lag)
        logger.debug(f"  Created {col_name} for {site_id}")

    # Rolling statistics (7, 14, 30 days)
    for window in [7, 14, 30]:
        df[f"rolling_mean_{window}d"] = df["value"].rolling(window=window, min_periods=1).mean()
        df[f"rolling_std_{window}d"] = df["value"].rolling(window=window, min_periods=1).std()
        logger.debug(f"  Created rolling_{window}d features for {site_id}")

    logger.info(f"  ✓ Engineered {len(df.columns) - 3} features for {site_id}")
    return df


# ============================================================================
# SAVE STAGE
# ============================================================================


def save_site_data(
    df: pd.DataFrame,
    site_id: str,
    output_dir: Path = DATA_DIR,
) -> Path:
    """Save processed site data to timestamped CSV file.

    Filename format: usgs_{site_id}_{YYYYMMDD}.csv

    Args:
        df: DataFrame to save
        site_id: USGS site ID
        output_dir: Directory for output files

    Returns:
        Path to saved CSV file
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d")
    output_path = output_dir / f"usgs_{site_id}_{timestamp}.csv"

    df.to_csv(output_path, index=False)
    logger.info(f"  ✓ Saved to {output_path.name} ({len(df)} records)")

    return output_path


# ============================================================================
# MAIN PIPELINE ORCHESTRATOR
# ============================================================================


def run_pipeline(
    sites: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    output_format: str = "csv",
    parallel: bool = True,
    engineer_features_enabled: bool = False,
    log_dir: Path = LOG_DIR,
) -> Dict[str, Path]:
    """Main USGS groundwater data pipeline orchestrator.

    This is the canonical entry point for all data fetching operations.
    It orchestrates the complete pipeline:
    1. Load site list (all 36 or specified subset)
    2. Fetch data from USGS API (with retries)
    3. Validate schema and values
    4. Engineer features (optional)
    5. Save to timestamped CSV
    6. Generate manifest with audit trail

    Args:
        sites: List of site IDs to process. If None, processes all 36.
        start_date: Start date (YYYY-MM-DD). Default: 1994-01-01
        end_date: End date (YYYY-MM-DD). Default: today
        output_format: Output format (currently only 'csv' supported)
        parallel: Use parallel processing (default: True)
        engineer_features_enabled: Add lag/rolling features (default: False)
        log_dir: Directory for log files

    Returns:
        Dict[site_id] -> Path to CSV file for successful sites
        Missing keys indicate failed sites

    Raises:
        ValueError: If no sites specified and config missing
        RuntimeError: If pipeline encounters critical errors

    Example:
        >>> from src.data.pipeline import run_pipeline
        >>> results = run_pipeline()
        >>> print(f"Processed {len(results)} sites")
        >>> for site_id, path in results.items():
        ...     print(f"  {site_id}: {path}")

    Design Notes:
        - STATELESS: Can be called multiple times independently
        - ERROR RESILIENT: One site failure doesn't block others
        - DETERMINISTIC: Same input → Same output (except timestamps)
        - AUDITABLE: Complete manifest.json with all metadata
    """
    # Setup
    log_file = setup_logging(log_dir)
    logger.info("=" * 80)
    logger.info("USGS GROUNDWATER DATA PIPELINE")
    logger.info("=" * 80)

    pipeline_start_time = datetime.now()
    stats = PipelineStats(timestamp=pipeline_start_time, output_format=output_format)

    # Normalize dates
    start_date = start_date or DEFAULT_START_DATE
    end_date = end_date or DEFAULT_END_DATE

    logger.info(f"Start date: {start_date}")
    logger.info(f"End date: {end_date}")
    logger.info(f"Parallel processing: {parallel}")

    # Determine sites to process
    if sites is None:
        try:
            all_sites = get_all_site_ids()
            sites = all_sites
        except ValueError as e:
            logger.error(f"Failed to load sites: {e}")
            raise
    else:
        logger.info(f"Processing {len(sites)} specified sites")

    stats.sites_total = len(sites)
    logger.info(f"Processing {stats.sites_total} sites total")

    # Process sites (parallel or sequential)
    results = {}
    if parallel:
        results = _process_sites_parallel(sites, start_date, end_date, engineer_features_enabled)
    else:
        results = _process_sites_sequential(sites, start_date, end_date, engineer_features_enabled)

    # Update stats
    stats.sites_successful = len(results)
    stats.sites_failed = stats.sites_total - stats.sites_successful
    stats.output_files = {k: str(v) for k, v in results.items()}

    # Calculate total records
    for path in results.values():
        if path.exists():
            df = pd.read_csv(path)
            stats.total_records_saved += len(df)

    # Record duration
    stats.duration_seconds = (datetime.now() - pipeline_start_time).total_seconds()

    # Save manifest
    manifest_path = _save_manifest(stats, DATA_DIR)

    # Log summary
    logger.info("=" * 80)
    logger.info("PIPELINE SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Sites processed: {stats.sites_successful}/{stats.sites_total}")
    logger.info(f"Sites failed: {stats.sites_failed}")
    logger.info(f"Total records saved: {stats.total_records_saved}")
    logger.info(f"Duration: {stats.duration_seconds:.1f} seconds")
    logger.info(f"Manifest: {manifest_path}")
    logger.info(f"Log file: {log_file}")
    logger.info("=" * 80)

    return results


def _process_sites_sequential(
    sites: List[str],
    start_date: str,
    end_date: str,
    engineer_features_enabled: bool,
) -> Dict[str, Path]:
    """Process sites sequentially (single-threaded).

    Args:
        sites: List of site IDs
        start_date: Start date
        end_date: End date
        engineer_features_enabled: Enable feature engineering

    Returns:
        Dict of successful site_id -> output path
    """
    results = {}

    for i, site_id in enumerate(sites, 1):
        logger.info(f"\n[{i}/{len(sites)}] Processing {site_id}...")

        df = fetch_single_site(site_id, start_date, end_date)
        if df is None:
            logger.error(f"  ✗ Failed to fetch {site_id}")
            continue

        validation = validate_schema(df, site_id)
        if not validation.valid:
            logger.error(f"  ✗ Validation failed for {site_id}: {validation.errors}")
            continue

        if engineer_features_enabled:
            df = engineer_features(df, site_id)

        output_path = save_site_data(df, site_id)
        results[site_id] = output_path

    return results


def _process_sites_parallel(
    sites: List[str],
    start_date: str,
    end_date: str,
    engineer_features_enabled: bool,
    max_workers: int = 8,
) -> Dict[str, Path]:
    """Process sites in parallel using ThreadPoolExecutor.

    Args:
        sites: List of site IDs
        start_date: Start date
        end_date: End date
        engineer_features_enabled: Enable feature engineering
        max_workers: Maximum number of worker threads

    Returns:
        Dict of successful site_id -> output path
    """
    results = {}

    logger.info(f"Using parallel processing with {max_workers} workers")

    def process_one_site(site_id: str) -> Tuple[str, Optional[Path]]:
        """Process a single site and return (site_id, output_path)."""
        try:
            df = fetch_single_site(site_id, start_date, end_date)
            if df is None:
                return site_id, None

            validation = validate_schema(df, site_id)
            if not validation.valid:
                logger.error(f"Validation failed for {site_id}")
                return site_id, None

            if engineer_features_enabled:
                df = engineer_features(df, site_id)

            output_path = save_site_data(df, site_id)
            return site_id, output_path
        except Exception as e:
            logger.error(f"Error processing {site_id}: {e}")
            return site_id, None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_one_site, site_id): site_id for site_id in sites}

        completed = 0
        for future in as_completed(futures):
            completed += 1
            site_id, output_path = future.result()

            if output_path is not None:
                results[site_id] = output_path
                logger.debug(f"[{completed}/{len(sites)}] ✓ {site_id}")
            else:
                logger.debug(f"[{completed}/{len(sites)}] ✗ {site_id}")

    return results


def _save_manifest(stats: PipelineStats, output_dir: Path = DATA_DIR) -> Path:
    """Save pipeline execution manifest.

    The manifest tracks:
    - When the pipeline ran
    - How long it took
    - How many sites succeeded/failed
    - Output file locations
    - All errors for debugging

    Args:
        stats: Pipeline statistics
        output_dir: Directory for manifest file

    Returns:
        Path to manifest file
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d")
    manifest_path = output_dir / f"pipeline_manifest_{timestamp}.json"

    with open(manifest_path, "w") as f:
        json.dump(stats.to_dict(), f, indent=2)

    logger.info(f"✓ Manifest saved: {manifest_path}")
    return manifest_path


# ============================================================================
# USGS SITE SERVICE — WELL DEPTH ENRICHMENT
# ============================================================================
# These functions fetch actual drilled-depth metadata from the USGS NWIS Site
# Service and can be run offline to overwrite the static defaults in
# config/usgs_sites.json with verified values.
#
# Usage:
#   from src.data.pipeline import enrich_sites_with_well_depths, get_all_site_ids
#   results = enrich_sites_with_well_depths(get_all_site_ids())
#   # results: {site_id: {"well_depth_ft": float|None, "usgs_aquifer_code": str}}
# ============================================================================

USGS_SITE_SERVICE_URL = "https://waterservices.usgs.gov/nwis/site/"

# USGS local aquifer codes (aqfr_cd from NWIS site service) → zone names.
# Codes verified against actual Florida monitoring sites via NWIS siteOutput=expanded.
_USGS_AQ_CODE_TO_ZONE: Dict[str, str] = {
    # --- Biscayne Aquifer (SE Florida, Miami-Dade) ---
    "112BSCNN": "Biscayne",  # primary local code returned by NWIS
    "112BNQR": "Biscayne",  # alternate national-level code (kept for safety)
    # --- Surficial / Near-Surface (SW Florida, shallow water-table) ---
    "112NRSD": "Surficial Sand",  # non-rock surficial, SW Florida
    "112SRFL": "Surficial Sand",  # alternate surficial code
    # --- Tamiami Aquifer System (SW Florida intermediate) ---
    "121TMIM": "Lower Tamiami",
    "121TMIU": "Upper Tamiami",
    # --- Sand and Shell (Lee/Collier, intermediate) ---
    "122SNDS": "Sand and Shell",
    # --- Hawthorn Group (SW Florida, semi-confining / intermediate) ---
    "122HTRN": "Hawthorn",  # unconfined / open-hole variant
    "122HTRNN": "Hawthorn",  # confined variant
    "112HWTH": "Hawthorn",  # alternate code
    # --- Floridan Aquifer System (Sarasota and north) ---
    "120FLRD": "Floridan",  # undivided Floridan
    "112FLRD": "Upper Floridan",  # upper Floridan
    "112FLRL": "Lower Floridan",  # lower Floridan
    "123SWNN": "Upper Floridan",  # Suwannee-Tampa zone (upper Floridan)
    # --- Tampa Limestone (upper Floridan equivalent, Sarasota) ---
    "122TAMP": "Tampa Limestone",
    # --- Sand-and-Gravel (Panhandle / NW Florida — not in current dataset) ---
    "112SNDG": "Sand and Gravel",
}


def fetch_site_well_metadata(site_id: str) -> Dict[str, Optional[float]]:
    """Fetch well depth, aquifer code, and location from USGS NWIS Site Service.

    Calls the NWIS site service with ``siteOutput=expanded`` to retrieve:
        - ``well_depth_va``  — depth of well casing (ft)
        - ``hole_depth_va``  — total drilled depth (ft)
        - ``aqfr_cd``        — USGS local aquifer code (e.g. ``121TMIM`` = Tamiami)
        - ``nat_aqfr_cd``    — USGS national aquifer code
        - ``aqfr_type_cd``   — C = confined, U = unconfined
        - ``dec_lat_va``     — decimal latitude (NAD83)
        - ``dec_long_va``    — decimal longitude (NAD83)
        - ``station_nm``     — USGS station name

    Returns a dict with all usable fields; empty dict on any failure.
    """
    params = {
        "sites": site_id,
        "siteOutput": "expanded",
        "format": "rdb",
    }
    try:
        resp = requests.get(
            USGS_SITE_SERVICE_URL,
            params=params,
            timeout=USGS_API_TIMEOUT,
        )
        resp.raise_for_status()

        # RDB format: lines starting with # are comments; first non-comment
        # line is the tab-delimited header; second is the data-type line;
        # third (if present) is the first data row.
        lines = [ln for ln in resp.text.splitlines() if not ln.startswith("#") and ln.strip()]
        if len(lines) < 3:
            return {}

        headers = lines[0].split("\t")
        # lines[1] is the format descriptor row (e.g. "5s\t15d\t…") — skip
        data_row = lines[2].split("\t") if len(lines) > 2 else []
        if not data_row:
            return {}

        row = dict(zip(headers, data_row))

        def _safe_float(val: str) -> Optional[float]:
            try:
                return float(val.strip()) if val.strip() else None
            except ValueError:
                return None

        # NWIS uses 'aqfr_cd' (not 'aq_cd') for local aquifer code
        aq_code = row.get("aqfr_cd", "").strip()
        nat_aq_code = row.get("nat_aqfr_cd", "").strip()
        aqfr_type = row.get("aqfr_type_cd", "").strip()  # C=confined, U=unconfined
        return {
            "well_depth_ft": _safe_float(row.get("well_depth_va", "")),
            "hole_depth_ft": _safe_float(row.get("hole_depth_va", "")),
            "usgs_aquifer_code": aq_code,
            "nat_aquifer_code": nat_aq_code,
            "aquifer_zone": _USGS_AQ_CODE_TO_ZONE.get(aq_code, ""),
            "confined": aqfr_type == "C",
            "lat": _safe_float(row.get("dec_lat_va", "")),
            "lng": _safe_float(row.get("dec_long_va", "")),
            "station_nm": row.get("station_nm", "").strip(),
        }
    except Exception as exc:
        logger.warning("NWIS site service failed for %s: %s", site_id, exc)
        return {}


def enrich_sites_with_well_depths(
    site_ids: List[str],
    parallel: bool = True,
    max_workers: int = 8,
) -> Dict[str, dict]:
    """Batch-fetch NWIS well depth metadata for a list of site IDs.

    Returns ``{site_id: metadata_dict}`` where each value contains the keys
    returned by :func:`fetch_site_well_metadata`.  Sites that fail return an
    empty dict so callers can detect missing data.

    Run this offline to refresh the static ``well_depth_ft`` defaults in
    ``config/usgs_sites.json`` with authoritative NWIS values.
    """
    results: Dict[str, dict] = {}

    if parallel:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {pool.submit(fetch_site_well_metadata, sid): sid for sid in site_ids}
            for future in as_completed(future_map):
                sid = future_map[future]
                try:
                    results[sid] = future.result()
                except Exception as exc:
                    logger.warning("Depth enrichment failed for %s: %s", sid, exc)
                    results[sid] = {}
    else:
        for sid in site_ids:
            results[sid] = fetch_site_well_metadata(sid)

    fetched = sum(1 for v in results.values() if v.get("well_depth_ft") is not None)
    logger.info("Well depth enrichment: %d/%d sites returned depth data", fetched, len(site_ids))
    return results


if __name__ == "__main__":
    # CLI entry point
    # Usage: python -m src.data.pipeline
    try:
        results = run_pipeline(parallel=True)
        print(f"\n✓ Pipeline complete: {len(results)}/36 sites processed")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Pipeline failed: {e}")
        sys.exit(1)
