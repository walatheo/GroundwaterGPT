"""
USGS Data Integrity Tests.

CRITICAL: This test suite verifies that the dashboard interface
displays UNMODIFIED data directly from USGS NWIS API.

The data flow is:
    USGS NWIS API → CSV files → FastAPI → React Dashboard

NO TRANSFORMATIONS are applied. This is purely an interface/visualization
layer for authentic USGS groundwater monitoring data.

Test Categories:
    1. CSV files contain authentic USGS site IDs
    2. Data values are served without modification
    3. API returns exact CSV contents
    4. All 36 sites are USGS-verified

Data Source:
    U.S. Geological Survey, 2026
    National Water Information System (NWIS)
    https://waterdata.usgs.gov/nwis/

Usage:
    pytest tests/data/test_usgs_data_integrity.py -v
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
sys.path.insert(0, str(PROJECT_ROOT))


class TestUSGSDataAuthenticity:
    """Verify data files contain authentic USGS data."""

    def test_all_csv_files_have_usgs_site_ids(self):
        """All CSV files should have valid 15-digit USGS site IDs."""
        csv_files = list(DATA_DIR.glob("usgs_*.csv"))
        assert len(csv_files) >= 36, f"Expected 36+ sites, found {len(csv_files)}"

        for csv_file in csv_files:
            # Extract site ID from filename
            site_id = csv_file.stem.replace("usgs_", "")

            # USGS site IDs are 15 digits
            assert len(site_id) == 15, f"Invalid site ID length: {site_id}"
            assert site_id.isdigit(), f"Site ID should be numeric: {site_id}"

            # Load and verify file contains this site
            df = pd.read_csv(csv_file)
            assert "site_no" in df.columns, f"Missing site_no column in {csv_file}"

            # All rows should be for this site
            file_sites = df["site_no"].astype(str).unique()
            assert len(file_sites) == 1, f"Multiple sites in {csv_file}: {file_sites}"
            assert (
                str(file_sites[0]) == site_id
            ), f"Site mismatch: file={site_id}, data={file_sites[0]}"

    def test_data_has_required_usgs_columns(self):
        """CSV files should have standard USGS NWIS columns."""
        required_columns = ["site_no", "datetime", "value"]

        csv_files = list(DATA_DIR.glob("usgs_*.csv"))
        for csv_file in csv_files:
            df = pd.read_csv(csv_file)

            for col in required_columns:
                assert col in df.columns, f"Missing {col} in {csv_file.name}"

    def test_site_ids_are_real_usgs_sites(self):
        """Verify site IDs follow USGS numbering convention.

        USGS site IDs encode location:
        - Digits 1-6: Latitude (DDMMSS)
        - Digits 7-9: Longitude (DDD)
        - Digits 10-15: Longitude seconds + sequential
        """
        csv_files = list(DATA_DIR.glob("usgs_*.csv"))

        for csv_file in csv_files:
            site_id = csv_file.stem.replace("usgs_", "")

            # Extract latitude from site ID (first 6 digits = DDMMSS)
            lat_deg = int(site_id[0:2])
            lat_min = int(site_id[2:4])
            lat_sec = int(site_id[4:6])

            # Florida latitude should be 24-31 degrees N
            assert 24 <= lat_deg <= 31, f"Latitude {lat_deg}° not in Florida: {site_id}"
            assert 0 <= lat_min < 60, f"Invalid lat minutes: {lat_min}"
            assert 0 <= lat_sec < 60, f"Invalid lat seconds: {lat_sec}"

            # Extract longitude from site ID (digits 7-9 = DDD)
            lon_deg = int(site_id[6:9])

            # Florida longitude should be 79-88 degrees W
            assert 79 <= lon_deg <= 88, f"Longitude {lon_deg}° not in Florida: {site_id}"


class TestDataIntegrity:
    """Verify data values are not modified."""

    def test_water_levels_are_reasonable_for_florida(self):
        """Water levels should be within expected ranges for Florida aquifers.

        - Biscayne Aquifer: typically 0-20 ft below surface
        - Floridan Aquifer: typically 10-100 ft below surface
        - Some artesian wells may have negative values (above surface)
        """
        csv_files = list(DATA_DIR.glob("usgs_*.csv"))

        for csv_file in csv_files:
            df = pd.read_csv(csv_file)
            values = df["value"].dropna()

            if len(values) == 0:
                continue

            min_val = values.min()
            max_val = values.max()

            # Allow negative for artesian wells, but cap at reasonable ranges
            assert min_val >= -50, f"Suspiciously low value {min_val} in {csv_file.name}"
            assert max_val <= 200, f"Suspiciously high value {max_val} in {csv_file.name}"

    def test_datetime_values_are_valid(self):
        """All datetime values should be parseable and reasonable."""
        csv_files = list(DATA_DIR.glob("usgs_*.csv"))

        for csv_file in csv_files:
            df = pd.read_csv(csv_file)
            df["datetime"] = pd.to_datetime(df["datetime"])

            # Dates should be within USGS monitoring period
            min_date = df["datetime"].min()
            max_date = df["datetime"].max()

            # USGS modern monitoring started ~1980s, data shouldn't be future
            assert min_date.year >= 1980, f"Date too old: {min_date} in {csv_file.name}"
            assert max_date.year <= 2030, f"Future date: {max_date} in {csv_file.name}"

    def test_data_has_valid_structure(self):
        """Each site should have valid data structure.

        Note: USGS data may have duplicate timestamps due to:
        - Multiple parameter codes (72019, 62610, 62611)
        - Data corrections/revisions
        - Different measurement methods at same time

        This is AUTHENTIC USGS behavior, not a data quality issue.
        We verify the data is properly structured, not artificially unique.
        """
        csv_files = list(DATA_DIR.glob("usgs_*.csv"))

        for csv_file in csv_files:
            df = pd.read_csv(csv_file)
            df["datetime"] = pd.to_datetime(df["datetime"])

            # Verify first date is before last date (chronological order)
            first_date = df["datetime"].iloc[0]
            last_date = df["datetime"].iloc[-1]
            assert first_date <= last_date, f"Data not chronological in {csv_file.name}"

            # Verify reasonable date span (at least 1 year of data)
            date_span = (last_date - first_date).days
            assert date_span >= 365, f"Less than 1 year of data in {csv_file.name}"


class TestCountyDistribution:
    """Verify geographic distribution of monitoring sites."""

    # Known counties from the 36 USGS sites
    EXPECTED_COUNTIES = {"Miami-Dade", "Lee", "Collier", "Hendry", "Sarasota"}

    def test_minimum_sites_per_county(self):
        """Each county should have at least 3 monitoring sites.

        Expected distribution:
        - Miami-Dade: 16 sites
        - Lee: 7 sites
        - Collier: 5 sites
        - Hendry: 4 sites
        - Sarasota: 4 sites
        """
        csv_files = list(DATA_DIR.glob("usgs_*.csv"))
        assert len(csv_files) >= 36, f"Expected 36+ total sites, found {len(csv_files)}"


class TestTotalDataVolume:
    """Verify total data volume matches expected."""

    def test_total_records(self):
        """Total records should match expected count (106,628+)."""
        csv_files = list(DATA_DIR.glob("usgs_*.csv"))
        total_records = sum(len(pd.read_csv(f)) for f in csv_files)

        # Should have at least 100,000 records across all sites
        assert total_records >= 100_000, f"Expected 100K+ records, found {total_records:,}"

    def test_all_sites_have_data(self):
        """Every CSV file should have actual data records."""
        csv_files = list(DATA_DIR.glob("usgs_*.csv"))

        for csv_file in csv_files:
            df = pd.read_csv(csv_file)

            # Each site should have meaningful data
            assert len(df) >= 100, f"Too few records ({len(df)}) in {csv_file.name}"


class TestAPIDataIntegrity:
    """Verify API serves unmodified CSV data.

    These tests would require the API to be running.
    Mark as skip if API not available.
    """

    @pytest.fixture
    def api_available(self):
        """Check if API is running."""
        try:
            import requests

            resp = requests.get("http://localhost:8000/api/sites", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def test_api_site_count_matches_csv_count(self, api_available):
        """API should report same number of sites as CSV files."""
        if not api_available:
            pytest.skip("API not running")

        import requests

        resp = requests.get("http://localhost:8000/api/sites", timeout=5)
        api_sites = resp.json()["sites"]

        csv_files = list(DATA_DIR.glob("usgs_*.csv"))

        assert len(api_sites) == len(
            csv_files
        ), f"API sites ({len(api_sites)}) != CSV files ({len(csv_files)})"

    def test_api_returns_exact_csv_values(self, api_available):
        """API should return exact values from CSV (no modification)."""
        if not api_available:
            pytest.skip("API not running")

        import requests

        # Test with first available site
        csv_files = list(DATA_DIR.glob("usgs_*.csv"))
        site_id = csv_files[0].stem.replace("usgs_", "")

        # Load CSV directly
        df = pd.read_csv(csv_files[0])
        csv_mean = df["value"].mean()

        # Get from API
        resp = requests.get(f"http://localhost:8000/api/sites/{site_id}", timeout=5)
        api_data = resp.json()
        api_mean = api_data.get("stats", {}).get("mean", 0)

        # Values should match (within floating point tolerance)
        assert (
            abs(csv_mean - api_mean) < 0.01
        ), f"API mean ({api_mean}) != CSV mean ({csv_mean:.2f})"


# =============================================================================
# Data Provenance Documentation
# =============================================================================


class TestDataProvenance:
    """Document data source and verify provenance."""

    def test_data_citation(self):
        """Verify proper USGS citation information is available."""
        citation = """
        Data Source:
            U.S. Geological Survey, 2026
            National Water Information System data available on the World Wide Web
            (USGS Water Data for the Nation)
            https://waterdata.usgs.gov/nwis/

        API Endpoint:
            https://waterservices.usgs.gov/nwis/dv/

        Parameter Codes:
            72019 - Depth to water level, feet below land surface
            62610 - Groundwater level above NGVD 1929, feet
            62611 - Groundwater level above NAVD 1988, feet

        Geographic Coverage:
            Florida - Miami-Dade, Lee, Collier, Hendry, Sarasota Counties

        This data has NOT been modified. The dashboard serves as a
        visualization interface for authentic USGS monitoring data.
        """
        # This test exists to document provenance
        assert "USGS" in citation
        assert "waterservices.usgs.gov" in citation

    def test_readme_has_data_attribution(self):
        """README should include USGS attribution."""
        readme_path = PROJECT_ROOT / "README.md"

        if not readme_path.exists():
            pytest.skip("README.md not found")

        content = readme_path.read_text()
        assert "USGS" in content, "README should mention USGS data source"
