# GroundwaterGPT

[![CI Pipeline](https://github.com/walatheo/GroundwaterGPT/actions/workflows/ci.yml/badge.svg)](https://github.com/walatheo/GroundwaterGPT/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**A machine learning platform for groundwater level prediction and trend analysis in Southwest Florida.**

---

## 🎯 Project Overview

GroundwaterGPT predicts groundwater levels using historical data from USGS monitoring wells. The platform provides:

- **7-day ahead predictions** with 93% accuracy (R² = 0.93)
- **Interactive dashboard** for trend visualization
- **Research-ready foundation** for hydrogeological studies

### Current Model Performance

| Metric | Value | Threshold |
|--------|-------|-----------|
| R² (7-day ahead) | **0.9262** | ≥ 0.80 |
| RMSE | **0.30 ft** | ≤ 0.50 ft |
| MAE | **0.23 ft** | — |

---

## 🚀 Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/walatheo/GroundwaterGPT.git
cd GroundwaterGPT

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Download Data

```bash
python download_data.py
```

This fetches real groundwater data from USGS for Fort Myers, FL (2014-2023).

### 3. Train Model

```bash
python train_groundwater.py
```

Trains and compares Ridge, Random Forest, and Gradient Boosting models.

### 4. Generate Dashboard

```bash
python dashboard.py
open plots/dashboard.html
```

Creates an interactive 6-panel visualization of groundwater trends.

---

## 📊 Data Sources

### Groundwater Data
- **Source:** USGS National Water Information System (NWIS)
- **Site:** 263314081472201 (Fort Myers, Surficial Aquifer)
- **Period:** 2014-01-01 to 2023-12-31
- **Records:** 3,650 daily measurements
- **Variable:** Depth to water level (feet below surface)

### Reference Documents
Three hydrogeology PDFs are embedded in ChromaDB for future RAG integration:
- `a-glossary-of-hydrogeology.pdf`
- `age-dating-young-groundwater.pdf`
- `a-conceptual-overview-of-surface-and-near-surface-brines-and-evaporite-minerals.pdf`

---

## 📁 Project Structure

```
GroundwaterGPT/
├── config.py                 # Configuration settings
├── download_data.py          # USGS data fetcher
├── train_groundwater.py      # Model training pipeline
├── dashboard.py              # Interactive dashboard generator
├── requirements.txt          # Dependencies
├── DEVELOPMENT_GUIDE.md      # Best practices & standards
├── PROJECT_STATUS.md         # Roadmap & current status
│
├── data/                     # Data files (gitignored)
│   ├── groundwater.csv       # USGS measurements
│   ├── forecast.csv          # 30-day predictions
│   └── model_comparison.csv  # Model metrics
│
├── models/                   # Trained models (gitignored)
│   └── best_gradient_boosting.joblib
│
├── plots/                    # Visualizations (gitignored)
│   ├── dashboard.html        # Interactive dashboard
│   └── model_predictions.png # Prediction accuracy
│
├── tests/                    # Test suite
│   ├── unit/                 # Feature engineering tests
│   ├── model/                # Model performance tests
│   └── data/                 # Data quality tests
│
├── .github/workflows/        # CI/CD pipeline
│   └── ci.yml
│
└── chroma_db/                # Vector store for RAG
```

---

## 🧪 Testing

Run the full test suite:

```bash
pytest tests/ -v
```

Run with coverage:

```bash
pytest tests/ --cov=. --cov-report=html
open htmlcov/index.html
```

### Test Categories

| Category | Tests | Purpose |
|----------|-------|---------|
| `tests/unit/` | 9 | Feature engineering, data leakage prevention |
| `tests/model/` | 10 | Model performance thresholds |
| `tests/data/` | 13 | Data quality and schema validation |

**Current Status:** 32/32 tests passing ✅

---

## 🔧 Development

### Pre-commit Hooks

Install hooks for automatic code quality checks:

```bash
pip install pre-commit
pre-commit install
```

### Code Style

- **Formatter:** Black (line length 100)
- **Linter:** Flake8
- **Import sorting:** isort
- **Type hints:** Required for public functions

### Branch Strategy

```
main (protected)
  ↑ PR + CI must pass
develop
  ↑ feature branches
feature/your-feature
```

---

## 📈 Roadmap

| Phase | Status | Focus |
|-------|--------|-------|
| 1. Foundation | ✅ Complete | Data pipeline, ML model, dashboard |
| 2. Quality | 🔄 Current | CI/CD, testing, documentation |
| 3. Enhancement | 📋 Planned | Multi-horizon forecasting, confidence intervals |
| 4. Research | 📋 Planned | RAG integration, automated reports |
| 5. Production | 📋 Planned | API, web hosting, alerts |

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for detailed roadmap.

---

## 📚 Documentation

- **[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)** - Coding standards, roles, schedule
- **[PROJECT_STATUS.md](PROJECT_STATUS.md)** - Current status and roadmap

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make changes with tests
4. Run quality checks (`pytest && flake8`)
5. Commit with conventional message (`feat: add new feature`)
6. Push and create PR

---

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

---

## 👤 Author

**walatheo** - [GitHub](https://github.com/walatheo)

*Florida Gulf Coast University*

---

## 🙏 Acknowledgments

- **USGS** - Groundwater monitoring data via NWIS
- **Copernicus Climate Data Store** - ERA5 reanalysis data
- **scikit-learn** - Machine learning framework
- **Plotly** - Interactive visualizations
