# GroundwaterGPT - Project Status & Roadmap

**Last Updated:** March 16, 2026
**Location:** Florida (Miami-Dade, Lee, Collier, Sarasota, Hendry Counties)
**Data Source:** USGS National Water Information System (NWIS) - Verified Authentic

---

## 📍 Current Status - Phase 5 In Progress 🔄

### System Overview

| Component | Technology | Status |
|-----------|------------|--------|
| **Frontend** | React 18 + Vite + Tailwind CSS | ✅ Running |
| **Backend API** | FastAPI + uvicorn | ✅ Running |
| **Data Source** | USGS NWIS (36 sites) | ✅ Verified |
| **Knowledge Base** | ChromaDB (1,901 docs) | ✅ Active |
| **ML Models** | scikit-learn (R² = 0.93) | ✅ Trained |
| **Local LLM Runtime** | Ollama (`qwen3:8b`) | ✅ Default configured |

---

## 📊 Data Coverage

### USGS Monitoring Sites: 36 Total

| County | Sites | Aquifer Type |
|--------|-------|--------------|
| **Miami-Dade** | 16 | Biscayne Aquifer |
| **Lee (Fort Myers)** | 7 | Floridan Aquifer (L-2194, L-581, L-1999, etc.) |
| **Collier (Naples)** | 5 | SW Florida Aquifer (C-951R, C-953R, etc.) |
| **Sarasota** | 4 | Floridan Aquifer |
| **Hendry** | 4 | Floridan Aquifer (HE-1042, HE-859, etc.) |

### Data Verification ✅

| Check | Status |
|-------|--------|
| USGS API confirmation | ✅ All 36 sites verified |
| Site IDs match official database | ✅ Confirmed |
| Values match API responses | ✅ Verified |
| **Total Records** | **106,628** |

---

## 🏗️ Architecture

### Stack Components

```
┌─────────────────────────────────────────────────────────────┐
│                    FRONTEND (React)                         │
│  http://localhost:3000                                      │
│  ├── MapView.jsx      - Leaflet interactive map            │
│  ├── TimeSeriesChart  - Recharts with trend analysis       │
│  ├── HeatmapChart     - Monthly/yearly patterns            │
│  ├── AnalysisView     - Statistics & seasonal patterns     │
│  └── Sidebar          - Site selector (36 sites)           │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTP API
┌─────────────────────▼───────────────────────────────────────┐
│                    BACKEND (FastAPI)                        │
│  http://localhost:8000                                      │
│  ├── /api/sites           - List all 36 USGS sites         │
│  ├── /api/sites/{id}/data - Time series data               │
│  ├── /api/sites/{id}/heatmap - Monthly averages            │
│  └── /api/compare         - Multi-site comparison          │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    DATA LAYER                               │
│  data/usgs_*.csv (36 files, 106,628 records)               │
│  - Fetched from official USGS NWIS API                     │
│  - Daily groundwater level measurements                     │
│  - Depth to water (feet below land surface)                │
└─────────────────────────────────────────────────────────────┘
```

---

## ✅ Completed Phases

### Phase 1: Foundation ✅
- [x] USGS data pipeline
- [x] ML prediction model (Gradient Boosting, R² = 0.93)
- [x] ChromaDB knowledge base
- [x] Initial dashboard (Plotly HTML)

### Phase 2: Quality Infrastructure ✅
- [x] CI/CD Pipeline (GitHub Actions)
- [x] Test suite (32 tests passing)
- [x] Pre-commit hooks
- [x] Development guide

### Phase 3: Visualization Upgrade ✅
- [x] React frontend with Vite
- [x] Tailwind CSS styling
- [x] Interactive Leaflet map
- [x] Recharts time series
- [x] Heatmap visualization
- [x] FastAPI backend

### Phase 4: Data Expansion & Accuracy ✅ (Current)
- [x] Expanded from 6 → 36 USGS sites
- [x] Added SW Florida (Lee, Collier, Sarasota, Hendry)
- [x] Data verification against USGS API
- [x] Knowledge base accuracy tests (31/31 passing)
- [x] Documentation updates

---

## 🎯 User Types & Use Cases

### 1. 🔬 Researcher / Scientist
**Goal:** Analyze groundwater trends, validate hypotheses

**Features:**
- Time series analysis with trend lines
- Seasonal pattern visualization
- Multi-site comparison
- Export data for further analysis

**Typical Workflow:**
1. Select monitoring site from map
2. Review long-term trends
3. Compare seasonal patterns
4. Export data for statistical analysis

---

### 2. 🏛️ Government / Water Manager
**Goal:** Monitor aquifer health, plan water resources

**Features:**
- Real-time water level monitoring
- Historical trend analysis
- Multi-county view
- Anomaly detection

**Typical Workflow:**
1. View regional map of all sites
2. Identify sites with declining levels
3. Review historical patterns
4. Generate reports for stakeholders

