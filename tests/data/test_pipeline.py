"""
Comprehensive tests for src/data/pipeline.py

Test Coverage:
- Unit tests for individual pipeline stages (fetch, validate, engineer, save)
- Integration tests for complete pipeline execution
- Edge case handling
- Error resilience
- Data quality validation

Running Tests:
    pytest tests/data/test_pipeline.py -v
    pytest tests/data/test_pipeline.py -v --tb=short
    pytest tests/data/test_pipeline.py::TestPipelineOrchestration -v

Test Philosophy (per ENGINEERING_STANDARDS.md):
- Never modify tests to pass; fix the implementation
- Understand why tests fail
- Document what was learned
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest
import requests

# Setup imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.pipeline import (
    ValidationResult,
    PipelineStats,
    engineer_features,
    fetch_single_site,
    get_all_site_ids,
    run_pipeline,
    save_site_data,
    validate_schema,
)

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def sample_usgs_response():
    """Mock USGS API response for a single site."""
    return {
        "value": {
            "timeSeries": [
                {
                    "sourceInfo": {"siteName": "Test Site"},
                    "values": [
                        {
                            "value": [
                                {"dateTime": "2023-01-01T00:00:00", "value": "15.2"},
                                {"dateTime": "2023-01-02T00:00:00", "value": "15.5"},
                                {"dateTime": "2023-01-03T00:00:00", "value": "15.1"},
                                {"dateTime": "2023-01-04T00:00:00", "value": "15.8"},
                                {"dateTime": "2023-01-05T00:00:00", "value": "15.3"},
                            ]
                        }
                    ],
                }
            ]
        }
    }


@pytest.fixture
def sample_valid_dataframe():
    """Sample valid groundwater DataFrame."""
    return pd.DataFrame(
        {
            "site_no": ["251241080385301"] * 5,
            "datetime": pd.date_range("2023-01-01", periods=5),
            "value": [15.2, 15.5, 15.1, 15.8, 15.3],
        }
    )


@pytest.fixture
def sample_invalid_dataframe():
    """Sample invalid groundwater DataFrame (missing columns)."""
    return pd.DataFrame(
        {
            "site_id": ["251241080385301"] * 5,  # Wrong column name
            "date": [1, 2, 3, 4, 5],  # Not datetime
        }
    )


@pytest.fixture
def temp_data_dir(tmp_path):
    """Temporary directory for output files."""
    return tmp_path / "data"


# ============================================================================
# UNIT TESTS: Individual Stages
# ============================================================================


class TestFetchSingleSite:
    """Test the fetch_single_site() function."""

    @patch("src.data.pipeline.requests.get")
    def test_successful_fetch_with_parameter_72019(
        self, mock_get, sample_usgs_response
    ):
        """Fetch should succeed with parameter code 72019."""
        mock_response = Mock()
        mock_response.json.return_value = sample_usgs_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        df = fetch_single_site("251241080385301", "2023-01-01", "2023-12-31")

        assert df is not None
        assert len(df) == 5
        assert list(df.columns) == ["site_no", "datetime", "value"]
        assert df["site_no"].iloc[0] == "251241080385301"

    @patch("src.data.pipeline.requests.get")
    def test_fetch_handles_missing_values(self, mock_get):
        """Fetch should filter out USGS missing value sentinel (-999999)."""
        response_with_missing = {
            "value": {
                "timeSeries": [
                    {
                        "sourceInfo": {"siteName": "Test Site"},
                        "values": [
                            {
                                "value": [
                                    {
                                        "dateTime": "2023-01-01T00:00:00",
                                        "value": "15.2",
                                    },
                                    {
                                        "dateTime": "2023-01-02T00:00:00",
                                        "value": "-999999",
                                    },
                                    {
                                        "dateTime": "2023-01-03T00:00:00",
                                        "value": "15.1",
                                    },
                                ]
                            }
                        ],
                    }
                ]
            }
        }

        mock_response = Mock()
        mock_response.json.return_value = response_with_missing
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        df = fetch_single_site("251241080385301")

        # Should only have 2 records (missing value filtered out)
        assert len(df) == 2
        assert all(df["value"] > -999)

    @patch("src.data.pipeline.requests.get")
    def test_fetch_returns_none_on_no_data(self, mock_get):
        """Fetch should return None if no data found."""
        empty_response = {"value": {"timeSeries": []}}

        mock_response = Mock()
        mock_response.json.return_value = empty_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        df = fetch_single_site("999999999999999")

        assert df is None

    @patch("src.data.pipeline.requests.get")
    def test_fetch_retries_on_error(self, mock_get):
        """Fetch should retry on network errors before giving up."""
        # Fail once on each parameter code, then succeed on second try
        mock_response = Mock()
        mock_response.json.return_value = {
            "value": {
                "timeSeries": [
                    {
                        "values": [
                            {
                                "value": [
                                    {"value": "15.2", "dateTime": "2023-01-01T00:00:00"}
                                ]
                            }
                        ]
                    }
                ]
            }
        }
        mock_response.raise_for_status.return_value = None

        # Pattern: Fail first attempt, succeed on second for first parameter code
        mock_get.side_effect = [
            requests.RequestException("Network error"),  # param code 1, attempt 1
            mock_response,  # param code 1, attempt 2 - succeeds
        ]

        df = fetch_single_site("251241080385301")

        assert mock_get.call_count >= 2  # Should have retried
        assert df is not None  # Should have successfully fetched


class TestValidateSchema:
    """Test the validate_schema() function."""

    def test_valid_data_passes(self, sample_valid_dataframe):
        """Valid data should pass all checks."""
        result = validate_schema(sample_valid_dataframe, "251241080385301")

        assert result.valid is True
        assert result.record_count == 5
        assert result.checks["schema_valid"] is True
        assert result.checks["datetime_valid"] is True
        assert len(result.errors) == 0

    def test_missing_columns_detected(self, sample_invalid_dataframe):
        """Missing required columns should fail validation."""
        result = validate_schema(sample_invalid_dataframe, "251241080385301")

        assert result.valid is False
        assert "Missing columns" in result.errors[0]
        assert result.checks["schema_valid"] is False

    def test_invalid_datetime_detected(self):
        """Invalid datetime format should fail validation."""
        df = pd.DataFrame(
            {
                "site_no": ["251241080385301"] * 3,
                "datetime": ["2023-01-01", "invalid-date", "2023-01-03"],
                "value": [15.2, 15.5, 15.1],
            }
        )

        result = validate_schema(df, "251241080385301")

        assert result.valid is False
        assert result.checks["datetime_valid"] is False

    def test_value_range_warning(self):
        """Values outside normal range should generate warning."""
        df = pd.DataFrame(
            {
                "site_no": ["251241080385301"] * 3,
                "datetime": pd.date_range("2023-01-01", periods=3),
                "value": [-100, 0, 300],  # Outside typical range
            }
        )

        result = validate_schema(df, "251241080385301")

        assert result.valid is True  # Still valid, just warning
        assert any("range" in w.lower() for w in result.warnings)

    def test_duplicate_detection(self):
        """Duplicate datetimes should be warned."""
        df = pd.DataFrame(
            {
                "site_no": ["251241080385301"] * 3,
                "datetime": pd.to_datetime(
                    ["2023-01-01", "2023-01-01", "2023-01-02"]
                ),  # First two are duplicates
                "value": [15.2, 15.5, 15.3],
            }
        )

        result = validate_schema(df, "251241080385301")

        assert result.valid is True
        assert any("duplicate" in w.lower() for w in result.warnings)


class TestEngineerFeatures:
    """Test the engineer_features() function."""

    def test_lag_features_created(self, sample_valid_dataframe):
        """Lag features should be created correctly."""
        df_engineered = engineer_features(sample_valid_dataframe, "251241080385301")

        # Original 3 columns + 5 lag columns = 8 total
        assert len(df_engineered.columns) >= 8
        assert "lag_1d" in df_engineered.columns
        assert "lag_7d" in df_engineered.columns
        assert "lag_30d" in df_engineered.columns

    def test_rolling_features_created(self, sample_valid_dataframe):
        """Rolling window features should be created."""
        df_engineered = engineer_features(sample_valid_dataframe, "251241080385301")

        assert "rolling_mean_7d" in df_engineered.columns
        assert "rolling_mean_14d" in df_engineered.columns
        assert "rolling_std_7d" in df_engineered.columns

    def test_no_data_leakage(self, sample_valid_dataframe):
        """Early records should have NaN in lag features (no leakage)."""
        df_engineered = engineer_features(sample_valid_dataframe, "251241080385301")

        # First record shouldn't have lag_1d value
        assert pd.isna(df_engineered.iloc[0]["lag_1d"])

        # After sufficient lag, should have values
        assert not pd.isna(df_engineered.iloc[-1]["lag_1d"])

    def test_empty_dataframe_handled(self):
        """Engineer features should handle empty DataFrame gracefully."""
        df_empty = pd.DataFrame({"site_no": [], "datetime": [], "value": []})

        result = engineer_features(df_empty, "251241080385301")

        assert result.empty


class TestSaveSiteData:
    """Test the save_site_data() function."""

    def test_file_saved_with_timestamp(self, sample_valid_dataframe, temp_data_dir):
        """CSV should be saved with timestamp."""
        output_path = save_site_data(
            sample_valid_dataframe, "251241080385301", output_dir=temp_data_dir
        )

        assert output_path.exists()
        assert "usgs_251241080385301_" in output_path.name
        assert output_path.name.endswith(".csv")

    def test_saved_file_readable(self, sample_valid_dataframe, temp_data_dir):
        """Saved CSV should be readable and contain same data."""
        output_path = save_site_data(
            sample_valid_dataframe, "251241080385301", output_dir=temp_data_dir
        )

        df_loaded = pd.read_csv(output_path)

        assert len(df_loaded) == len(sample_valid_dataframe)
        assert list(df_loaded.columns) == list(sample_valid_dataframe.columns)

    def test_output_directory_created(self, sample_valid_dataframe, tmp_path):
        """Output directory should be created if it doesn't exist."""
        output_dir = tmp_path / "new" / "nested" / "path"
        assert not output_dir.exists()

        save_site_data(sample_valid_dataframe, "251241080385301", output_dir=output_dir)

        assert output_dir.exists()


