"""
================================================================================
TRAIN_GROUNDWATER.PY - Groundwater-Only Model Training
================================================================================

Predicts future groundwater levels using ONLY historical groundwater data.
No climate data required.

USAGE:
    python train_groundwater.py

Features Used (all derived from groundwater time series):
- Temporal: day of year (cyclical), month (cyclical)
- Lag features: past water levels (1, 3, 7, 14, 30 days ago)
- Rolling statistics: moving averages and std (7, 14, 30 day windows)
- Trend: difference from previous day, week, month
"""

import warnings
from pathlib import Path
from typing import Any, Optional, Tuple

import joblib
import numpy as np
import pandas as pd

# Configuration
DATA_DIR = Path(__file__).parent / "data"
MODELS_DIR = Path(__file__).parent / "models"
PLOTS_DIR = Path(__file__).parent / "plots"

MODELS_DIR.mkdir(exist_ok=True)
PLOTS_DIR.mkdir(exist_ok=True)

# Model configuration
FORECAST_HORIZON = 7  # Predict 7 days ahead (more realistic/useful)
LAG_DAYS = [7, 14, 21, 30, 60]  # Only use data from 7+ days ago
ROLLING_WINDOWS = [7, 14, 30]
TEST_SIZE = 0.2


def load_groundwater_data() -> pd.DataFrame:
    """Load groundwater data from CSV."""
    gw_file = DATA_DIR / "groundwater.csv"

    if not gw_file.exists():
        raise FileNotFoundError(f"Groundwater data not found: {gw_file}")

    df = pd.read_csv(gw_file, parse_dates=["date"])

    # Determine level column
    if "water_level_ft" in df.columns:
        level_col = "water_level_ft"
    else:
        level_col = "water_level_m"

    # Aggregate to daily if needed
    daily = df.groupby("date")[level_col].mean().reset_index()
    daily.columns = ["date", "water_level"]
    daily = daily.sort_values("date").reset_index(drop=True)

    print(f"Loaded {len(daily)} days of groundwater data")
    print(f"  Period: {daily['date'].min().date()} to {daily['date'].max().date()}")
    print(
        f"  Water level range: {daily['water_level'].min():.2f} to {daily['water_level'].max():.2f} ft"
    )

    return daily


