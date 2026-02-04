# GroundwaterGPT - Project Plan & Timeline

**Last Updated:** January 16, 2026
**Project Goal:** Expert-level groundwater knowledge system with verified data
**Repository:** https://github.com/walatheo/GroundwaterGPT
**Advisor Guidance:** Focus on benchmarking, data accuracy, groundwater expertise

---

## 🎯 Updated Vision (Advisor Guidance)

Build a **groundwater-focused expert system** that:
1. **Benchmarks data** against known standards for accuracy
2. **Collects comprehensive USGS data** across Florida aquifers
3. **Validates knowledge base** with rigorous testing
4. **Integrates visualization** directly into the research app
5. **Maintains strict groundwater focus** for domain expertise

---

## 👥 Team Roles & Responsibilities

### Role Definitions

| Role | Responsibility | Primary Files | Git Branch Pattern |
|------|---------------|---------------|-------------------|
| **Data Engineer** | USGS data collection, validation, benchmarking | `continuous_learning.py`, `download_data.py`, `data/` | `data/*` |
| **Knowledge Engineer** | KB accuracy, testing, embeddings, RAG quality | `agent/knowledge.py`, `tests/knowledge/` | `knowledge/*` |
| **UI/UX Developer** | Streamlit interface, visualization integration | `research_chat.py`, `dashboard.py`, `app.py` | `ui/*` |
| **ML Engineer** | Forecasting models, benchmarking, validation | `train_groundwater.py`, `models/` | `ml/*` |
| **Research Lead** | Agent logic, source verification, domain expertise | `agent/research_agent.py`, `agent/source_verification.py` | `agent/*` |

### Workflow Rules

```
main (protected - requires PR review)
  ↑
  └── PR requires: 1 approval + passing tests
      ↑
      └── Feature branches by role:
          ├── data/usgs-florida-expansion
          ├── knowledge/benchmark-tests
          ├── ui/visualization-integration
          ├── ml/model-validation
          └── agent/groundwater-focus
```

### Code Ownership

| Directory | Owner | Reviewer |
|-----------|-------|----------|
| `data/`, `continuous_learning.py` | Data Engineer | Knowledge Engineer |
| `agent/knowledge.py`, `chroma_db/` | Knowledge Engineer | Research Lead |
| `research_chat.py`, `*.html` | UI/UX Developer | Any |
| `train_groundwater.py`, `models/` | ML Engineer | Data Engineer |
| `agent/research_agent.py` | Research Lead | Knowledge Engineer |

---

## 📊 Current Status (February 3, 2026)

### ✅ COMPLETED (Phases 1-4)

| Component | Description | Status |
|-----------|-------------|--------|
| **Knowledge Base** | ChromaDB with 1,901 documents | ✅ |
| **Deep Research Agent** | Iterative search, query optimization | ✅ |
| **Source Verification** | Trust scoring (USGS 1.0 → Unknown 0.5) | ✅ |
| **Query/Research Modes** | Fast KB search + Deep research | ✅ |
| **Continuous Learning** | USGS data auto-fetcher (36 sites active) | ✅ |
| **ML Forecasting** | 7-day predictions (R² = 0.93) | ✅ |
| **React Dashboard** | Interactive map, charts, heatmaps | ✅ |
| **FastAPI Backend** | REST API serving USGS data | ✅ |
| **Data Expansion** | 36 sites, 106,628 records | ✅ |
| **Data Verification** | All sites verified against USGS API | ✅ |
| **KB Accuracy Tests** | 31/31 tests passing | ✅ |
| **Whitebox Documentation** | Transparent architecture | ✅ |

### 🎯 NEXT PRIORITIES (Phase 5)

| Priority | Task | Owner |
|----------|------|-------|
| 1 | **Natural language queries** - AI chat interface | Research Lead |
| 2 | **RAG integration** - Query hydrogeology documents | Knowledge Engineer |
| 3 | **Automated reports** - Generate trend analysis | Research Analyst |
| 4 | **Multi-horizon forecasting** - 7, 14, 30 day predictions | ML Engineer |
| 3 | **KB accuracy tests** - validate data integrity | Knowledge Engineer |
| 4 | **Integrate visualizations** into Streamlit app | UI/UX Developer |
| 5 | **Groundwater focus** - prune non-relevant content | Research Lead |
| 6 | **UI improvements** - better user experience | UI/UX Developer |

---

## 🗓️ Development Timeline

### Phase 1: Data Benchmarking & Expansion
**Duration:** 2 weeks (Jan 16 - Jan 29)
**Owner:** Data Engineer
**Reviewer:** Knowledge Engineer

