# GroundwaterGPT

[![CI Pipeline](https://github.com/walatheo/GroundwaterGPT/actions/workflows/ci.yml/badge.svg)](https://github.com/walatheo/GroundwaterGPT/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**An AI-powered groundwater research platform with transparent, explainable architecture.**

---

## 🎯 Project Overview

GroundwaterGPT is a **whitebox AI system** that combines:
- **Deep Research Agent**: LLM-powered research with source verification
- **Continuous Learning**: Auto-growing knowledge base from USGS data
- **ML Predictions**: 7-day groundwater level forecasts (93% accuracy)
- **Interactive Dashboard**: Trend visualization

### Key Features

| Feature | Description |
|---------|-------------|
| 📚 **Query Mode** | Instant search of knowledge base (USGS data, PDFs) |
| 🔬 **Research Mode** | Deep web research with verified sources |
| 🧠 **Auto-Learning** | Continuously grows knowledge from new data |
| 📊 **Predictions** | ML models for groundwater level forecasting |
| ✅ **Whitebox** | All decisions are transparent and explainable |

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

### 2. Start the Research Interface

```bash
# Using main entry point
python main.py app

# Or directly
streamlit run src/ui/research_chat.py --server.port 8502
```

Open http://localhost:8502 to access:
- **Query Mode**: Fast search of USGS data and hydrogeology documents
- **Research Mode**: Deep research with web search and auto-learning

### 3. Run Continuous Learning

```bash
python main.py learn
```

Fetches data from 40+ Florida aquifer monitoring sites and adds to knowledge base.

### 4. View the Dashboard

```bash
open plots/dashboard.html
```

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
- `resources/pdfs/*.pdf` - Hydrogeology reference documents

---

## 📁 Project Structure

```
GroundwaterGPT/
├── main.py                   # 🚀 CLI entry point (Streamlit legacy)
├── README.md                 # This file
├── requirements.txt          # Python dependencies
│
├── 📚 docs/                  # Documentation
│   ├── ROLES.md              # Team responsibilities
│   ├── DEVELOPMENT_GUIDE.md  # Coding standards
│   ├── ENGINEERING_STANDARDS.md  # Software engineering standards
│   └── CHECKLIST.md          # Review checklist
│
├── 🖥️ api/                   # FastAPI Backend
│   └── main.py               # REST API server (port 8000)
│
├── 🌐 frontend/              # React Frontend
│   ├── src/                  # React components
│   ├── package.json          # NPM dependencies
│   └── vite.config.js        # Vite configuration
│
├── 🤖 src/                   # Source code
│   ├── agent/                # AI research agent
│   │   ├── research_agent.py # Deep Research Agent
│   │   ├── knowledge.py      # ChromaDB interface
│   │   └── source_verification.py
│   ├── data/                 # Data processing
│   │   ├── download_data.py  # USGS fetcher
│   │   └── continuous_learning.py
│   └── ml/                   # Machine learning
│       └── train_groundwater.py
│
├── 📊 data/                  # USGS CSV data
│   └── usgs_*.csv            # 36 monitoring sites
│
├── 📖 resources/             # Reference materials
│   └── pdfs/                 # Hydrogeology PDFs
│
├── 🧠 knowledge_base/        # ChromaDB vector store
│
├── 🎯 models/                # Trained ML models
│
├── 📈 outputs/               # Generated outputs
│   └── plots/                # Visualizations
│
├── 🧪 tests/                 # Test suite (89+ tests)
│   ├── data/                 # Data quality & integrity tests
│   ├── model/                # ML performance tests
│   └── unit/                 # Unit tests
│
└── 🔧 config/                # Configuration
    └── config.py
```

---

## 🏗️ Whitebox Architecture

GroundwaterGPT follows **whitebox principles** - all AI decisions are transparent and explainable.

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                        │
│  src/ui/research_chat.py (Streamlit UI)                            │
│  - Query Mode: Fast KB search                               │
│  - Research Mode: Deep web research                         │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    AGENT LAYER                              │
│  agent/research_agent.py (Deep Research Agent)              │
│  - Query optimization                                       │
│  - Iterative search                                         │
│  - Insight extraction                                       │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    KNOWLEDGE LAYER                          │
│  agent/knowledge.py (ChromaDB + Embeddings)                 │
│  - Vector search (BAAI/bge-small-en-v1.5)                  │
│  - Document storage                                         │
│  continuous_learning.py (Data Collection)                   │
│  - USGS API integration                                     │
│  - Auto-ingestion                                           │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    VERIFICATION LAYER                       │
│  agent/source_verification.py                               │
│  - Trust scoring (0.0 - 1.0)                               │
│  - Source categorization                                    │
│  - Approval/rejection logic                                 │
└─────────────────────────────────────────────────────────────┘
```

### Trust Hierarchy

All sources are scored transparently:

| Priority | Source Type | Score | Example |
|----------|-------------|-------|---------|
| 1 | USGS Data | 1.00 | waterdata.usgs.gov |
| 2 | Research Papers | 0.95 | DOI links, journals |
| 3 | Government | 0.90 | .gov domains |
| 4 | Academic | 0.85 | .edu domains |
| 5 | Reference | 0.70 | Wikipedia |
| 6 | Unknown | 0.50 | Unverified |
| 7 | Untrusted | 0.00 | Blocked |

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
| `tests/unit/` | 50+ | Feature engineering, data leakage prevention |
| `tests/model/` | 10 | Model performance thresholds |
| `tests/data/` | 25+ | Data quality, schema validation, USGS integrity |

**Current Status:** 89/89 tests passing ✅

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
| 2. Quality | ✅ Complete | CI/CD, testing, documentation |
| 3. Enhancement | ✅ Complete | Multi-site expansion, React frontend |
| 4. Dashboard | ✅ Complete | AI Chat (Beta), 36 USGS sites, interactive maps |
| 5. Research | � Current | AI Research Integration, advanced analytics |
| 6. Production | 📋 Planned | API, web hosting, alerts |

See [CHECKLIST.md](docs/CHECKLIST.md) for detailed status.

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| **[CHECKLIST.md](docs/CHECKLIST.md)** | Active tasks, phase goals, sprint tracking |
| **[DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md)** | Architecture, roles, coding standards |
| **[ENGINEERING_STANDARDS.md](docs/ENGINEERING_STANDARDS.md)** | Testing philosophy, code quality rules |
| **[SPONSOR_SUMMARY.md](docs/SPONSOR_SUMMARY.md)** | Executive overview for stakeholders |

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
