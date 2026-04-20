# EAGLE — Evidence-Aligned Groundwater Level Explorer

[![CI Pipeline](https://github.com/walatheo/GroundwaterGPT/actions/workflows/ci.yml/badge.svg)](https://github.com/walatheo/GroundwaterGPT/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**EAGLE is an auditable groundwater research platform that turns public USGS records for 44 Florida monitoring wells into usable trend analysis, visual summaries, and reproducible outputs, with evidence-guided AI limited to explanation and next-step guidance over a deterministic analysis pipeline.**

---

## Quick Demo

```bash
make demo
```

Open http://localhost:3000, then try:

- `Estero trends` for a 10-well cohort chart.
- `compare G-3336 and G-5004` for a 2-well overlay.
- `which aquifer supplies Estero?` for a text-only answer with no chart.

The demo starts FastAPI on http://127.0.0.1:8000 with `GROUNDWATERGPT_SKIP_AGENT_INIT=1`, waits for `/api/chat/status`, then starts the Vite frontend on http://localhost:3000. Logs stream to `/tmp/gwgpt-backend.log` and `/tmp/gwgpt-frontend.log`.

Build note, 2026-04-14: after lazy-loading chart panels, the initial Vite JS chunk is `260.26 kB` gzip; chart-heavy panels load as async chunks.

---

## 🎯 Project Overview

EAGLE is a **research-facing whitebox application** that combines:
- **Deterministic USGS Analysis**: Monthly aggregation, trend summaries, cohort comparison, and chart payloads from local monitoring records
- **Evidence-Linked Assistance**: Claim IDs, evidence IDs, citation integrity checks, and provenance metadata
- **Research Workflow**: Plans, reproducible run logging, and manuscript draft scaffolding
- **Interactive Dashboard**: Map, time-series, heatmap, workbench, and chat/research views

### Key Features

| Feature | Description |
|---------|-------------|
| 📚 **Query Mode** | Groundwater Q&A over local data and curated hydrogeology sources |
| 🔬 **Research Mode** | Structured reports with claim citations, verdicts, and provenance |
| 📈 **Deterministic Trends** | USGS monthly means, net change, annualized rates, and cohort summaries |
| 🗺️ **Visual Analysis** | Map, time-series, heatmap, and comparative workbench views |
| ✅ **Whitebox** | User-facing conclusions carry citations, evidence IDs, and reproducibility metadata |

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

### 2. Start the Demo

```bash
make demo
```

Open http://localhost:3000 to access the React dashboard and research interface.

### 3. Run Benchmarks

```bash
make benchmark
```

Runs the deterministic fallback benchmark with threshold enforcement.

### 4. Run Unit Tests

```bash
make test
```

---

## 📊 Data Sources

### Groundwater Data
- **Source:** USGS National Water Information System (NWIS)
- **Network:** 40 canonical USGS time-series CSVs, with 44 metadata entries available to the site catalogue
- **Period:** Local records span 1994-01-01 to 2026-04-05 across the shipped dataset
- **Variable:** Depth to water level (feet below surface)

### Reference Documents
Three hydrogeology PDFs are embedded in ChromaDB for future RAG integration:
- `a-glossary-of-hydrogeology.pdf`
- `age-dating-young-groundwater.pdf`
- `resources/pdfs/*.pdf` - Hydrogeology reference documents

---

## 📁 Project Structure

```
EAGLE/
├── README.md                 # This file
├── requirements.txt          # Python dependencies
│
├── 📚 docs/                  # Documentation
│   ├── README.md             # Documentation index
│   ├── EAGLE_TECHNICAL_OVERVIEW.md
│   ├── MANUSCRIPT_DRAFT.md
│   ├── DEVELOPMENT_GUIDE.md
│   ├── ENGINEERING_STANDARDS.md
│   └── DEMO_RUNBOOK.md
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
│
├── 📊 data/                  # USGS CSV data
│   └── usgs_*.csv            # 40 canonical monitoring-site time series
│
├── 📖 resources/             # Reference materials
│   └── pdfs/                 # Hydrogeology PDFs
│
├── 🧠 knowledge_base/        # ChromaDB vector store
│
├── 📈 outputs/               # Generated research outputs, ignored by git
│
├── 🧪 tests/                 # Test suite (181 unit tests passing locally)
│   ├── data/                 # Data quality & integrity tests
│   └── unit/                 # Unit tests
│
└── 🔧 config/                # Configuration
    └── config.py
```

---

## 🏗️ Whitebox Architecture

EAGLE follows **whitebox principles** — all AI-surfaced conclusions are traceable to deterministic routines over the local USGS monitoring archive.

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                        │
│  frontend/src (React + Vite)                                │
│  - Dashboard, map, charts, chat                             │
│  - Inline chart rendering from deterministic API payloads   │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    API + ANALYSIS LAYER                     │
│  api/routes/chat.py + api/routes/_site_analysis.py          │
│  - Routing to site/aquifer/location/network cohorts         │
│  - Monthly means, trends, citations, chart payloads         │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│               KNOWLEDGE + EVIDENCE-GUIDED AI LAYER          │
│  agent/knowledge.py (ChromaDB + Embeddings)                 │
│  - Vector search (BAAI/bge-small-en-v1.5)                  │
│  api/routes/_evidence_guided_ai.py                          │
│  - Grounded next-goal and follow-up synthesis               │
│  agent/research_agent.py                                    │
│  - Experimental research-agent path kept out of demo core   │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    VERIFICATION + PROVENANCE LAYER          │
│  api/routes/_citation.py + api/routes/_provenance.py        │
│  - Claim verdicts, citation integrity, hashes               │
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

Run the deterministic unit suite:

```bash
make test
```

Run the benchmark gate used for manuscript-facing deterministic claims:

```bash
make benchmark
```

### Test Categories

| Category | Tests | Purpose |
|----------|-------|---------|
| `tests/unit/` | 181 passing locally | API contracts, chart payloads, citation integrity, claim verdicts, workbench |
| `tests/benchmark/` | 68 cases | Deterministic research response checks and threshold enforcement |
| `tests/data/` | 25+ | Data quality, schema validation, USGS integrity |
**Current deterministic status:** manuscript-facing unit tests and the 68/68 fallback benchmark pass locally.

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
| 1. Foundation | ✅ Complete | Data pipeline, dashboard, baseline research interface |
| 2. Quality | ✅ Complete | CI/CD, testing, documentation |
| 3. Enhancement | ✅ Complete | Multi-site expansion, React frontend |
| 4. Dashboard | ✅ Complete | AI Chat (Beta), 40 canonical USGS time-series files, interactive maps |
| 5. Research | 🔄 Current | Research utility, provenance, and manuscript-safe analysis |
| 6. Production | 📋 Planned | API, web hosting, alerts |

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| **[docs/README.md](docs/README.md)** | Documentation index for the maintained guide set |
| **[EAGLE_TECHNICAL_OVERVIEW.md](docs/EAGLE_TECHNICAL_OVERVIEW.md)** | Manuscript-grounding technical description |
| **[MANUSCRIPT_DRAFT.md](docs/MANUSCRIPT_DRAFT.md)** | Submission-oriented draft centered on the actual novelty |
| **[DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md)** | Architecture and developer workflow |
| **[ENGINEERING_STANDARDS.md](docs/ENGINEERING_STANDARDS.md)** | Testing philosophy and code quality rules |
| **[DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md)** | Deterministic demo and benchmark walkthrough |

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
- **Copernicus Climate Data Store** - Optional ERA5 reanalysis source for local experiments