#### Week 1: Benchmarking (Jan 16-22)
| Task | Description | Deliverable |
|------|-------------|-------------|
| Define benchmarks | Research USGS data standards, expected ranges | `docs/BENCHMARKS.md` |
| Validation tests | Create tests for water level ranges, outliers | `tests/data/test_benchmarks.py` |
| Data quality report | Generate report on current data quality | `data/quality_report.csv` |
| Historical comparison | Compare our data to published USGS reports | Validation document |

#### Week 2: USGS Expansion (Jan 23-29)
| Task | Description | Deliverable |
|------|-------------|-------------|
| Site discovery | Identify 20+ active Florida monitoring sites | Site list |
| Data collection | Fetch 10+ years of data per site | `data/usgs_*.csv` |
| KB integration | Add all site summaries to ChromaDB | Updated KB |
| Coverage map | Visualize monitoring site locations | `plots/florida_sites.html` |

**Success Metrics:**
- [ ] 20+ USGS sites with validated data
- [ ] 100% of data passes benchmark tests
- [ ] Coverage across Floridan, Biscayne, Surficial aquifers

---

### Phase 2: Knowledge Base Accuracy
**Duration:** 2 weeks (Jan 30 - Feb 12)
**Owner:** Knowledge Engineer
**Reviewer:** Research Lead

#### Week 1: Accuracy Testing (Jan 30 - Feb 5)
| Task | Description | Deliverable |
|------|-------------|-------------|
| Query accuracy tests | Test KB returns correct info for known queries | `tests/knowledge/test_accuracy.py` |
| Embedding quality | Evaluate semantic search precision/recall | Metrics report |
| Duplicate detection | Find and remove duplicate chunks | Cleaned KB |
| Metadata validation | Ensure all docs have proper metadata | Validation script |

#### Week 2: KB Optimization (Feb 6-12)
| Task | Description | Deliverable |
|------|-------------|-------------|
| Chunk size tuning | Test different chunk sizes for retrieval | Optimal config |
| Relevance scoring | Improve similarity thresholds | Updated `knowledge.py` |
| Ground truth dataset | Create Q&A pairs for testing | `tests/data/ground_truth.json` |
| Regression tests | Prevent accuracy degradation | CI integration |

**Success Metrics:**
- [ ] 95%+ precision on groundwater queries
- [ ] Ground truth test suite (50+ Q&A pairs)
- [ ] Zero duplicate documents in KB

---

### Phase 3: Visualization Integration
**Duration:** 2 weeks (Feb 13 - Feb 26)
**Owner:** UI/UX Developer
**Reviewer:** Any

#### Week 1: Dashboard Integration (Feb 13-19)
| Task | Description | Deliverable |
|------|-------------|-------------|
| Embed Plotly in Streamlit | Move dashboard.html into app | Integrated UI |
| Real-time data viz | Show live USGS data in app | Dynamic charts |
| Site selector | Dropdown to choose monitoring site | Multi-site view |
| Time range picker | Select date ranges for analysis | Date filters |

#### Week 2: UI Polish (Feb 20-26)
| Task | Description | Deliverable |
|------|-------------|-------------|
| Responsive design | Mobile-friendly layout | CSS updates |
| Loading states | Progress indicators for all operations | Better UX |
| Error handling | User-friendly error messages | Error UI |
| Dark mode | Theme toggle option | Theme support |

**Success Metrics:**
- [ ] All visualizations in Streamlit (no external HTML)
- [ ] Page load time < 3 seconds
- [ ] Mobile-responsive design

---

### Phase 4: Groundwater Expertise Focus
**Duration:** 2 weeks (Feb 27 - Mar 12)
**Owner:** Research Lead
**Reviewer:** Knowledge Engineer

#### Week 1: Content Curation (Feb 27 - Mar 5)
| Task | Description | Deliverable |
|------|-------------|-------------|
| Audit KB content | Review all documents for relevance | Audit report |
| Remove off-topic | Delete non-groundwater content | Cleaned KB |
| Add key sources | Ingest critical hydrogeology references | Expanded KB |
| Terminology mapping | Create groundwater glossary for agent | `data/glossary.json` |

#### Week 2: Agent Specialization (Mar 6-12)
| Task | Description | Deliverable |
|------|-------------|-------------|
| Prompt engineering | Optimize prompts for groundwater | Updated prompts |
| Source prioritization | Boost groundwater-specific sources | Updated verification |
| Expert mode | Deep dive option for technical queries | New agent mode |
| Citation format | Proper scientific citations | Citation system |