# ============================================================================
# INTEGRATION TESTS: Complete Pipeline
# ============================================================================


class TestPipelineOrchestration:
    """Test the main run_pipeline() orchestrator function."""

    @patch("src.data.pipeline.fetch_single_site")
    def test_run_pipeline_all_sites(
        self, mock_fetch, sample_valid_dataframe, temp_data_dir
    ):
        """Pipeline should process all sites when sites=None."""
        mock_fetch.return_value = sample_valid_dataframe

        with patch("src.data.pipeline.DATA_DIR", temp_data_dir):
            with patch(
                "src.data.pipeline.get_all_site_ids", return_value=["251241080385301"]
            ):
                results = run_pipeline(parallel=False)

        assert len(results) >= 1
        assert "251241080385301" in results

    @patch("src.data.pipeline.fetch_single_site")
    def test_run_pipeline_specific_sites(
        self, mock_fetch, sample_valid_dataframe, temp_data_dir
    ):
        """Pipeline should process only specified sites."""
        mock_fetch.return_value = sample_valid_dataframe

        with patch("src.data.pipeline.DATA_DIR", temp_data_dir):
            results = run_pipeline(sites=["251241080385301"], parallel=False)

        assert len(results) == 1
        assert "251241080385301" in results

    @patch("src.data.pipeline.fetch_single_site")
    def test_run_pipeline_with_parallel(
        self, mock_fetch, sample_valid_dataframe, temp_data_dir
    ):
        """Pipeline should work with parallel processing."""
        mock_fetch.return_value = sample_valid_dataframe

        with patch("src.data.pipeline.DATA_DIR", temp_data_dir):
            results_parallel = run_pipeline(
                sites=["251241080385301", "251457080395802"], parallel=True
            )
            results_sequential = run_pipeline(
                sites=["251241080385301", "251457080395802"], parallel=False
            )

        # Should get same number of results regardless of parallelization
        assert len(results_parallel) == len(results_sequential)

    @patch("src.data.pipeline.fetch_single_site")
    def test_run_pipeline_error_resilience(
        self, mock_fetch, sample_valid_dataframe, temp_data_dir
    ):
        """Pipeline should continue even if one site fails."""
        # First site succeeds, second fails
        mock_fetch.side_effect = [sample_valid_dataframe, None]

        with patch("src.data.pipeline.DATA_DIR", temp_data_dir):
            results = run_pipeline(
                sites=["251241080385301", "999999999999999"], parallel=False
            )

        # Should still process the good site
        assert len(results) == 1
        assert "251241080385301" in results

    @patch("src.data.pipeline.fetch_single_site")
    def test_run_pipeline_creates_manifest(
        self, mock_fetch, sample_valid_dataframe, temp_data_dir
    ):
        """Pipeline should create manifest.json with execution details."""
        mock_fetch.return_value = sample_valid_dataframe

        with patch("src.data.pipeline.DATA_DIR", temp_data_dir):
            run_pipeline(sites=["251241080385301"], parallel=False)

        # Check manifest exists
        manifests = list(temp_data_dir.glob("pipeline_manifest_*.json"))
        assert len(manifests) >= 1

        # Verify manifest contents
        with open(manifests[0], "r") as f:
            manifest = json.load(f)

        assert manifest["sites_total"] == 1
        assert manifest["sites_successful"] == 1
        assert "output_files" in manifest


