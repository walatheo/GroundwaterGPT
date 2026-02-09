# GroundwaterGPT - Active Checklist & Goals

**Last Updated:** February 4, 2026
**Current Phase:** Phase 5 - AI Research Integration
**Sprint:** Feb 4-10, 2026

---

## 📋 Quick Status

| Component | Status | Tests | Notes |
|-----------|--------|-------|-------|
| **Data Pipeline** | ✅ Complete | 26/26 | 36 USGS sites, 106K records |
| **Knowledge Base** | ✅ Complete | 31/31 | 1,901 documents |
| **React Dashboard** | ✅ Complete | - | Map, charts, heatmaps |
| **FastAPI Backend** | ✅ Complete | - | REST API on :8000 |
| **AI Chat (Beta)** | ✅ Complete | 17/17 | Rule-based responses |
| **ML Models** | ✅ Complete | - | R² = 0.93 (7-day) |

**Total Tests:** 89 passing, 4 skipped

---

## 🎯 Phase Goals

### ✅ Phase 1-4: COMPLETED

| Phase | Goals Achieved | Key Deliverables |
|-------|---------------|------------------|
| **1. Foundation** | Data pipeline, ML model | `download_data.py`, R²=0.93 |
| **2. Quality** | CI/CD, testing | 80%+ coverage, GitHub Actions |
| **3. Data Expansion** | 36 sites, 106K records | 5 counties covered |
| **4. Dashboard** | React UI, AI Chat Beta | Interactive map, chat |

### 🔄 Phase 5: AI Research Integration (CURRENT)

**Success Criteria - ALL must pass before Phase 6:**

| Goal | Target | Current | Status |
|------|--------|---------|--------|
| **G5.1** LLM Connected | Yes | No | ⏳ |
| **G5.2** RAG Precision | ≥90% | - | ⏳ |
| **G5.3** Source Citations | 100% | - | ⏳ |
| **G5.4** Hallucination Rate | <5% | - | ⏳ |
| **G5.5** Farmer KB Topics | ≥10 | 7 | 🔄 |
| **G5.6** Response Time | <3s | <1s | ✅ |

---

## 📅 Current Sprint (Feb 4-10)

### Priority 1: Research Integrity ✅
- [x] Create ENGINEERING_STANDARDS.md
- [x] Create USGS data integrity tests (13 tests)
- [x] Consolidate documentation (7 → 4 files)
- [x] Clean unused files from repo

### Priority 2: AI Assistant Upgrade
- [ ] Integrate LLM for natural language queries
- [ ] Connect RAG to chat endpoint
- [ ] Add source citations to responses
- [ ] Expand farmer knowledge base

### Priority 3: Testing
- [ ] Write RAG accuracy tests BEFORE implementation
- [ ] Add hallucination detection tests
- [ ] Ensure all existing tests pass

---

## 🧪 Testing Standards

### Before Marking Any Task Complete

- [ ] Unit tests written (if applicable)
- [ ] All existing tests still pass
- [ ] Code reviewed
- [ ] Documentation updated
- [ ] No linting errors

### Test Philosophy

> **NEVER modify a test just to make it pass.**
>
> If a test fails:
> 1. Understand WHY it fails
> 2. Fix the ROOT CAUSE
> 3. Document what was learned

---

## 📁 Project Structure

```
GroundwaterGPT/
├── api/main.py              # FastAPI backend (active)
├── frontend/                # React dashboard (active)
│   └── src/components/      # UI components
├── src/
│   ├── agent/               # AI research agent
│   ├── data/                # Data pipeline
│   └── ml/                  # ML models
├── data/                    # 36 USGS CSV files
├── tests/                   # 89+ tests
└── docs/                    # 4 documentation files
    ├── CHECKLIST.md         # ← You are here
    ├── DEVELOPMENT_GUIDE.md # Complete dev guide + roles
    ├── ENGINEERING_STANDARDS.md # Code quality rules
    └── SPONSOR_SUMMARY.md   # Executive overview
```

---

## 👥 Role Quick Reference