def create_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create time-series features from groundwater data only.

    IMPORTANT: All features are shifted by FORECAST_HORIZON days to prevent
    data leakage. This ensures we're predicting 7 days ahead, not next day.

    Feature Categories:
    1. Temporal (cyclical encoding) - based on target date
    2. Lag features (past values) - shifted by forecast horizon
    3. Rolling statistics (trends and variability) - shifted
    4. Change features (momentum) - shifted
    """
    data = df.copy()

    # === TEMPORAL FEATURES (Cyclical Encoding) ===
    # These are based on the TARGET date (what we're predicting for)
    data["month"] = data["date"].dt.month
    data["month_sin"] = np.sin(2 * np.pi * data["month"] / 12)
    data["month_cos"] = np.cos(2 * np.pi * data["month"] / 12)

    # Day of year - finer seasonal resolution
    data["day_of_year"] = data["date"].dt.dayofyear
    data["doy_sin"] = np.sin(2 * np.pi * data["day_of_year"] / 365)
    data["doy_cos"] = np.cos(2 * np.pi * data["day_of_year"] / 365)

    # === LAG FEATURES (Past Values) ===
    # All lags are relative to FORECAST_HORIZON days before target
    for lag in LAG_DAYS:
        # e.g., if predicting 7 days ahead, lag_7d means value from 7+lag days before target
        data[f"level_lag_{lag}d"] = data["water_level"].shift(FORECAST_HORIZON + lag)

    # === ROLLING STATISTICS ===
    # All rolling stats end FORECAST_HORIZON days before target
    for window in ROLLING_WINDOWS:
        base_shift = FORECAST_HORIZON
        data[f"level_roll_mean_{window}d"] = (
            data["water_level"].shift(base_shift).rolling(window).mean()
        )
        data[f"level_roll_std_{window}d"] = (
            data["water_level"].shift(base_shift).rolling(window).std()
        )
        data[f"level_roll_min_{window}d"] = (
            data["water_level"].shift(base_shift).rolling(window).min()
        )
        data[f"level_roll_max_{window}d"] = (
            data["water_level"].shift(base_shift).rolling(window).max()
        )

    # === CHANGE FEATURES (Momentum) ===
    # Changes computed from data available FORECAST_HORIZON days ago
    data["change_7d"] = data["water_level"].shift(FORECAST_HORIZON) - data["water_level"].shift(
        FORECAST_HORIZON + 7
    )
    data["change_14d"] = data["water_level"].shift(FORECAST_HORIZON) - data["water_level"].shift(
        FORECAST_HORIZON + 14
    )
    data["change_30d"] = data["water_level"].shift(FORECAST_HORIZON) - data["water_level"].shift(
        FORECAST_HORIZON + 30
    )

    # Drop rows with NaN (from lag/rolling operations)
    data = data.dropna()

    return data


def prepare_data(df: pd.DataFrame) -> Tuple:
    """
    Prepare train/test split for time series.

    IMPORTANT: No shuffling - maintains temporal order to prevent data leakage.
    """
    from sklearn.model_selection import train_test_split

    # Create features
    data = create_features(df)
    print(f"\nCreated features: {len(data)} samples after feature engineering")

    # Define feature columns (exclude date, month, day_of_year, target)
    exclude_cols = ["date", "water_level", "month", "day_of_year"]
    feature_cols = [c for c in data.columns if c not in exclude_cols]

    X = data[feature_cols]
    y = data["water_level"]
    dates = data["date"]

    # Time-series split - NO SHUFFLE
    split_idx = int(len(X) * (1 - TEST_SIZE))

    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    dates_train, dates_test = dates.iloc[:split_idx], dates.iloc[split_idx:]

    print(
        f"Train: {len(X_train)} samples ({dates_train.min().date()} to {dates_train.max().date()})"
    )
    print(f"Test:  {len(X_test)} samples ({dates_test.min().date()} to {dates_test.max().date()})")
    print(f"Features: {len(feature_cols)}")

    return X_train, X_test, y_train, y_test, feature_cols, dates_test


def train_model(X_train, y_train, model_type: str = "ridge") -> Any:
    """Train a model with tuned hyperparameters."""
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    models = {
        "ridge": Pipeline([("scaler", StandardScaler()), ("model", Ridge(alpha=1.0))]),
        "random_forest": Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "model",
                    RandomForestRegressor(
                        n_estimators=100,
                        max_depth=8,
                        min_samples_split=5,
                        min_samples_leaf=3,
                        max_features="sqrt",
                        n_jobs=-1,
                        random_state=42,
                    ),
                ),
            ]
        ),
        "gradient_boosting": Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "model",
                    GradientBoostingRegressor(
                        n_estimators=100,
                        max_depth=4,
                        learning_rate=0.1,
                        min_samples_split=5,
                        min_samples_leaf=3,
                        subsample=0.8,
                        random_state=42,
                    ),
                ),
            ]
        ),
    }

    model = models.get(model_type.lower())
    if model is None:
        raise ValueError(f"Unknown model: {model_type}")

    print(f"  Training {model_type}...", end=" ", flush=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model.fit(X_train, y_train)
    print("done")

    return model


def evaluate_model(model, X_test, y_test) -> dict:
    """Evaluate model performance."""
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    y_pred = model.predict(X_test)

    return {
        "r2": r2_score(y_test, y_pred),
        "rmse": np.sqrt(mean_squared_error(y_test, y_pred)),
        "mae": mean_absolute_error(y_test, y_pred),
        "predictions": y_pred,
    }


def get_feature_importance(model, feature_names: list) -> pd.DataFrame:
    """Extract feature importance from model."""
    try:
        if hasattr(model, "named_steps"):
            inner_model = model.named_steps["model"]
        else:
            inner_model = model

        if hasattr(inner_model, "feature_importances_"):
            importance = inner_model.feature_importances_
        elif hasattr(inner_model, "coef_"):
            importance = np.abs(inner_model.coef_)
        else:
            return pd.DataFrame()

        return pd.DataFrame({"feature": feature_names, "importance": importance}).sort_values(
            "importance", ascending=False
        )

    except Exception:
        return pd.DataFrame()


def compare_models(
    X_train, y_train, X_test, y_test, feature_names: list
) -> Tuple[Any, pd.DataFrame]:
    """Train and compare all models."""
    from sklearn.metrics import r2_score

    print("\n" + "=" * 60)
    print("MODEL COMPARISON (Groundwater-Only Features)")
    print("=" * 60)

    results = []
    models = {}

    for name in ["ridge", "random_forest", "gradient_boosting"]:
        model = train_model(X_train, y_train, name)
        models[name] = model

        metrics = evaluate_model(model, X_test, y_test)

        results.append(
            {
                "model": name,
                "r2": round(metrics["r2"], 4),
                "rmse": round(metrics["rmse"], 4),
                "mae": round(metrics["mae"], 4),
            }
        )

        print(
            f"    {name:20s} | R²: {metrics['r2']:.4f} | RMSE: {metrics['rmse']:.4f} | MAE: {metrics['mae']:.4f}"
        )

    results_df = pd.DataFrame(results)
    results_df.to_csv(DATA_DIR / "model_comparison.csv", index=False)

    # Select best model
    best_name = results_df.loc[results_df["r2"].idxmax(), "model"]
    best_model = models[best_name]

    print(f"\n✓ Best Model: {best_name} (R² = {results_df['r2'].max():.4f})")

    # Save best model
    model_path = MODELS_DIR / f"best_{best_name}.joblib"
    joblib.dump(best_model, model_path)
    print(f"✓ Model saved: {model_path.name}")

    # Feature importance
    importance = get_feature_importance(best_model, feature_names)
    if not importance.empty:
        importance.to_csv(DATA_DIR / "feature_importance.csv", index=False)
        print("\n📊 Top 10 Features:")
        for i, row in importance.head(10).iterrows():
            print(f"    {row['feature']:30s} {row['importance']:.4f}")

    return best_model, results_df


def plot_predictions(y_test, y_pred, dates_test, model_name: str):
    """Create prediction visualization."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(
        f'Groundwater Level Predictions - {model_name.replace("_", " ").title()}',
        fontsize=14,
        fontweight="bold",
    )

    # 1. Time series comparison
    ax1 = axes[0, 0]
    ax1.plot(dates_test, y_test, "b-", label="Actual", alpha=0.7, linewidth=1)
    ax1.plot(dates_test, y_pred, "r-", label="Predicted", alpha=0.7, linewidth=1)
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Water Level (ft)")
    ax1.set_title("Actual vs Predicted")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 2. Scatter plot
    ax2 = axes[0, 1]
    ax2.scatter(y_test, y_pred, alpha=0.5, s=20)
    min_val = min(y_test.min(), y_pred.min())
    max_val = max(y_test.max(), y_pred.max())
    ax2.plot([min_val, max_val], [min_val, max_val], "r--", label="Perfect Prediction")
    ax2.set_xlabel("Actual Water Level (ft)")
    ax2.set_ylabel("Predicted Water Level (ft)")
    ax2.set_title("Prediction Accuracy")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # 3. Residuals over time
    ax3 = axes[1, 0]
    residuals = y_test.values - y_pred
    ax3.plot(dates_test, residuals, "g-", alpha=0.7, linewidth=1)
    ax3.axhline(y=0, color="r", linestyle="--")
    ax3.set_xlabel("Date")
    ax3.set_ylabel("Residual (ft)")
    ax3.set_title("Prediction Errors Over Time")
    ax3.grid(True, alpha=0.3)

    # 4. Residual distribution
    ax4 = axes[1, 1]
    ax4.hist(residuals, bins=30, edgecolor="black", alpha=0.7)
    ax4.axvline(x=0, color="r", linestyle="--")
    ax4.set_xlabel("Residual (ft)")
    ax4.set_ylabel("Frequency")
    ax4.set_title(f"Error Distribution (Mean: {residuals.mean():.3f}, Std: {residuals.std():.3f})")
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "model_predictions.png", dpi=150, bbox_inches="tight")
    plt.close()

    print(f"✓ Predictions plot saved: plots/model_predictions.png")


