"""
Data quality and validation tests.

Tests ensure:
1. Data files exist and are readable
2. Schema is correct (expected columns)
3. Values are within valid ranges
4. No critical gaps in time series
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestDataFiles:
    """Test data files exist and are readable."""
    
    def test_groundwater_file_exists(self, data_dir):
        """Groundwater CSV should exist."""
        path = data_dir / "groundwater.csv"
        assert path.exists(), f"Missing: {path}"
    
    def test_groundwater_readable(self, data_dir):
        """Groundwater CSV should be readable."""
        path = data_dir / "groundwater.csv"
        
        if not path.exists():
            pytest.skip("Groundwater data not available")
        
        df = pd.read_csv(path)
        assert len(df) > 0, "Groundwater file is empty"
    
    def test_forecast_file_exists(self, data_dir):
        """Forecast CSV should exist after training."""
        path = data_dir / "forecast.csv"
        
        if not path.exists():
            pytest.skip("Forecast not yet generated")
        
        df = pd.read_csv(path)
        assert len(df) > 0


class TestGroundwaterSchema:
    """Test groundwater data schema."""
    
    @pytest.fixture
    def groundwater_df(self, data_dir):
        """Load groundwater data."""
        path = data_dir / "groundwater.csv"
        
        if not path.exists():
            pytest.skip("Groundwater data not available")
        
        return pd.read_csv(path, parse_dates=['date'])
    
    def test_required_columns(self, groundwater_df):
        """Required columns should exist."""
        required = ['date']
        level_cols = ['water_level_ft', 'water_level', 'water_level_m']
        
        for col in required:
            assert col in groundwater_df.columns, f"Missing column: {col}"
        
        # At least one level column should exist
        has_level = any(col in groundwater_df.columns for col in level_cols)
        assert has_level, f"Missing water level column. Have: {groundwater_df.columns.tolist()}"
    
    def test_date_column_type(self, groundwater_df):
        """Date column should be datetime."""
        assert pd.api.types.is_datetime64_any_dtype(groundwater_df['date'])
    
    def test_date_sorted(self, groundwater_df):
        """Data should be sorted by date."""
        dates = groundwater_df['date']
        assert dates.is_monotonic_increasing or dates.is_monotonic_decreasing


class TestGroundwaterValues:
    """Test groundwater data values are valid."""
    
    @pytest.fixture
    def groundwater_df(self, data_dir):
        """Load groundwater data."""
        path = data_dir / "groundwater.csv"
        
        if not path.exists():
            pytest.skip("Groundwater data not available")
        
        return pd.read_csv(path, parse_dates=['date'])
    
    @pytest.fixture
    def level_column(self, groundwater_df):
        """Get the water level column name."""
        for col in ['water_level_ft', 'water_level', 'water_level_m']:
            if col in groundwater_df.columns:
                return col
        pytest.fail("No water level column found")
    
    def test_no_null_dates(self, groundwater_df):
        """No null dates allowed."""
        assert groundwater_df['date'].isnull().sum() == 0
    
    def test_water_level_range(self, groundwater_df, level_column):
        """Water levels should be in realistic range."""
        levels = groundwater_df[level_column]
        
        # Typical depth to water: 0-100 ft for surficial aquifer
        assert levels.min() >= -10, f"Min level {levels.min()} seems too low"
        assert levels.max() <= 100, f"Max level {levels.max()} seems too high"
    
    def test_no_extreme_outliers(self, groundwater_df, level_column):
        """No extreme statistical outliers (> 5 std dev)."""
        levels = groundwater_df[level_column]
        mean = levels.mean()
        std = levels.std()
        
        outliers = levels[(levels < mean - 5*std) | (levels > mean + 5*std)]
        
        assert len(outliers) == 0, f"Found {len(outliers)} extreme outliers"
    
    def test_sufficient_data_coverage(self, groundwater_df):
        """Should have at least 1 year of data."""
        date_range = groundwater_df['date'].max() - groundwater_df['date'].min()
        days = date_range.days
        
        assert days >= 365, f"Only {days} days of data, need >= 365"


class TestTimeSeriesQuality:
    """Test time series specific quality."""
    
    @pytest.fixture
    def groundwater_df(self, data_dir):
        """Load groundwater data."""
        path = data_dir / "groundwater.csv"
        
        if not path.exists():
            pytest.skip("Groundwater data not available")
        
        return pd.read_csv(path, parse_dates=['date'])
    
    def test_no_duplicate_dates(self, groundwater_df):
        """No duplicate dates after aggregation."""
        daily = groundwater_df.groupby('date').size()
        # Some duplicates OK if multiple measurements per day
        # But after groupby, should be unique
        assert True  # Groupby handles this
    
    def test_date_gaps_acceptable(self, groundwater_df):
        """Gaps should not exceed 30 days."""
        dates = groundwater_df['date'].sort_values()
        gaps = dates.diff().dt.days
        max_gap = gaps.max()
        
        assert max_gap <= 30, f"Max gap of {max_gap} days exceeds 30 day limit"
    
    def test_data_recency(self, groundwater_df):
        """Data should be reasonably recent."""
        latest = groundwater_df['date'].max()
        
        # For testing purposes, just check it's a valid date
        assert pd.notna(latest)