---

### 3. 🎓 Student / Educator
**Goal:** Learn about groundwater systems, teaching

**Features:**
- Visual exploration of aquifer data
- Interactive maps
- Clear visualizations
- Access to verified USGS data

**Typical Workflow:**
1. Explore Florida aquifer map
2. Select site to study
3. Analyze seasonal patterns
4. Compare different aquifer types

---

### 4. 🌾 Agricultural / Private Well Owner
**Goal:** Understand local groundwater conditions

**Features:**
- Find nearby monitoring sites
- View current water levels
- Seasonal patterns for planning
- Historical context

**Typical Workflow:**
1. Locate nearest USGS monitoring site
2. Check current groundwater levels
3. Review seasonal patterns for irrigation planning
4. Track year-over-year changes

---

## 🚀 Active Development Plan

### Sprint 1 (Current): Operational Hardening
- [x] Knowledge ingestion pipeline + API endpoints added
- [x] Research workflow tools added (plan, run logging, paper draft)
- [x] Full test suite stabilized for local data artifacts
- [x] Runtime readiness endpoint for KB dependency/storage health
- [x] Graceful 503 handling for missing embedding runtime dependencies

### Sprint 2: Research Workflow Productization
- [x] Expose experiment workflows to frontend/API users end-to-end
- [x] Add reproducibility schema checks for run configs and metrics
- [x] Persist manuscript provenance and citations in generated drafts

### Sprint 3: Quality & Citation Integrity
- [x] Add evaluation harness for retrieval/report quality in CI
- [x] Add structured claim-to-source citation output
- [x] Set minimum quality thresholds before production rollout
- [x] Expand benchmark question corpus to 30+ deterministic research cases

### Sprint 4: Live-Agent Quality Gating ✅ COMPLETE
- [x] Add `fallback/live/both` benchmark execution modes
- [x] Add optional live-mode CI gate (`ENFORCE_LIVE_CHAT_THRESHOLDS`)
- [x] Add section-level confidence + trust metadata in research output
- [x] Add citation integrity checks (claim + section coverage) in API responses
- [x] Add guardrail filtering for uncited factual sentences in synthesized reports
- [x] Add retrieval precision benchmark + optional CI enforcement
- [x] Add claim disagreement engine (`claim_verdicts`) with adversarial contradiction checks
- [x] Add claim-verdict summary metadata and benchmark coverage/risk thresholds
- [x] Wire `ClaimDisagreementEngine` into `DeepResearchAgent` output
- [x] Wire claim verdicts + summary into fallback API route
- [x] Fix sys.path import hacks → canonical `src.*` imports in API layer
- [x] Update Anthropic model IDs to Claude 4.x generation in `llm_factory.py`

### Sprint 5: Multi-Agent Research Architecture (CURRENT — Mar 16–23, 2026)
- [ ] Design orchestrator-worker protocol: `LeadResearcher` dispatches typed tasks to `SubAgent`s
- [ ] Implement `SubAgent` with task types: search / summarize / verify
- [ ] Add planner/reflection/checkpoint loop for long-running research
- [ ] Add budget-aware controls (max_depth, max_tokens, timeout) per research plan
- [ ] Add contradiction-aware synthesis — surface disagreements explicitly in final reports
- [ ] Expose `claim_verdict_summary` in frontend research view
- [ ] Validate multi-agent output using L2 benchmark questions

### Sprint 6: Production Deployment
- [ ] Cloud deployment + observability + alerts
- [ ] Health probes for API, KB, and model runtime
- [ ] Public-facing reliability and onboarding polish

---

## 📈 Key Metrics

| Metric | Value |
|--------|-------|
| USGS Sites | 36 |
| Total Records | 106,628 |
| ML Model R² | 0.93 |
| KB Documents | 1,901 |
| Test Coverage | 32+ tests |
| Counties Covered | 5 |

---

## 📚 Documentation

- [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) - Coding standards, architecture
- [DELIVERABLE_PLAN.md](DELIVERABLE_PLAN.md) - Depth-first deliverable scope + acceptance criteria
- [PROJECT_PLAN.md](PROJECT_PLAN.md) - Timeline & milestones
- [ROLES.md](ROLES.md) - Team responsibilities
- [CHECKLIST.md](CHECKLIST.md) - Review checklist

---

## 🔗 Quick Start

### Start the Application

```bash
# Terminal 1: Start API
cd GroundwaterGPT/api
uvicorn main:app --reload --port 8000

# Terminal 2: Start Frontend
cd GroundwaterGPT/frontend
npm run dev
```

**Access:**
- Frontend: http://localhost:3000
- API: http://localhost:8000/api/sites

---

## 📖 Data Citation

```
U.S. Geological Survey, 2026
National Water Information System data available on the World Wide Web
(USGS Water Data for the Nation)
https://waterdata.usgs.gov/nwis/
```

---

*Last updated: February 3, 2026*