class TestGetAllSiteIds:
    """Test the get_all_site_ids() function."""

    def test_loads_all_36_sites(self):
        """Should load all 36 configured sites."""
        site_ids = get_all_site_ids()

        assert len(site_ids) == 36

    def test_site_ids_are_valid(self):
        """All site IDs should be 15-digit strings."""
        site_ids = get_all_site_ids()

        for site_id in site_ids:
            assert len(site_id) == 15
            assert site_id.isdigit()

    def test_no_duplicates(self):
        """Site ID list should have no duplicates."""
        site_ids = get_all_site_ids()

        assert len(site_ids) == len(set(site_ids))


class TestValidationResult:
    """Test the ValidationResult dataclass."""

    def test_creation_and_fields(self):
        """ValidationResult should initialize with proper defaults."""
        result = ValidationResult(
            site_id="251241080385301", valid=True, record_count=100
        )

        assert result.site_id == "251241080385301"
        assert result.valid is True
        assert result.record_count == 100
        assert isinstance(result.errors, list)
        assert isinstance(result.checks, dict)


class TestPipelineStats:
    """Test the PipelineStats dataclass."""

    def test_to_dict_serializable(self):
        """PipelineStats should convert to JSON-serializable dict."""
        from datetime import datetime

        stats = PipelineStats(
            timestamp=datetime.now(), sites_total=36, sites_successful=36
        )

        dict_repr = stats.to_dict()

        assert isinstance(dict_repr, dict)
        assert "timestamp" in dict_repr
        assert dict_repr["sites_total"] == 36
        assert dict_repr["sites_successful"] == 36

        # Should be JSON serializable
        json_str = json.dumps(dict_repr)
        assert isinstance(json_str, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
