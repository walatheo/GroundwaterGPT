"""
================================================================================
TEST_PIPELINE.PY - Quality Assurance Tests
================================================================================

Run: pytest test_pipeline.py -v

These tests ensure:
1. Data integrity - files load correctly, no NaN/infinite values
2. Feature engineering - lag/rolling features created properly
3. Model quality - R² above minimum threshold
4. Configuration validity - all paths exist, settings valid
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================

class TestConfiguration:
    """Test configuration settings are valid."""
    
    def test_config_imports(self):
        """Config module loads without error."""
        from config import (
            REGIONS, ACTIVE_REGION, TIME_CONFIG, 
            ERA5_VARIABLES, DATA_DIR, PLOTS_DIR, MODELS_DIR
        )
        assert REGIONS is not None
        assert ACTIVE_REGION in REGIONS
    
    def test_region_structure(self):
        """Active region has required fields."""
        from config import get_region
        region = get_region()
        required_fields = ["name", "lat", "lon", "area"]
        for field in required_fields:
            assert field in region, f"Region missing '{field}'"
    
    def test_time_config(self):
        """Time configuration is valid."""
        from config import TIME_CONFIG
        from datetime import datetime
        
        start = datetime.strptime(TIME_CONFIG["start_date"], "%Y-%m-%d")
        end = datetime.strptime(TIME_CONFIG["end_date"], "%Y-%m-%d")
        assert end > start, "End date must be after start date"
    
    def test_directories_exist(self):
        """Output directories can be created."""
        from config import DATA_DIR, PLOTS_DIR, MODELS_DIR
        
        # These should create if needed
        DATA_DIR.mkdir(exist_ok=True)
        PLOTS_DIR.mkdir(exist_ok=True)
        MODELS_DIR.mkdir(exist_ok=True)
        
        assert DATA_DIR.exists()
        assert PLOTS_DIR.exists()
        assert MODELS_DIR.exists()


# =============================================================================
# DATA LOADER TESTS
# =============================================================================

class TestDataLoaders:
    """Test data loading functions."""
    
    @pytest.fixture
    def climate_data(self):
        """Load climate data fixture."""
        from loaders import load_climate
        return load_climate(force_download=False)
    
    @pytest.fixture
    def groundwater_data(self):
        """Load groundwater data fixture."""
        from loaders import load_groundwater
        return load_groundwater(force_download=False)
    
    def test_climate_loads(self, climate_data):
        """Climate data loads successfully."""
        assert climate_data is not None
        assert len(climate_data) > 0
    
    def test_climate_columns(self, climate_data):
        """Climate data has required columns."""
        required = ["date", "temperature_c", "precipitation_mm"]
        for col in required:
            assert col in climate_data.columns, f"Missing column: {col}"
    
    def test_climate_no_nans(self, climate_data):
        """Climate data has no NaN values."""
        for col in ["temperature_c", "precipitation_mm"]:
            nan_count = climate_data[col].isna().sum()
            assert nan_count == 0, f"{col} has {nan_count} NaN values"
    
    def test_climate_reasonable_values(self, climate_data):
        """Climate values are in reasonable ranges."""
        # Temperature: -40°C to 60°C
        assert climate_data["temperature_c"].min() > -40
        assert climate_data["temperature_c"].max() < 60
        
        # Precipitation: 0 to 500mm per day
        assert climate_data["precipitation_mm"].min() >= 0
        assert climate_data["precipitation_mm"].max() < 500
    
    def test_groundwater_loads(self, groundwater_data):
        """Groundwater data loads successfully."""
        assert groundwater_data is not None
        assert len(groundwater_data) > 0
    
    def test_groundwater_columns(self, groundwater_data):
        """Groundwater data has required columns."""
        assert "date" in groundwater_data.columns
        assert "site_id" in groundwater_data.columns
        # Can be water_level_ft or water_level_m
        level_col = [c for c in groundwater_data.columns if "water_level" in c]
        assert len(level_col) > 0, "Missing water_level column"
    
    def test_groundwater_no_nans(self, groundwater_data):
        """Groundwater data has no NaN values in key columns."""
        level_col = [c for c in groundwater_data.columns if "water_level" in c][0]
        nan_count = groundwater_data[level_col].isna().sum()
        assert nan_count == 0, f"{level_col} has {nan_count} NaN values"
    
    def test_date_overlap(self, climate_data, groundwater_data):
        """Climate and groundwater data have overlapping dates."""
        climate_dates = set(climate_data["date"])
        gw_dates = set(groundwater_data["date"])
        overlap = climate_dates & gw_dates
        assert len(overlap) > 0, "No overlapping dates between datasets"


# =============================================================================
# FEATURE ENGINEERING TESTS
# =============================================================================

class TestFeatureEngineering:
    """Test feature preparation."""
    
    @pytest.fixture
    def prepared_data(self):
        """Prepare training data fixture."""
        from loaders import load_climate, load_groundwater
        from train import prepare_data
        
        climate = load_climate()
        gw = load_groundwater()
        return prepare_data(climate, gw)
    
    def test_prepare_data_returns_five(self, prepared_data):
        """prepare_data returns 5 elements."""
        assert len(prepared_data) == 5
    
    def test_train_test_shapes(self, prepared_data):
        """Train and test sets have correct shapes."""
        X_train, X_test, y_train, y_test, features = prepared_data
        
        # Rows match
        assert len(X_train) == len(y_train)
        assert len(X_test) == len(y_test)
        
        # Columns match feature count
        assert X_train.shape[1] == len(features)
        assert X_test.shape[1] == len(features)
    
    def test_no_data_leakage(self, prepared_data):
        """Test set dates come after training dates (no leakage)."""
        X_train, X_test, y_train, y_test, features = prepared_data
        
        # Since we use shuffle=False, last training idx < first test idx
        assert y_train.index.max() < y_test.index.min()
    
    def test_lag_features_exist(self, prepared_data):
        """Lag features are created."""
        X_train, _, _, _, features = prepared_data
        lag_features = [f for f in features if "_lag" in f]
        assert len(lag_features) > 0, "No lag features created"
    
    def test_rolling_features_exist(self, prepared_data):
        """Rolling features are created."""
        X_train, _, _, _, features = prepared_data
        roll_features = [f for f in features if "_roll" in f]
        assert len(roll_features) > 0, "No rolling features created"
    
    def test_cyclical_features_exist(self, prepared_data):
        """Cyclical time features are created."""
        X_train, _, _, _, features = prepared_data
        assert "month_sin" in features or "day_sin" in features
        assert "month_cos" in features or "day_cos" in features
    
    def test_no_infinite_values(self, prepared_data):
        """No infinite values in training data."""
        X_train, X_test, y_train, y_test, _ = prepared_data
        
        assert not np.isinf(X_train.values).any(), "X_train has infinite values"
        assert not np.isinf(X_test.values).any(), "X_test has infinite values"


# =============================================================================
# MODEL TRAINING TESTS
# =============================================================================

class TestModelTraining:
    """Test model training and evaluation."""
    
    @pytest.fixture
    def trained_model(self):
        """Train a model fixture."""
        from loaders import load_climate, load_groundwater
        from train import prepare_data, train_model
        
        climate = load_climate()
        gw = load_groundwater()
        X_train, X_test, y_train, y_test, features = prepare_data(climate, gw)
        
        model = train_model(X_train, y_train, "ridge")
        return model, X_train, X_test, y_train, y_test, features
    
    def test_ridge_trains(self, trained_model):
        """Ridge model trains successfully."""
        model, _, _, _, _, _ = trained_model
        assert model is not None
    
    def test_model_predicts(self, trained_model):
        """Model produces predictions."""
        model, _, X_test, _, _, _ = trained_model
        predictions = model.predict(X_test)
        assert len(predictions) == len(X_test)
    
    def test_model_r2_threshold(self, trained_model):
        """Model achieves minimum R² threshold."""
        from sklearn.metrics import r2_score
        
        model, _, X_test, _, y_test, _ = trained_model
        predictions = model.predict(X_test)
        r2 = r2_score(y_test, predictions)
        
        # Ridge should achieve at least R² > 0.5 on this data
        assert r2 > 0.5, f"R² ({r2:.4f}) below minimum threshold (0.5)"
    
    def test_predictions_reasonable(self, trained_model):
        """Predictions are in reasonable range."""
        model, _, X_test, _, y_test, _ = trained_model
        predictions = model.predict(X_test)
        
        # Predictions should be within 2x the actual range
        actual_min, actual_max = y_test.min(), y_test.max()
        actual_range = actual_max - actual_min
        
        assert predictions.min() > actual_min - actual_range
        assert predictions.max() < actual_max + actual_range
    
    def test_feature_importance_works(self, trained_model):
        """Feature importance can be extracted."""
        from train import get_feature_importance
        
        model, _, _, _, _, features = trained_model
        importance = get_feature_importance(model, features)
        
        assert importance is not None
        assert len(importance) == len(features)
        assert "feature" in importance.columns
        assert "importance" in importance.columns


# =============================================================================
# VISUALIZATION TESTS
# =============================================================================

class TestVisualization:
    """Test visualization functions."""
    
    def test_plots_created(self):
        """Visualization creates plot files."""
        from config import PLOTS_DIR
        from loaders import load_climate, load_groundwater
        from visualize import plot_all
        
        climate = load_climate()
        gw = load_groundwater()
        plot_all(climate, gw)
        
        expected_plots = ["climate.png", "groundwater.png", "correlation.png"]
        for plot in expected_plots:
            assert (PLOTS_DIR / plot).exists(), f"Missing plot: {plot}"


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """End-to-end integration tests."""
    
    def test_full_pipeline(self):
        """Full pipeline runs without error."""
        from loaders import load_climate, load_groundwater
        from visualize import plot_all
        from train import prepare_data, compare_models
        
        # Load
        climate = load_climate()
        gw = load_groundwater()
        
        # Visualize
        plot_all(climate, gw)
        
        # Train
        X_train, X_test, y_train, y_test, features = prepare_data(climate, gw)
        best_model, results = compare_models(X_train, y_train, X_test, y_test, features)
        
        # Verify outputs
        assert best_model is not None
        assert len(results) == 3  # 3 models compared
    
    def test_model_persistence(self):
        """Model can be saved and loaded."""
        from config import MODELS_DIR
        from train import load_best_model
        
        # Should have a saved model from previous tests
        model_files = list(MODELS_DIR.glob("best_*.joblib"))
        assert len(model_files) > 0, "No saved model found"
        
        # Load it
        model = load_best_model()
        assert model is not None


# =============================================================================
# DATA QUALITY TESTS
# =============================================================================

class TestDataQuality:
    """Statistical data quality tests."""
    
    @pytest.fixture
    def climate_data(self):
        from loaders import load_climate
        return load_climate()
    
    @pytest.fixture
    def groundwater_data(self):
        from loaders import load_groundwater
        return load_groundwater()
    
    def test_sufficient_data(self, climate_data, groundwater_data):
        """Have enough data for meaningful analysis."""
        assert len(climate_data) >= 100, "Not enough climate data"
        assert len(groundwater_data) >= 100, "Not enough groundwater data"
    
    def test_no_duplicate_dates(self, climate_data):
        """No duplicate dates in climate data."""
        duplicate_count = climate_data["date"].duplicated().sum()
        assert duplicate_count == 0, f"{duplicate_count} duplicate dates"
    
    def test_data_continuity(self, climate_data):
        """Data has no large gaps."""
        dates = pd.to_datetime(climate_data["date"]).sort_values()
        gaps = dates.diff().dt.days.dropna()
        max_gap = gaps.max()
        assert max_gap <= 7, f"Max gap of {max_gap} days exceeds threshold"
    
    def test_precipitation_physical(self, climate_data):
        """Precipitation values are physically possible."""
        # World record daily rainfall is about 1825mm
        assert climate_data["precipitation_mm"].max() < 2000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