def forecast_future(model, df: pd.DataFrame, feature_cols: list, days: int = 30) -> pd.DataFrame:
    """
    Forecast future groundwater levels.

    Uses iterative prediction: each day's prediction becomes
    input for the next day's prediction.
    """
    print(f"\n📈 Forecasting {days} days ahead...")

    # Start from the last known data
    data = create_features(df).copy()
    last_date = data["date"].max()

    forecasts = []
    current_data = data.copy()

    for i in range(days):
        next_date = last_date + pd.Timedelta(days=i + 1)

        # Get latest features
        latest = current_data.iloc[-1:][feature_cols]

        # Predict
        pred = model.predict(latest)[0]

        forecasts.append({"date": next_date, "predicted_level": pred})

        # Add prediction to data for next iteration
        new_row = pd.DataFrame({"date": [next_date], "water_level": [pred]})
        temp_df = pd.concat([df, new_row], ignore_index=True)
        current_data = create_features(temp_df)

    forecast_df = pd.DataFrame(forecasts)
    forecast_df.to_csv(DATA_DIR / "forecast.csv", index=False)
    print(f"✓ Forecast saved: data/forecast.csv")

    return forecast_df


def main():
    """Main training pipeline."""
    print("=" * 60)
    print("GROUNDWATER-ONLY MODEL TRAINING")
    print("=" * 60)

    # Load data
    df = load_groundwater_data()

    # Prepare data
    X_train, X_test, y_train, y_test, feature_cols, dates_test = prepare_data(df)

    # Compare models
    best_model, results_df = compare_models(X_train, y_train, X_test, y_test, feature_cols)

    # Get predictions for plotting
    metrics = evaluate_model(best_model, X_test, y_test)

    # Plot results
    best_name = results_df.loc[results_df["r2"].idxmax(), "model"]
    plot_predictions(y_test, metrics["predictions"], dates_test, best_name)

    # Generate 30-day forecast
    forecast = forecast_future(best_model, df, feature_cols, days=30)

    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)
    print(f"\n📊 30-Day Forecast Preview:")
    print(forecast.head(10).to_string(index=False))

    return best_model, results_df


if __name__ == "__main__":
    main()
