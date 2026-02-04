# Team Roles & Responsibilities

**Last Updated:** February 4, 2026
**Version:** 2.0
**Project:** GroundwaterGPT - Florida Aquifer Intelligence Platform

This document defines team roles, specialized responsibilities, deliverables, and requirements for clean collaboration. **All changes to responsibilities require team discussion and documentation.**

---

## � Table of Contents

1. [Role Definitions](#-role-definitions)
2. [Specialized Work Areas](#-specialized-work-areas)
3. [Requirements & Standards](#-requirements--standards)
4. [Git Workflow](#-git-workflow)
5. [PR Review Process](#-pr-review-process)
6. [Change Management](#-change-management)
7. [Current Sprint](#-current-sprint)

---

## �👥 Role Definitions

### 1. Data Engineer
**Specialization:** USGS Data Pipeline & Quality Assurance

| Area | Responsibility | Primary Files | Deliverables |
|------|---------------|---------------|--------------|
| **Data Collection** | Fetch USGS groundwater data from NWIS API | `download_data.py`, `continuous_learning.py` | Clean CSV files |
| **Data Validation** | Ensure data quality, remove outliers | `tests/data/test_benchmarks.py` | Quality reports |
| **Pipeline Maintenance** | Keep data pipeline running reliably | `data/*.csv` | Automated updates |
| **Benchmarking** | Compare data against USGS standards | `scripts/verify_usgs_data.py` | Verification logs |

**Required Deliverables (Phase 5):**
- [ ] Maintain 36+ USGS sites with validated data
- [ ] Automated daily data refresh pipeline
- [ ] Data quality dashboard showing anomalies
- [ ] 100% data passes benchmark tests

**Quality Gates (MUST MEET):**
| Metric | Requirement | Current |
|--------|-------------|---------|
| Total Sites | ≥ 36 | ✅ 36 |
| Data Records | ≥ 100,000 | ✅ 106,628 |
| USGS API Verification | 100% | ✅ 100% |
| Benchmark Test Pass | 100% | ✅ 100% |
| No Impossible Values | 0 errors | ✅ Passing |

**Branch Pattern:** `data/*`

---

### 2. Knowledge Engineer
**Specialization:** RAG System & Knowledge Base Quality

| Area | Responsibility | Primary Files | Deliverables |
|------|---------------|---------------|--------------|
| **KB Maintenance** | Manage ChromaDB vector store | `src/agent/knowledge.py`, `knowledge_base/` | Clean KB |
| **RAG Quality** | Ensure accurate document retrieval | `tests/knowledge/test_*.py` | Accuracy tests |
| **Embedding Optimization** | Tune chunk sizes, similarity thresholds | `config/config.py` | Optimal config |
| **Ground Truth Testing** | Create Q&A pairs for validation | `tests/data/ground_truth.json` | Test dataset |

**Required Deliverables (Phase 5):**
- [ ] RAG integration for hydrogeology queries
- [ ] 95%+ query precision on groundwater topics
- [ ] Zero duplicate documents in KB
- [ ] 50+ ground truth Q&A pairs for validation

**Quality Gates (MUST MEET):**
| Metric | Requirement | Current |
|--------|-------------|---------|
| KB Documents | ≥ 1,500 | ✅ 1,901 |
| Query Precision | ≥ 95% | ✅ 97% |
| Accuracy Tests | 100% pass | ✅ 31/31 |
| Duplicate Docs | 0 | ✅ 0 |
| Florida-Specific Tests | 100% pass | ✅ 31/31 |

**Branch Pattern:** `knowledge/*`

---

### 3. Frontend Developer
**Specialization:** React Dashboard & User Interface

| Area | Responsibility | Primary Files | Deliverables |
|------|---------------|---------------|--------------|
| **React Dashboard** | Main visualization interface | `frontend/src/components/*.jsx` | Interactive UI |
| **Map Visualization** | Leaflet map with site markers | `frontend/src/components/MapView.jsx` | Site map |
| **Charts & Graphs** | Recharts time series, heatmaps | `TimeSeriesChart.jsx`, `HeatmapChart.jsx` | Data viz |
| **AI Chat Interface** | Chat UI for farmer/researcher queries | `frontend/src/components/ChatView.jsx` | Chat component |
| **Responsive Design** | Mobile-friendly layouts | `frontend/src/index.css` | CSS updates |

**Required Deliverables (Phase 5):**
- [ ] Full AI Assistant chat interface (upgrade from Beta)
- [ ] Farmer-focused dashboard view
- [ ] Multi-site comparison view
- [ ] Export data functionality

**Quality Gates (MUST MEET):**
| Metric | Requirement | Current |
|--------|-------------|---------|
| Page Load Time | < 3 seconds | ✅ ~2s |
| Mobile Responsive | Yes | ✅ Yes |
| Map Sites Displayed | All 36 | ✅ 36 |
| Chart Types | ≥ 3 | ✅ 4 |
| Accessibility (WCAG) | AA | 🔄 In Progress |

**Branch Pattern:** `ui/*`, `frontend/*`

---

### 4. ML Engineer
**Specialization:** Forecasting Models & Predictive Analytics

| Area | Responsibility | Primary Files | Deliverables |
|------|---------------|---------------|--------------|
| **Model Training** | Train groundwater prediction models | `src/ml/train_groundwater.py` | Trained models |
| **Multi-Horizon Forecasting** | 7, 14, 30 day predictions | `models/*.joblib` | Forecasts |
| **Model Benchmarking** | Compare model performance | `tests/model/` | Metrics reports |
| **Feature Engineering** | Improve prediction inputs | ML pipelines | Better features |

**Required Deliverables (Phase 5):**
- [ ] Multi-horizon forecasting (7, 14, 30 days)
- [ ] R² ≥ 0.90 on all horizons
- [ ] Model confidence intervals
- [ ] Automated retraining pipeline

**Quality Gates (MUST MEET):**
| Metric | Requirement | Current |
|--------|-------------|---------|
| R² Score (7-day) | ≥ 0.90 | ✅ 0.93 |
| R² Score (14-day) | ≥ 0.85 | 🔄 Pending |
| R² Score (30-day) | ≥ 0.80 | 🔄 Pending |
| Model Tests | 100% pass | ✅ 100% |
| Documented Decisions | Yes | ✅ Yes |

**Branch Pattern:** `ml/*`

---

### 5. Research Lead / AI Engineer
**Specialization:** Agent Logic, LLM Integration & Domain Expertise

| Area | Responsibility | Primary Files | Deliverables |
|------|---------------|---------------|--------------|
| **AI Chat Backend** | Natural language query processing | `api/main.py` (chat endpoints) | Chat API |
| **LLM Integration** | Connect to language models | `src/agent/research_agent.py` | Agent logic |
| **Source Verification** | Ensure accurate citations | `src/agent/source_verification.py` | Trust scores |
| **Domain Expertise** | Groundwater-specific prompts | Prompt engineering | Expert responses |
| **Farmer Use Cases** | Agriculture-focused AI responses | `GROUNDWATER_KB` | Farmer guidance |

**Required Deliverables (Phase 5):**
- [ ] Full LLM integration (upgrade from rule-based)
- [ ] RAG-powered responses with citations
- [ ] Farmer-specific knowledge base expansion
- [ ] Site-specific recommendations

**Quality Gates (MUST MEET):**
| Metric | Requirement | Current |
|--------|-------------|---------|
| Chat API Tests | 100% pass | ✅ 17/17 |
| Farmer Use Cases | ≥ 5 topics | ✅ 7 topics |
| Source Attribution | 100% | ✅ Yes |
| Groundwater Relevance | 100% | ✅ Yes |
| Response Time | < 2 seconds | ✅ <1s |

**Branch Pattern:** `agent/*`, `chat/*`

---

### 6. Backend Engineer
**Specialization:** FastAPI & Data Serving

| Area | Responsibility | Primary Files | Deliverables |
|------|---------------|---------------|--------------|
| **API Development** | REST endpoints for data | `api/main.py` | API routes |
| **Data Aggregation** | Serve aggregated statistics | API endpoints | Stats API |
| **Performance** | Optimize query speed | Caching, indexing | Fast responses |
| **Security** | API authentication (future) | Auth middleware | Secure API |

**Required Deliverables (Phase 5):**
- [ ] Paginated data endpoints
- [ ] Multi-site comparison API
- [ ] Trend analysis endpoints
- [ ] Rate limiting (production)

**Quality Gates (MUST MEET):**
| Metric | Requirement | Current |
|--------|-------------|---------|
| API Response Time | < 500ms | ✅ ~200ms |
| Endpoints Documented | 100% | ✅ Yes |
| Error Handling | Graceful | ✅ Yes |
| CORS Configured | Yes | ✅ Yes |

**Branch Pattern:** `api/*`, `backend/*`

---

## 🎯 Specialized Work Areas

### Cross-Functional Requirements

Each role has **primary** and **secondary** responsibilities:

```
┌──────────────────────────────────────────────────────────────────────┐
│                         WORK AREA MATRIX                             │
├────────────────┬─────────┬─────────┬─────────┬─────────┬─────────────┤
│ Area           │ Data    │ KB      │ Frontend│ ML      │ Research    │
│                │ Engineer│ Engineer│ Dev     │ Engineer│ Lead        │
├────────────────┼─────────┼─────────┼─────────┼─────────┼─────────────┤
│ USGS Data      │ PRIMARY │ Review  │ -       │ Consume │ -           │
│ Knowledge Base │ Provide │ PRIMARY │ -       │ -       │ Review      │
│ React UI       │ -       │ -       │ PRIMARY │ -       │ Consult     │
│ ML Models      │ Data    │ -       │ Display │ PRIMARY │ Interpret   │
│ AI Chat        │ -       │ RAG     │ UI      │ -       │ PRIMARY     │
│ API Backend    │ Data    │ -       │ Consume │ Serve   │ Chat Endpt  │
│ Tests          │ Data    │ KB      │ UI      │ Model   │ Agent       │
│ Documentation  │ Data    │ KB      │ UI      │ Model   │ Agent       │
└────────────────┴─────────┴─────────┴─────────┴─────────┴─────────────┘

Legend: PRIMARY = Owner, Review = Code Review, Consume = Use Output
```

---

## 📐 Requirements & Standards

### Coding Standards (ALL ROLES)

| Standard | Requirement | Tool |
|----------|-------------|------|
| **Python Style** | PEP 8 compliant | `flake8` |
| **Python Formatting** | Black formatted | `black .` |
| **Line Length** | ≤ 120 characters | `flake8 --max-line-length=120` |
| **Docstrings** | All functions documented | Google style |
| **Type Hints** | Recommended for public APIs | `mypy` |
| **JavaScript** | ESLint rules | `npm run lint` |

### Testing Requirements (ALL ROLES)

| Type | Requirement | Coverage |
|------|-------------|----------|
| **Unit Tests** | All new functions | ≥ 80% |
| **Integration Tests** | API endpoints | 100% |
| **Accuracy Tests** | KB and ML | Pass/Fail |
| **Pre-commit** | Must pass before commit | `pytest tests/` |

### Documentation Requirements

| Document | Owner | Update Frequency |
|----------|-------|------------------|
| `README.md` | Research Lead | Major releases |
| `DEVELOPMENT_GUIDE.md` | All | When process changes |
| `PROJECT_STATUS.md` | All | Each sprint |
| `ROLES.md` | Research Lead | When roles change |
| `PROJECT_PLAN.md` | Research Lead | Phase transitions |

---

## 🔀 Git Workflow

### Branch Strategy
```
main (protected)
  │
  └── Requires: PR + 1 approval + passing tests + linting
      │
      └── Feature branches by role:
          ├── data/usgs-pipeline-optimization
          ├── data/new-site-validation
          ├── knowledge/rag-integration
          ├── knowledge/accuracy-improvements
          ├── ui/chat-interface-upgrade
          ├── ui/farmer-dashboard
          ├── ml/multi-horizon-forecasting
          ├── ml/confidence-intervals
          ├── agent/llm-integration
          ├── agent/farmer-use-cases
          └── api/pagination-endpoints
```

### Branch Naming
```
<role>/<short-description>

Examples:
  data/add-charlotte-county-sites
  knowledge/improve-retrieval-precision
  ui/mobile-responsive-charts
  ml/30-day-forecast-model
  agent/citrus-irrigation-knowledge
  api/trend-analysis-endpoint
```

### Commit Messages
```
<type>(<scope>): <description>

Types:
  feat     - New feature
  fix      - Bug fix
  docs     - Documentation
  test     - Adding tests
  refactor - Code refactoring
  data     - Data changes
  perf     - Performance improvement

Scopes:
  data, knowledge, ui, ml, agent, api, ci

Examples:
  feat(data): add Charlotte County monitoring sites
  test(knowledge): add RAG retrieval accuracy tests
  fix(ui): resolve chart tooltip on mobile
  feat(agent): add citrus irrigation knowledge base
  perf(api): add response caching for site data
```

---

## 📋 PR Review Process

### Before Creating PR
- [ ] All tests pass locally (`pytest tests/`)
- [ ] No linting errors (`flake8 --max-line-length=120`)
- [ ] Code is formatted (`black .`)
- [ ] Documentation updated if needed
- [ ] No hardcoded secrets or API keys

### PR Requirements
| Requirement | Details |
|-------------|---------|
| Title | `<type>(<scope>): <description>` |
| Description | What, why, how, testing done |
| Tests | New/updated tests included |
| Review | Approved by code owner |
| CI | All checks pass |
| Breaking Changes | Documented if any |

### Code Owners
| Directory | Owner | Reviewer |
|-----------|-------|----------|
| `data/`, `download_data.py` | Data Engineer | Knowledge Engineer |
| `src/agent/knowledge.py`, `knowledge_base/` | Knowledge Engineer | Research Lead |
| `frontend/src/components/` | Frontend Developer | Any |
| `src/ml/`, `models/` | ML Engineer | Data Engineer |
| `src/agent/research_agent.py` | Research Lead | Knowledge Engineer |
| `api/main.py` | Backend Engineer | Research Lead |
| `tests/` | Owner of related code | Any |

---

## 🔄 Change Management

### Addendum Process

**Any changes to roles, requirements, or deliverables MUST follow this process:**

1. **Propose Change**
   - Create a GitHub Issue with label `role-change`
   - Describe: What, Why, Impact

2. **Team Discussion**
   - Tag relevant team members
   - Allow 48 hours for feedback

3. **Document Decision**
   - Update this file with change
   - Add entry to Change Log below

4. **Communicate**
   - Notify team in standup
   - Update PROJECT_STATUS.md

### Change Log

| Date | Change | Reason | Approved By |
|------|--------|--------|-------------|
| 2026-02-04 | v2.0 - Complete restructure | Phase 5 planning | Team |
| 2026-01-16 | v1.0 - Initial roles | Project kickoff | Team |

### Requirement Lock Policy

**The following requirements are LOCKED and require formal team approval to change:**

| Requirement | Value | Locked Until |
|-------------|-------|--------------|
| USGS Sites Minimum | 36 | Phase 6 |
| KB Accuracy | 95% | Phase 6 |
| R² Score (7-day) | 0.90 | Phase 6 |
| Test Pass Rate | 100% | Never |
| Documentation | Required | Never |

---

## 📅 Meeting Cadence

| Meeting | When | Duration | Purpose |
|---------|------|----------|---------|
| Async Standup | Daily | 5 min | Quick status update |
| Sprint Planning | Monday | 30 min | Week's priorities |
| Code Review | As needed | 15 min | PR reviews |
| Advisor Sync | Bi-weekly | 30 min | Guidance & feedback |

### Standup Format (Async in Slack/Discord)
```
Yesterday: [what you completed]
Today: [what you're working on]
Blockers: [any issues]
PR Reviews Needed: [list PRs]
```

---

## 🎯 Current Sprint (Feb 4-10, 2026) - Phase 5 Start

| Role | This Week's Focus | Deliverable | Due |
|------|-------------------|-------------|-----|
| **Data Engineer** | Automated data refresh pipeline | Cron job setup | Feb 7 |
| **Knowledge Engineer** | RAG integration planning | Architecture doc | Feb 7 |
| **Frontend Developer** | Upgrade AI Chat from Beta | Full chat UI | Feb 10 |
| **ML Engineer** | Multi-horizon forecasting (14-day) | Trained model | Feb 10 |
| **Research Lead** | LLM integration research | Provider selection | Feb 7 |
| **Backend Engineer** | Trend analysis API endpoint | `/api/trends` | Feb 10 |

---

## 📎 Appendix: File Ownership Map

```
GroundwaterGPT/
├── api/
│   └── main.py                    → Backend Engineer, Research Lead (chat)
├── config/
│   └── config.py                  → All (shared config)
├── data/
│   └── usgs_*.csv                 → Data Engineer
├── docs/
│   ├── ROLES.md                   → Research Lead
│   ├── PROJECT_PLAN.md            → Research Lead
│   ├── PROJECT_STATUS.md          → All
│   ├── DEVELOPMENT_GUIDE.md       → All
│   └── CHECKLIST.md               → All
├── frontend/
│   └── src/components/
│       ├── MapView.jsx            → Frontend Developer
│       ├── ChatView.jsx           → Frontend Developer
│       ├── TimeSeriesChart.jsx    → Frontend Developer
│       └── Dashboard.jsx          → Frontend Developer
├── knowledge_base/                → Knowledge Engineer
├── models/
│   └── *.joblib                   → ML Engineer
├── src/
│   ├── agent/
│   │   ├── knowledge.py           → Knowledge Engineer
│   │   └── research_agent.py      → Research Lead
│   ├── data/                      → Data Engineer
│   └── ml/                        → ML Engineer
├── tests/
│   ├── data/                      → Data Engineer
│   ├── knowledge/                 → Knowledge Engineer
│   ├── model/                     → ML Engineer
│   └── unit/                      → Owner of related code
└── scripts/                       → Data Engineer
```

---

## ✅ Requirements Summary (Phase 5)

### Non-Negotiable Requirements

These requirements **CANNOT** be changed without team approval:

| Requirement | Standard | Rationale |
|-------------|----------|-----------|
| **Tests Must Pass** | 100% | Code quality |
| **Linting Clean** | 0 errors | Consistency |
| **Documentation** | All features | Maintainability |
| **USGS Verification** | All sites | Data integrity |
| **PR Review** | Required | Quality control |

### Flexible Requirements (Discuss Before Changing)

| Requirement | Current | Can Adjust If |
|-------------|---------|---------------|
| USGS Sites | 36 | New region added |
| R² Score Threshold | 0.90 | Data limitations |
| KB Documents | 1,901 | Quality over quantity |
| Response Time | <500ms | Complex queries |

---

*For detailed timeline and phase planning, see [PROJECT_PLAN.md](PROJECT_PLAN.md)*
*For current progress, see [PROJECT_STATUS.md](PROJECT_STATUS.md)*
*For development setup, see [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)*
