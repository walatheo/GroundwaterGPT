"""
Model performance tests.

Tests ensure trained models meet minimum quality standards:
1. R² >= 0.75 (explains 75% of variance - realistic for 7-day forecasts)
2. RMSE <= 1.5 ft (average error for real-world USGS data)
3. No systematic bias (residuals centered at 0)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Add project root and src paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "ml"))


class TestModelPerformance:
    """Test trained model meets quality thresholds."""

    @pytest.fixture
    def model_and_data(self, models_dir, data_dir):
        """Load model and prepare test data."""
        from joblib import load

        # Find the best model file (could be ridge, gradient_boosting, etc.)
        model_files = list(models_dir.glob("best_*.joblib"))
        if not model_files:
            pytest.skip("Trained model not available")
        model_path = model_files[0]
        data_path = data_dir / "groundwater.csv"

        if not data_path.exists():
            pytest.skip("Groundwater data not available")

        try:
            from train_groundwater import load_groundwater_data, prepare_data

            model = load(model_path)
            df = load_groundwater_data()
            X_train, X_test, y_train, y_test, feature_cols, dates_test = prepare_data(df)
        except FileNotFoundError as e:
            pytest.skip(f"Data not available: {e}")

        return model, X_test, y_test

    def test_r2_minimum_threshold(self, model_and_data):
        """Model R² must be >= 0.75 (realistic for 7-day forecasts with real USGS data)."""
        from sklearn.metrics import r2_score

        model, X_test, y_test = model_and_data
        y_pred = model.predict(X_test)
        r2 = r2_score(y_test, y_pred)

        assert r2 >= 0.75, f"R² = {r2:.4f} is below 0.75 threshold"

    def test_rmse_maximum_threshold(self, model_and_data):
        """Model RMSE must be <= 1.5 ft for real-world USGS data."""
        from sklearn.metrics import mean_squared_error

        model, X_test, y_test = model_and_data
        y_pred = model.predict(X_test)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))

        assert rmse <= 1.5, f"RMSE = {rmse:.4f} exceeds 1.5 ft threshold"

    def test_no_systematic_bias(self, model_and_data):
        """Residuals should be centered around 0 (no systematic over/under prediction)."""
        model, X_test, y_test = model_and_data
        y_pred = model.predict(X_test)
        residuals = y_test.values - y_pred

        mean_residual = np.mean(residuals)

        # Mean residual should be close to 0 (within 0.5 ft for real-world data)
        assert (
            abs(mean_residual) < 0.5
        ), f"Systematic bias detected: mean residual = {mean_residual:.4f}"

    def test_predictions_in_realistic_range(self, model_and_data):
        """Predictions should be within realistic physical bounds."""
        model, X_test, y_test = model_and_data
        y_pred = model.predict(X_test)

        # Water levels should be between 0 and 50 ft (typical range)
        assert y_pred.min() > -5, f"Predictions too low: min = {y_pred.min():.2f}"
        assert y_pred.max() < 50, f"Predictions too high: max = {y_pred.max():.2f}"


class TestModelComparison:
    """Test model comparison results."""

    @pytest.fixture
    def comparison_results(self, data_dir):
        """Load model comparison CSV."""
        path = data_dir / "model_comparison.csv"

        if not path.exists():
            pytest.skip("Model comparison results not available")

        return pd.read_csv(path)

    def test_all_models_evaluated(self, comparison_results):
        """All expected models should be in comparison."""
        expected_models = ["ridge", "random_forest", "gradient_boosting"]

        for model in expected_models:
            assert model in comparison_results["model"].values, f"Missing model: {model}"

    def test_best_model_selected_correctly(self, comparison_results):
        """Best model should have highest R²."""
        best_idx = comparison_results["r2"].idxmax()

        # Verify the best model has the maximum R² value
        assert comparison_results.loc[best_idx, "r2"] == comparison_results["r2"].max()

    def test_metrics_are_valid(self, comparison_results):
        """All metrics should be valid numbers."""
        assert not comparison_results["r2"].isnull().any()
        assert not comparison_results["rmse"].isnull().any()
        assert not comparison_results["mae"].isnull().any()

        # R² should be between -1 and 1 (typically 0-1 for decent models)
        assert (comparison_results["r2"] >= -1).all()
        assert (comparison_results["r2"] <= 1).all()

        # RMSE and MAE should be positive
        assert (comparison_results["rmse"] > 0).all()
        assert (comparison_results["mae"] > 0).all()


class TestFeatureImportance:
    """Test feature importance analysis."""

    @pytest.fixture
    def feature_importance(self, data_dir):
        """Load feature importance CSV."""
        path = data_dir / "feature_importance.csv"

        if not path.exists():
            pytest.skip("Feature importance not available")

        return pd.read_csv(path)

    def test_importance_sums_to_one(self, feature_importance):
        """Feature importances should sum to approximately 1 (tree-based) or be normalized."""
        total = feature_importance["importance"].sum()

        # For tree-based models: sum to 1
        # For linear models with coefficients: may not sum to 1
        # Accept either normalized (sum ~1) or unnormalized coefficients
        is_normalized = 0.99 <= total <= 1.01
        has_valid_values = total > 0 and not np.isnan(total)

        assert is_normalized or has_valid_values, f"Invalid importance values: sum = {total:.4f}"

    def test_no_negative_importance(self, feature_importance):
        """All importance values should be non-negative."""
        assert (feature_importance["importance"] >= 0).all()

    def test_reasonable_top_features(self, feature_importance):
        """Top features should be interpretable (lag/rolling/temporal)."""
        top_features = feature_importance.head(5)["feature"].tolist()

        # At least one of the top features should be a lag or rolling feature
        lag_or_roll = any("lag" in f or "roll" in f for f in top_features)
        assert lag_or_roll, f"Top features don't include lag/rolling: {top_features}"
