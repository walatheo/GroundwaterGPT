# GroundwaterGPT Development Guide

**Purpose:** Best practices and standards for developing a production-quality groundwater prediction and research platform.

**Core Goals:**
1. Accurate groundwater level modeling and trend analysis
2. Research-ready platform with extensibility for future studies
3. Clean, maintainable, well-documented codebase

---

## 📋 Table of Contents

1. [Project Vision & Roadmap](#-project-vision--roadmap)
2. [Code Quality Standards](#-code-quality-standards)
3. [CI/CD Pipeline](#-cicd-pipeline)
4. [Data Engineering Best Practices](#-data-engineering-best-practices)
5. [Testing Strategy](#-testing-strategy)
6. [Documentation Standards](#-documentation-standards)
7. [Code Maintenance](#-code-maintenance)

---

## 🎯 Project Vision & Roadmap

### Mission Statement
Build a reliable, extensible platform for groundwater analysis that can:
- Model and predict groundwater levels with quantified uncertainty
- Visualize trends for stakeholders and researchers
- Serve as a foundation for academic research and addendums
- Integrate new data sources and methodologies over time

### Development Phases

| Phase | Focus | Status |
|-------|-------|--------|
| **1. Foundation** | Data pipeline, basic ML, dashboard | ✅ Complete |
| **2. Quality** | Testing, CI/CD, documentation | 🔄 Current |
| **3. Enhancement** | Multi-site, confidence intervals, API | 📋 Planned |
| **4. Research** | RAG integration, automated reports | 📋 Planned |
| **5. Production** | Web hosting, alerts, integrations | 📋 Planned |

---

## 🔧 Code Quality Standards

### Python Style Guide

```python
# Use type hints for all functions
def predict_groundwater(
    model: Pipeline,
    features: pd.DataFrame,
    horizon_days: int = 7
) -> np.ndarray:
    """
    Predict groundwater levels for given features.
    
    Args:
        model: Trained sklearn Pipeline
        features: DataFrame with required feature columns
        horizon_days: Prediction horizon (default 7)
    
    Returns:
        Array of predicted water levels in feet
    
    Raises:
        ValueError: If features missing required columns
    
    Example:
        >>> predictions = predict_groundwater(model, test_features)
        >>> print(f"Next 7 days: {predictions[:7]}")
    """
    # Implementation
    pass
```

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Files | `snake_case.py` | `train_groundwater.py` |
| Classes | `PascalCase` | `GroundwaterProcessor` |
| Functions | `snake_case` | `load_usgs_data()` |
| Constants | `UPPER_SNAKE` | `FORECAST_HORIZON` |
| Private | `_leading_underscore` | `_validate_dates()` |

### Code Organization

```
src/
├── data/           # Data loading and processing
│   ├── __init__.py
│   ├── usgs.py     # USGS API interactions
│   ├── processors.py
│   └── validators.py
├── models/         # ML model code
│   ├── __init__.py
│   ├── features.py # Feature engineering
│   ├── train.py    # Training logic
│   └── predict.py  # Inference logic
├── visualization/  # Plotting and dashboards
│   ├── __init__.py
│   └── dashboard.py
└── utils/          # Shared utilities
    ├── __init__.py
    ├── config.py
    └── logging.py
```

---

## 🚀 CI/CD Pipeline

### GitHub Actions Workflow

Create `.github/workflows/ci.yml`:

```yaml
name: CI Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov flake8 mypy
          
      - name: Lint with flake8
        run: flake8 . --max-line-length=100 --exclude=.venv
        
      - name: Type check with mypy
        run: mypy --ignore-missing-imports *.py
        
      - name: Run tests
        run: pytest tests/ -v --cov=. --cov-report=xml
        
      - name: Upload coverage
        uses: codecov/codecov-action@v3

  quality-gate:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - name: Check test coverage threshold
        run: |
          # Fail if coverage < 80%
          coverage report --fail-under=80
```

### Branch Strategy

```
main (protected)
  ↑ PR + review required
develop
  ↑ feature branches merge here
feature/add-multi-site
feature/confidence-intervals
bugfix/fix-date-parsing
```

### Pre-commit Hooks

Create `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: ['--maxkb=500']
      
  - repo: https://github.com/psf/black
    rev: 24.1.0
    hooks:
      - id: black
        language_version: python3.11
        
  - repo: https://github.com/pycqa/flake8
    rev: 7.0.0
    hooks:
      - id: flake8
        args: ['--max-line-length=100']
```

---

## 📊 Data Engineering Best Practices

### Data Pipeline Principles

1. **Immutability**: Raw data never modified
2. **Reproducibility**: Any output can be regenerated
3. **Validation**: Data validated at every stage
4. **Lineage**: Track data transformations

### Directory Structure

```
data/
├── raw/                    # Untouched source data
│   └── usgs_download_2024-01-13.csv
├── processed/              # Cleaned, validated data
│   └── groundwater_clean.csv
├── features/               # Feature-engineered data
│   └── training_features.csv
└── outputs/                # Model outputs
    ├── predictions.csv
    └── forecasts.csv
```

### Feature Engineering Standards

```python
class FeatureEngineer:
    """
    Feature engineering with proper data leakage prevention.
    
    All features use ONLY data available at prediction time.
    """
    
    def __init__(self, forecast_horizon: int = 7):
        self.forecast_horizon = forecast_horizon
        self.feature_names: List[str] = []
    
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Create features with documented transformations.
        
        Data Leakage Prevention:
        - All lags shifted by forecast_horizon + lag
        - Rolling stats end forecast_horizon days before target
        - No future data used in any feature
        """
        data = df.copy()
        
        # Document each feature
        self._add_temporal_features(data)
        self._add_lag_features(data)
        self._add_rolling_features(data)
        
        return data
    
    def get_feature_documentation(self) -> pd.DataFrame:
        """Return documentation for all features."""
        return pd.DataFrame({
            'feature': self.feature_names,
            'description': [...],
            'data_available': [...],
        })
```

### Data Validation

```python
from dataclasses import dataclass
from typing import List

@dataclass
class DataQualityReport:
    """Results of data quality checks."""
    passed: bool
    total_records: int
    missing_values: dict
    outliers: dict
    date_gaps: List[tuple]
    warnings: List[str]
    errors: List[str]

def validate_groundwater_data(df: pd.DataFrame) -> DataQualityReport:
    """
    Comprehensive data quality validation.
    
    Checks:
    1. No missing dates in time series
    2. Values within physical bounds (0-50 ft typical)
    3. No sudden jumps (> 3 std dev)
    4. Sufficient data for training
    """
    errors = []
    warnings = []
    
    # Check for gaps
    date_gaps = find_date_gaps(df['date'])
    if date_gaps:
        warnings.append(f"Found {len(date_gaps)} date gaps")
    
    # Check value bounds
    if df['water_level'].min() < 0:
        errors.append("Negative water levels detected")
    
    # Check for outliers
    outliers = detect_outliers(df['water_level'])
    
    return DataQualityReport(
        passed=len(errors) == 0,
        total_records=len(df),
        missing_values=df.isnull().sum().to_dict(),
        outliers=outliers,
        date_gaps=date_gaps,
        warnings=warnings,
        errors=errors,
    )
```

---

## 🧪 Testing Strategy

### Test Categories

| Type | Purpose | Coverage Target |
|------|---------|-----------------|
| **Unit** | Individual functions | 90% |
| **Integration** | Component interactions | 80% |
| **Data** | Data quality & schema | 100% of pipelines |
| **Model** | ML performance | Key metrics |
| **Regression** | Prevent regressions | Critical paths |

### Test Structure

```
tests/
├── conftest.py              # Shared fixtures
├── unit/
│   ├── test_features.py     # Feature engineering
│   ├── test_data_loading.py
│   └── test_utils.py
├── integration/
│   ├── test_pipeline.py     # End-to-end pipeline
│   └── test_model_training.py
├── data/
│   ├── test_data_quality.py
│   └── test_schema.py
└── model/
    ├── test_predictions.py
    └── test_metrics.py
```

### Example Tests

```python
# tests/unit/test_features.py
import pytest
import pandas as pd
import numpy as np
from train_groundwater import create_features, FORECAST_HORIZON

class TestFeatureEngineering:
    """Test feature engineering functions."""
    
    @pytest.fixture
    def sample_data(self):
        """Create sample groundwater data."""
        dates = pd.date_range('2020-01-01', periods=100, freq='D')
        return pd.DataFrame({
            'date': dates,
            'water_level': np.random.normal(5, 1, 100)
        })
    
    def test_no_data_leakage(self, sample_data):
        """Verify features don't use future data."""
        features = create_features(sample_data)
        
        # For any row, all feature values should be computable
        # using only data from FORECAST_HORIZON+ days before
        for i in range(FORECAST_HORIZON + 30, len(features)):
            row = features.iloc[i]
            # lag_7d should equal value from FORECAST_HORIZON + 7 days ago
            expected = sample_data.iloc[i - FORECAST_HORIZON - 7]['water_level']
            assert row['level_lag_7d'] == pytest.approx(expected)
    
    def test_feature_completeness(self, sample_data):
        """Verify no NaN in output features."""
        features = create_features(sample_data)
        assert not features.isnull().any().any()
    
    def test_temporal_features_cyclical(self, sample_data):
        """Verify sin/cos encoding is bounded [-1, 1]."""
        features = create_features(sample_data)
        
        assert features['month_sin'].between(-1, 1).all()
        assert features['month_cos'].between(-1, 1).all()


# tests/model/test_metrics.py
class TestModelPerformance:
    """Test model meets minimum performance standards."""
    
    @pytest.fixture
    def trained_model(self):
        """Load or train model."""
        from joblib import load
        return load('models/best_gradient_boosting.joblib')
    
    def test_r2_minimum(self, trained_model, test_data):
        """Model must achieve R² >= 0.80 on test data."""
        X_test, y_test = test_data
        y_pred = trained_model.predict(X_test)
        r2 = r2_score(y_test, y_pred)
        
        assert r2 >= 0.80, f"R² {r2:.4f} below threshold 0.80"
    
    def test_rmse_maximum(self, trained_model, test_data):
        """RMSE must be <= 0.5 feet."""
        X_test, y_test = test_data
        y_pred = trained_model.predict(X_test)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        
        assert rmse <= 0.5, f"RMSE {rmse:.4f} exceeds threshold 0.5"
```

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html

# Run specific category
pytest tests/unit/ -v
pytest tests/model/ -v

# Run tests matching pattern
pytest -k "test_feature" -v
```

---

## 📝 Documentation Standards

### Code Documentation

Every module should have:

```python
"""
module_name.py - Brief Description

Detailed explanation of what this module does and why.

Dependencies:
    - pandas >= 2.0
    - scikit-learn >= 1.3

Example:
    >>> from module_name import main_function
    >>> result = main_function(data)

Author: walatheo
Created: 2026-01-13
Modified: 2026-01-13
"""
```

### API Documentation

Use Sphinx-compatible docstrings:

```python
def download_usgs_data(
    site_id: str,
    start_date: str,
    end_date: str,
    parameter: str = "72019"
) -> pd.DataFrame:
    """
    Download groundwater data from USGS NWIS.
    
    Fetches daily water level measurements from the USGS National
    Water Information System for a specified monitoring well.
    
    Parameters
    ----------
    site_id : str
        USGS site identifier (e.g., "263314081472201")
    start_date : str
        Start date in YYYY-MM-DD format
    end_date : str
        End date in YYYY-MM-DD format
    parameter : str, optional
        USGS parameter code (default "72019" = depth to water)
    
    Returns
    -------
    pd.DataFrame
        DataFrame with columns:
        - date: datetime64[ns]
        - water_level_ft: float64
        - site_id: str
        - quality_flag: str
    
    Raises
    ------
    ConnectionError
        If USGS API is unreachable
    ValueError
        If site_id not found or date range invalid
    
    Notes
    -----
    Rate limited to 1 request per second per USGS guidelines.
    Data may have gaps; use validate_groundwater_data() to check.
    
    References
    ----------
    .. [1] USGS NWIS: https://waterdata.usgs.gov/nwis
    
    Examples
    --------
    >>> df = download_usgs_data(
    ...     site_id="263314081472201",
    ...     start_date="2020-01-01",
    ...     end_date="2023-12-31"
    ... )
    >>> print(f"Downloaded {len(df)} records")
    Downloaded 1461 records
    """
```

### README Template

```markdown
# Project Name

[![CI](https://github.com/walatheo/GroundwaterGPT/actions/workflows/ci.yml/badge.svg)]()
[![Coverage](https://codecov.io/gh/walatheo/GroundwaterGPT/branch/main/graph/badge.svg)]()
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)]()

Brief description of what this project does.

## Quick Start

\`\`\`bash
git clone https://github.com/walatheo/GroundwaterGPT.git
cd GroundwaterGPT
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python download_data.py
python train_groundwater.py
python dashboard.py
\`\`\`

## Features

- Feature 1
- Feature 2

## Documentation

- [Development Guide](DEVELOPMENT_GUIDE.md)
- [API Reference](docs/api.md)
- [Contributing](CONTRIBUTING.md)

## License

MIT
```

---

## 🧹 Code Maintenance

### Removing Redundant Code

**Checklist before each release:**

- [ ] Run `vulture` to find unused code
- [ ] Check for duplicate functions
- [ ] Remove commented-out code
- [ ] Update imports (remove unused)
- [ ] Consolidate similar functions

```bash
# Find unused code
pip install vulture
vulture *.py --min-confidence 80

# Sort and clean imports
pip install isort
isort .

# Format code consistently  
pip install black
black .
```

### Dependency Management

```bash
# Pin exact versions for reproducibility
pip freeze > requirements-lock.txt

# Keep requirements.txt with version ranges
# requirements.txt
pandas>=2.0,<3.0
scikit-learn>=1.3,<2.0
plotly>=5.18,<6.0
```

### Performance Monitoring

```python
# Add timing decorators to critical functions
import functools
import time
import logging

def timed(func):
    """Log execution time of function."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        logging.info(f"{func.__name__} took {elapsed:.2f}s")
        return result
    return wrapper

@timed
def train_model(X, y):
    # Training code
    pass
```

---

## 📅 Development Workflow

### Daily Development

1. Pull latest: `git pull origin develop`
2. Create branch: `git checkout -b feature/description`
3. Make changes with tests
4. Run quality checks: `pytest && flake8 && mypy`
5. Commit: `git commit -m "feat: description"`
6. Push: `git push origin feature/description`
7. Create PR → Review → Merge

### Commit Message Format

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation
- `test`: Adding tests
- `refactor`: Code refactoring
- `perf`: Performance improvement
- `chore`: Maintenance tasks

### Release Checklist

- [ ] All tests passing
- [ ] Coverage >= 80%
- [ ] No linting errors
- [ ] Documentation updated
- [ ] CHANGELOG updated
- [ ] Version bumped
- [ ] Tagged release

---

## 🔮 Future Addendums

This project is designed for extensibility. Planned research additions:

### Data Sources
- [ ] Additional USGS sites (regional analysis)
- [ ] NOAA precipitation data
- [ ] Sea level monitoring
- [ ] Satellite imagery (NDVI, soil moisture)

### Methodologies
- [ ] LSTM/Transformer models for sequence prediction
- [ ] Bayesian uncertainty quantification
- [ ] Causal inference for climate impacts
- [ ] Ensemble methods

### Research Outputs
- [ ] Automated trend reports
- [ ] Seasonal forecasts
- [ ] Drought/flood risk assessment
- [ ] Publication-ready figures

---

*This guide is a living document. Update as practices evolve.*