**Success Metrics:**
- [ ] 100% groundwater-relevant content in KB
- [ ] Agent passes hydrogeology exam questions
- [ ] Proper citations for all claims

---

## 📋 Testing Requirements

### Data Benchmarking Tests
```python
# tests/data/test_benchmarks.py
def test_water_level_range():
    """Water levels should be within expected ranges for Florida."""
    # Floridan: typically 10-100 ft below surface
    # Biscayne: typically 0-20 ft below surface

def test_no_impossible_values():
    """No negative depths (unless artesian), no values > 500 ft."""

def test_temporal_consistency():
    """No sudden jumps > 10 ft in 24 hours (likely sensor error)."""

def test_site_metadata_complete():
    """All sites have county, aquifer, coordinates."""
```

### Knowledge Base Accuracy Tests
```python
# tests/knowledge/test_accuracy.py
def test_usgs_query_returns_usgs_data():
    """Query about USGS site should return that site's data."""

def test_aquifer_query_returns_correct_aquifer():
    """Query about Biscayne should return Biscayne data."""

def test_no_hallucinated_sites():
    """Agent should not invent non-existent monitoring sites."""

def test_numerical_accuracy():
    """Water level numbers should match source data."""
```

---

## 🔀 Git Workflow

### Branch Naming Convention
```
<role>/<short-description>

Examples:
  data/usgs-expansion
  knowledge/accuracy-tests
  ui/viz-integration
  ml/benchmark-validation
  agent/groundwater-focus
```

### Commit Message Format
```
<type>(<scope>): <description>

Types: feat, fix, docs, test, refactor, data
Scopes: data, knowledge, ui, ml, agent, ci

Examples:
  feat(data): add 10 new USGS monitoring sites
  test(knowledge): add accuracy tests for KB queries
  fix(ui): improve mobile responsiveness
  data(benchmark): add water level range validation
```

### PR Checklist
- [ ] Tests pass (`pytest tests/`)
- [ ] No linting errors
- [ ] Documentation updated
- [ ] Reviewed by code owner
- [ ] Branch up to date with main

---

## 📈 Success Metrics Summary

| Phase | Key Metric | Target | Due Date |
|-------|------------|--------|----------|
| 1. Data | USGS sites with validated data | 20+ | Jan 29 |
| 2. Knowledge | Query precision | 95%+ | Feb 12 |
| 3. UI | Visualization integration | 100% | Feb 26 |
| 4. Expertise | Groundwater relevance | 100% | Mar 12 |

---

## 📅 Milestone Calendar

| Date | Milestone | Owner |
|------|-----------|-------|
| Jan 22 | Data benchmarks complete | Data Engineer |
| Jan 29 | USGS expansion complete (20+ sites) | Data Engineer |
| Feb 5 | KB accuracy tests complete | Knowledge Engineer |
| Feb 12 | KB optimization complete | Knowledge Engineer |
| Feb 19 | Dashboard integration complete | UI/UX Developer |
| Feb 26 | UI polish complete | UI/UX Developer |
| Mar 5 | Content curation complete | Research Lead |
| Mar 12 | Agent specialization complete | Research Lead |

---

## 📝 Meeting Schedule

| Meeting | Frequency | Attendees | Purpose |
|---------|-----------|-----------|---------|
| Standup | Daily (async) | All | Progress updates |
| Sprint Planning | Weekly (Mon) | All | Week's tasks |
| Code Review | As needed | Owner + Reviewer | PR reviews |
| Advisor Check-in | Bi-weekly | Lead + Advisor | Guidance |

---

## 🎯 Immediate Next Steps

### This Week (Jan 16-22)

| Task | Owner | Priority |
|------|-------|----------|
| Create `docs/BENCHMARKS.md` with expected data ranges | Data Engineer | High |
| Create `tests/data/test_benchmarks.py` | Data Engineer | High |
| Run benchmark tests on existing data | Data Engineer | High |
| Document data quality issues found | Data Engineer | Medium |

### Upcoming Sprint (Jan 23-29)

| Task | Owner | Priority |
|------|-------|----------|
| Expand USGS site list to 20+ sites | Data Engineer | High |
| Create KB accuracy test framework | Knowledge Engineer | High |
| Design visualization integration plan | UI/UX Developer | Medium |

---

*This plan follows advisor guidance received January 16, 2026.*
*Focus: Benchmarking → Data Expansion → KB Accuracy → Visualization → Groundwater Expertise*