| Role | Primary Focus | Key Files |
|------|--------------|-----------|
| **Data Engineer** | USGS pipeline | `src/data/`, `data/` |
| **Knowledge Engineer** | RAG, ChromaDB | `src/agent/knowledge.py` |
| **Frontend Developer** | React UI | `frontend/src/` |
| **ML Engineer** | Forecasting | `src/ml/` |
| **Research Lead** | AI chat, LLM | `src/agent/`, `api/` |

*Full role details in [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)*

---

## 📈 Progress Tracking

```
Phase 1: ████████████ 100% ✅ Foundation
Phase 2: ████████████ 100% ✅ Quality
Phase 3: ████████████ 100% ✅ Data Expansion
Phase 4: ████████████ 100% ✅ Dashboard
Phase 5: ██░░░░░░░░░░  15% 🔄 AI Research
Phase 6: ░░░░░░░░░░░░   0% ⏳ Multi-Horizon ML
Phase 7: ░░░░░░░░░░░░   0% ⏳ Production
```

---

## ✅ Quick Commands

```bash
# Run all tests
pytest tests/ -v

# Check code quality
flake8 src/ api/ tests/ --max-line-length=120
black --check src/ api/ tests/

# Start development servers
cd frontend && npm run dev          # Port 3000
cd api && uvicorn main:app --reload # Port 8000
```

---

*Last sprint completed: Feb 4, 2026 (Documentation consolidation)*

---

## 🧠 AI Chat Evaluation Goals

These benchmark questions define the performance targets for GroundwaterGPT's AI chat.
The system must answer these reproducibly with cited USGS wells and correct aquifer units.

### Level 1 — Single-Task Quantitative Trend (Easy)

**Benchmark Question:**
> *"What has been the change in groundwater level in Estero over the last 30 years?"*

**Required capabilities:**
- [ ] Identify relevant USGS monitoring wells near Estero (site ID, borehole code, aquifer name, geographic coordinates)
- [ ] Retrieve groundwater-level records for ~30 years (explicit data source statement, actual time period used e.g. 1994-01-10 to 2024-12-31)
- [ ] Produce a time series plot based on real data
- [ ] Summarize trend (declining / stable / rising)
- [ ] Compute net change (decline or rise) with relative magnitude (small vs. substantial)
- [ ] Separate results by aquifer (if more than one aquifer unit exists, provide answer for each)

**Success Criterion:** Answer must be reproducible using the cited wells, including correct well identification based on coordinates.

### Level 2 — Multi-Source Synthesis (Hard)

**Benchmark Question:**
> *"What are the groundwater sources the Village of Estero uses for water supply and what have been changes in groundwater levels there over the last 30 years?"*

**Required capabilities:**
- [ ] Identify which aquifers are actually used for supply (name specific units: Lower Tamiami, Hawthorn Group, Upper Floridan; acknowledge uncertainty if documentation is incomplete)
- [ ] Identify which monitoring wells represent those aquifers (which USGS wells, why they are appropriate proxies, limitations such as distance or depth mismatch)
- [ ] Evaluate trends within each specific aquifer (same as Level 1 requirements)
- [ ] Synthesize results across multiple units:
  - Direction of change in each unit
  - Compare trends across aquifers (which sources are most stressed)
  - Discuss shallow vs. deep system differences (e.g., shallow = high seasonal variability, deeper = smoother but persistent decline)
- [ ] Discuss implications (sustainability, saltwater intrusion risk, extensive drawdown, etc.)

**Success Criterion:** Answer must be reproducible using the cited wells, including correct aquifer units and well identification based on coordinates.

### Evaluation Rubric

| Dimension | Level 1 Target | Level 2 Target |
|-----------|---------------|----------------|
| **Well Identification** | Correct site IDs + coords | Correct + aquifer-appropriate |
| **Data Period** | Stated explicitly | Stated explicitly |
| **Trend Analysis** | Direction + magnitude | Per-aquifer + comparison |
| **Citations** | USGS well IDs cited | Wells + aquifer units cited |
| **Reproducibility** | Fully reproducible | Fully reproducible |
| **Implications** | Not required | Required (sustainability, risk) |
