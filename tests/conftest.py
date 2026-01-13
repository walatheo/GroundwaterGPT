"""
Pytest configuration and shared fixtures.

This module provides common test fixtures used across all test modules.
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta


# =============================================================================
# PATH FIXTURES
# =============================================================================

@pytest.fixture
def project_root():
    """Return project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def data_dir(project_root):
    """Return data directory path."""
    return project_root / "data"


@pytest.fixture
def models_dir(project_root):
    """Return models directory path."""
    return project_root / "models"


# =============================================================================
# DATA FIXTURES
# =============================================================================

@pytest.fixture
def sample_groundwater_data():
    """
    Generate sample groundwater data for testing.
    
    Creates 365 days of synthetic but realistic groundwater levels
    with seasonal patterns and random noise.
    """
    np.random.seed(42)
    
    dates = pd.date_range('2023-01-01', periods=365, freq='D')
    
    # Create realistic seasonal pattern
    day_of_year = np.arange(365)
    seasonal = 2 * np.sin(2 * np.pi * day_of_year / 365)  # ±2 ft seasonal swing
    trend = -0.002 * day_of_year  # Slight declining trend
    noise = np.random.normal(0, 0.3, 365)  # Random noise
    
    water_level = 5.0 + seasonal + trend + noise  # Base level ~5 ft
    
    return pd.DataFrame({
        'date': dates,
        'water_level': water_level
    })


@pytest.fixture
def sample_features(sample_groundwater_data):
    """Generate sample feature data from groundwater data."""
    from train_groundwater import create_features
    return create_features(sample_groundwater_data)


@pytest.fixture
def minimal_data():
    """Minimal valid dataset for quick tests."""
    return pd.DataFrame({
        'date': pd.date_range('2023-01-01', periods=100, freq='D'),
        'water_level': np.random.normal(5, 1, 100)
    })


# =============================================================================
# MODEL FIXTURES
# =============================================================================

@pytest.fixture
def trained_model(models_dir):
    """
    Load trained model if available, otherwise skip test.
    """
    model_path = models_dir / "best_gradient_boosting.joblib"
    
    if not model_path.exists():
        pytest.skip("Trained model not available")
    
    from joblib import load
    return load(model_path)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def assert_no_nan(df: pd.DataFrame, message: str = ""):
    """Assert DataFrame has no NaN values."""
    nan_cols = df.columns[df.isnull().any()].tolist()
    assert len(nan_cols) == 0, f"NaN values in columns: {nan_cols}. {message}"


def assert_date_continuous(dates: pd.Series, max_gap_days: int = 1):
    """Assert dates are continuous with no gaps > max_gap_days."""
    gaps = dates.diff().dt.days
    large_gaps = gaps[gaps > max_gap_days]
    assert len(large_gaps) == 0, f"Found {len(large_gaps)} gaps > {max_gap_days} days"