---

## 📁 Project Structure (Proposed Reorganization)

### Current Issues
- Python scripts scattered at root level
- Documentation mixed with code
- No clear separation of concerns

### Proposed Structure

```
GroundwaterGPT/
│
├── 📚 docs/                      # All documentation
│   ├── README.md                 # Main readme (symlink to root)
│   ├── PROJECT_PLAN.md           # Timeline & milestones
│   ├── ROLES.md                  # Team responsibilities
│   ├── DEVELOPMENT_GUIDE.md      # Coding standards
│   ├── CHECKLIST.md              # Review checklist
│   ├── PROJECT_STATUS.md         # Current status
│   └── BENCHMARKS.md             # Data quality standards (NEW)
│
├── 🤖 src/                       # Source code
│   ├── __init__.py
│   ├── agent/                    # AI agent components
│   │   ├── __init__.py
│   │   ├── research_agent.py     # Deep Research Agent
│   │   ├── knowledge.py          # ChromaDB interface
│   │   ├── source_verification.py # Trust scoring
│   │   ├── llm_factory.py        # LLM configuration
│   │   └── tools.py              # Agent tools
│   │
│   ├── data/                     # Data processing
│   │   ├── __init__.py
│   │   ├── download.py           # USGS data fetcher
│   │   ├── continuous_learning.py # Auto data collection
│   │   └── processing/           # Data pipelines
│   │       ├── __init__.py
│   │       ├── base.py
│   │       ├── groundwater.py
│   │       └── documents.py
│   │
│   ├── ml/                       # Machine learning
│   │   ├── __init__.py
│   │   ├── train.py              # Model training
│   │   └── predict.py            # Predictions
│   │
│   └── ui/                       # User interfaces
│       ├── __init__.py
│       ├── research_chat.py      # Main Streamlit app
│       ├── dashboard.py          # Visualization
│       └── data_explorer.py      # Data exploration
│
├── 📊 data/                      # Data files (gitignored)
│   ├── raw/                      # Raw USGS downloads
│   │   └── usgs_*.csv
│   ├── processed/                # Cleaned data
│   │   └── groundwater.csv
│   └── outputs/                  # Generated outputs
│       ├── forecast.csv
│       └── quality_report.csv
│
├── 📖 resources/                 # Reference materials
│   ├── pdfs/                     # Hydrogeology PDFs
│   │   ├── a-glossary-of-hydrogeology.pdf
│   │   ├── age-dating-young-groundwater.pdf
│   │   └── *.pdf
│   └── glossary.json             # Groundwater terms (NEW)
│
├── 🧠 knowledge_base/            # Vector store
│   └── chroma_db/                # ChromaDB files
│
├── 🎯 models/                    # Trained ML models
│   └── best_ridge.joblib
│
├── 📈 outputs/                   # Generated outputs
│   ├── plots/                    # Visualizations
│   │   └── dashboard.html
│   └── reports/                  # Generated reports
│
├── 🧪 tests/                     # Test suite
│   ├── __init__.py
│   ├── conftest.py
│   ├── data/                     # Data quality tests
│   │   ├── test_quality.py
│   │   └── test_benchmarks.py    # NEW
│   ├── knowledge/                # KB accuracy tests (NEW)
│   │   └── test_accuracy.py
│   ├── model/                    # ML tests
│   │   └── test_performance.py
│   └── unit/                     # Unit tests
│       └── test_features.py
│
├── 🔧 config/                    # Configuration
│   ├── config.py                 # Main config
│   ├── .env.example              # Environment template
│   └── requirements.txt          # Dependencies
│
├── 📜 scripts/                   # Utility scripts
│   └── setup.sh                  # Setup script
│
├── .github/                      # CI/CD
│   └── workflows/
│       └── ci.yml
│
├── .gitignore
├── .pre-commit-config.yaml
├── README.md                     # Root readme
└── pyproject.toml                # Python project config (NEW)
```

### Migration Plan

| Phase | Tasks | Owner |
|-------|-------|-------|
| 1 | Create new directory structure | Any |
| 2 | Move documentation to `docs/` | Any |
| 3 | Move source code to `src/` | Each role |
| 4 | Update imports in all files | Each role |
| 5 | Update CI/CD paths | Any |
| 6 | Test everything works | All |

### Import Changes After Restructure

```python
# Before
from agent.knowledge import search_knowledge
from continuous_learning import ContinuousLearner

# After
from src.agent.knowledge import search_knowledge
from src.data.continuous_learning import ContinuousLearner
```

---
