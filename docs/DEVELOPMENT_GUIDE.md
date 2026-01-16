# GroundwaterGPT Development Guide

**Purpose:** Best practices and standards for developing a production-quality groundwater prediction and research platform.

**Core Goals:**
1. Accurate groundwater level modeling and trend analysis
2. Research-ready platform with extensibility for future studies
3. Clean, maintainable, well-documented codebase

---

## 📋 Table of Contents

1. [Project Roles](#-project-roles)
2. [Development Schedule](#-development-schedule)
3. [Project Vision & Roadmap](#-project-vision--roadmap)
4. [Code Quality Standards](#-code-quality-standards)
5. [CI/CD Pipeline](#-cicd-pipeline)
6. [Data Engineering Best Practices](#-data-engineering-best-practices)
7. [Testing Strategy](#-testing-strategy)
8. [Documentation Standards](#-documentation-standards)
9. [Code Maintenance](#-code-maintenance)

---

## 👥 Project Roles

### Role Definitions

This project is structured around **four key roles** that ensure comprehensive coverage of all aspects from data to deployment. Each role has specific responsibilities, deliverables, and quality gates.

---

### 1. 📊 Data Engineer

**Focus:** Data acquisition, pipeline reliability, and feature engineering

**Responsibilities:**
- Maintain USGS data download pipeline (`download_data.py`)
- Ensure data quality and validation
- Design and implement feature engineering
- Monitor data freshness and completeness
- Handle data versioning and lineage

**Key Files Owned:**
- `download_data.py`
- `config.py` (data source configuration)
- `train_groundwater.py` (feature engineering sections)
- `tests/data/test_quality.py`

**Quality Gates:**
- [ ] All data tests pass (`pytest tests/data/`)
- [ ] No data gaps > 7 days in time series
- [ ] Feature engineering documented with rationale
- [ ] Data validation runs on every pipeline execution

**Deliverables per Sprint:**
| Deliverable | Acceptance Criteria |
|-------------|---------------------|
| Data freshness | Data updated within 7 days of latest USGS |
| Schema documentation | All columns documented with types/ranges |
| Feature documentation | Each feature has: name, formula, rationale |
| Validation report | Weekly data quality metrics |

---

### 2. 🤖 ML Engineer

**Focus:** Model development, training, evaluation, and prediction quality

**Responsibilities:**
- Design and train prediction models
- Prevent data leakage in feature/target setup
- Evaluate model performance and select best models
- Implement model versioning and tracking
- Monitor model drift and trigger retraining

**Key Files Owned:**
- `train_groundwater.py` (model training sections)
- `models/*.joblib`
- `tests/model/test_performance.py`
- Model experiment logs

**Quality Gates:**
- [ ] R² ≥ 0.80 on test set (7-day ahead)
- [ ] RMSE ≤ 0.5 ft
- [ ] No data leakage (verified by tests)
- [ ] Feature importance documented
- [ ] Model comparison documented

**Deliverables per Sprint:**
| Deliverable | Acceptance Criteria |
|-------------|---------------------|
| Model performance report | R², RMSE, MAE for all models |
| Feature importance analysis | Top 10 features with interpretation |
| Prediction validation | Backtesting on holdout period |
| Model card | Documented assumptions, limitations |

---

### 3. 🎨 Software Engineer

**Focus:** Code quality, architecture, testing, and CI/CD

**Responsibilities:**
- Maintain code quality standards (linting, formatting)
- Design and implement software architecture
- Write and maintain tests
- Manage CI/CD pipeline
- Code reviews and refactoring

**Key Files Owned:**
- `.github/workflows/ci.yml`
- `.pre-commit-config.yaml`
- `tests/unit/*.py`
- `config.py`
- All `__init__.py` files

**Quality Gates:**
- [ ] All tests pass (32+ tests)
- [ ] Code coverage ≥ 80%
- [ ] No linting errors (flake8, black, isort)
- [ ] Type hints on all public functions
- [ ] No code duplication

**Deliverables per Sprint:**
| Deliverable | Acceptance Criteria |
|-------------|---------------------|
| Test coverage report | Coverage % with gaps identified |
| CI/CD status | All pipelines green |
| Code review | All PRs reviewed within 24h |
| Refactoring log | Technical debt addressed |

---

### 4. 📈 Research Analyst

**Focus:** Domain expertise, visualization, insights, and documentation

**Responsibilities:**
- Interpret model results in hydrogeological context
- Design and maintain dashboard visualizations
- Write research documentation and reports
- Integrate domain knowledge (PDFs, literature)
- Identify new research questions and data sources

**Key Files Owned:**
- `dashboard.py`
- `plots/*.html`, `plots/*.png`
- `README.md`, `PROJECT_STATUS.md`
- `DEVELOPMENT_GUIDE.md` (research sections)
- PDF reference documents

**Quality Gates:**
- [ ] Dashboard reflects current model predictions
- [ ] Trend report updated with each data refresh
- [ ] Visualizations follow accessibility standards
- [ ] Research context documented

**Deliverables per Sprint:**
| Deliverable | Acceptance Criteria |
|-------------|---------------------|
| Updated dashboard | Reflects latest predictions |
| Trend analysis report | Key findings summarized |
| Research notes | New insights documented |
| Literature review | Relevant papers identified |

---

### Role Interaction Matrix

| From → To | Data Engineer | ML Engineer | Software Engineer | Research Analyst |
|-----------|---------------|-------------|-------------------|------------------|
| **Data Engineer** | — | Provides features | Reports data issues | Explains data sources |
| **ML Engineer** | Requests features | — | Reports model bugs | Explains predictions |
| **Software Engineer** | Reviews pipeline code | Reviews model code | — | Reviews viz code |
| **Research Analyst** | Requests new data | Validates predictions | Requests features | — |

---

## 📅 Development Schedule

### Sprint Structure

**Sprint Duration:** 2 weeks
**Sprint Cadence:**
- Day 1: Sprint planning & goal setting
- Days 2-12: Development work
- Day 13: Testing & integration
- Day 14: Sprint review & retrospective

---

### Phase 2: Quality Infrastructure (Current)
*January 13 - January 27, 2026*

| Week | Focus | Role Lead | Deliverables |
|------|-------|-----------|--------------|
| **Week 1** | Testing & CI/CD | Software Engineer | ✅ Test suite (32 tests), CI pipeline |
| **Week 2** | Documentation | Research Analyst | README update, API docs |

**Sprint Goals:**
- [x] Set up pytest framework
- [x] Create CI/CD pipeline
- [x] Add pre-commit hooks
- [ ] Achieve 80% code coverage
- [ ] Complete API documentation

---

### Phase 3: Agentic RAG System (Current)
*January 15 - February 15, 2026*

| Week | Focus | Role Lead | Deliverables |
|------|-------|-----------|--------------|
| **Week 1** | Agent Architecture | Software Engineer | LLM factory, tools, knowledge base |
| **Week 2** | Tool Implementation | Data Engineer + ML Engineer | Data query tools, prediction tools |
| **Week 3** | Deep Research Agent | Software Engineer | Iterative search, synthesis |
| **Week 4** | Chat Interface | Research Analyst | Streamlit chat app, user testing |

**Sprint Goals:**
- [x] Create modular LLM factory (swappable providers)
- [x] Implement groundwater data tools
- [x] Connect ChromaDB knowledge base
- [x] Build Deep Research Agent with iterative search
- [x] Integrate DuckDuckGo web search
- [x] Test with Ollama/Llama locally
- [ ] Test with Gemini API (quota pending)
- [ ] Launch chat interface
- [ ] Document agent capabilities

**Key Files:**
- `agent/llm_factory.py` - Swappable LLM providers (Ollama, OpenAI, Anthropic, Gemini)
- `agent/tools.py` - 6 custom groundwater tools
- `agent/knowledge.py` - ChromaDB RAG connector (1,884 chunks)
- `agent/groundwater_agent.py` - Main agent logic with simple retrieval mode
- `agent/research_agent.py` - Deep Research Agent with iterative search
- `chat_app.py` - Streamlit chat interface

**Deep Research Agent Features:**
- Iterative research with configurable depth (default: 3 levels)
- Query optimization using LLM
- Multi-source search (knowledge base + web)
- Insight extraction with confidence scoring
- Follow-up query generation
- Comprehensive report synthesis

---

### Phase 4: Enhanced Predictions
*February 15 - March 15, 2026*

| Week | Focus | Role Lead | Deliverables |
|------|-------|-----------|--------------|
| **Week 1-2** | Multi-horizon forecasting | ML Engineer | 7/14/30/90 day predictions |
| **Week 3-4** | Confidence intervals | ML Engineer + Data Engineer | Uncertainty quantification |

**Sprint Goals:**
- [ ] Implement multi-horizon prediction
- [ ] Add prediction confidence intervals
- [ ] Create forecast comparison dashboard
- [ ] Backtest on 2023 data

---

### Phase 4: Data Expansion
*February 24 - March 24, 2026*

| Week | Focus | Role Lead | Deliverables |
|------|-------|-----------|--------------|
| **Week 1-2** | Multi-site support | Data Engineer | 3-5 additional USGS sites |
| **Week 3-4** | Regional analysis | Research Analyst | Cross-site comparison dashboard |

**Sprint Goals:**
- [ ] Add Southwest Florida regional sites
- [ ] Create site comparison visualizations
- [ ] Implement regional trend analysis
- [ ] Document site selection criteria

---

### Phase 5: Research Platform
*March 24 - April 21, 2026*

| Week | Focus | Role Lead | Deliverables |
|------|-------|-----------|--------------|
| **Week 1-2** | RAG integration | Software Engineer | Query interface for PDFs |
| **Week 3-4** | Automated reports | Research Analyst | Monthly report generation |

**Sprint Goals:**
- [ ] LLM integration for natural language queries
- [ ] Automated monthly trend reports
- [ ] Research paper integration
- [ ] Knowledge base documentation

---

### Phase 6: Production Deployment
*April 21 - May 19, 2026*

| Week | Focus | Role Lead | Deliverables |
|------|-------|-----------|--------------|
| **Week 1-2** | API development | Software Engineer | REST API for predictions |
| **Week 3-4** | Web deployment | Software Engineer | Hosted dashboard |

**Sprint Goals:**
- [ ] Deploy API endpoint
- [ ] Host interactive dashboard
- [ ] Set up monitoring and alerts
- [ ] Create user documentation

---

### Milestone Summary

```
Jan 2026 ──────────────────────────────────────────────────────────► May 2026

     Phase 2          Phase 3           Phase 4          Phase 5        Phase 6
   ┌─────────┐     ┌───────────┐     ┌───────────┐    ┌──────────┐   ┌─────────┐
   │ Quality │ ──► │ Enhanced  │ ──► │   Data    │ ──►│ Research │ ──►│  Prod   │
   │  Infra  │     │Predictions│     │ Expansion │    │ Platform │   │ Deploy  │
   └─────────┘     └───────────┘     └───────────┘    └──────────┘   └─────────┘
      CI/CD          Multi-horizon     Multi-site        RAG           API
      Tests          Uncertainty       Regional          Reports       Web Host

   ✅ Current          📋 Next           📋 Q1             📋 Q1         📋 Q2
```

---

### Weekly Check-in Template

```markdown
## Weekly Check-in: [Date]

### Progress
- [ ] Data Engineer:
- [ ] ML Engineer:
- [ ] Software Engineer:
- [ ] Research Analyst:

### Blockers
-

### Next Week
-

### Metrics
- Tests passing: __/32
- Code coverage: __%
- Model R²: ___
- Data freshness: ___ days
```

---

### Definition of Done

A feature/task is considered **DONE** when:

- [ ] Code written and self-reviewed
- [ ] Unit tests added (if applicable)
- [ ] All tests pass locally
- [ ] Documentation updated
- [ ] PR created and reviewed
- [ ] CI pipeline passes
- [ ] Merged to main branch

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
