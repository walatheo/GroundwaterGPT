# Team Roles & Responsibilities

**Last Updated:** January 16, 2026

This document defines team roles, responsibilities, and workflows for clean collaboration.

---

## 👥 Role Definitions

### 1. Data Engineer
**Focus:** USGS data collection, validation, and benchmarking

| Responsibility | Files | Branch Pattern |
|---------------|-------|----------------|
| Fetch USGS groundwater data | `continuous_learning.py` | `data/*` |
| Validate data quality | `download_data.py` | |
| Create benchmark tests | `tests/data/test_benchmarks.py` | |
| Manage data storage | `data/*.csv` | |

**Key Metrics:**
- Data passes all benchmark tests
- 20+ USGS sites with 10+ years of data
- No impossible or outlier values

---

### 2. Knowledge Engineer
**Focus:** Knowledge base accuracy, testing, and optimization

| Responsibility | Files | Branch Pattern |
|---------------|-------|----------------|
| Maintain ChromaDB | `agent/knowledge.py` | `knowledge/*` |
| Test retrieval accuracy | `tests/knowledge/test_accuracy.py` | |
| Optimize embeddings | `chroma_db/` | |
| Create ground truth tests | `tests/data/ground_truth.json` | |

**Key Metrics:**
- 95%+ query precision
- Zero duplicate documents
- 50+ ground truth Q&A pairs

---

### 3. UI/UX Developer
**Focus:** Streamlit interface and visualization integration

| Responsibility | Files | Branch Pattern |
|---------------|-------|----------------|
| Main research interface | `research_chat.py` | `ui/*` |
| Dashboard integration | `dashboard.py` | |
| Visualization components | `app.py` | |
| User experience | CSS/styling | |

**Key Metrics:**
- All visualizations in Streamlit
- Page load < 3 seconds
- Mobile-responsive design

---

### 4. ML Engineer
**Focus:** Forecasting models and performance validation

| Responsibility | Files | Branch Pattern |
|---------------|-------|----------------|
| Train prediction models | `train_groundwater.py` | `ml/*` |
| Model benchmarking | `tests/model/` | |
| Feature engineering | Model pipelines | |
| Performance optimization | `models/` | |

**Key Metrics:**
- R² ≥ 0.90 for predictions
- Model validation tests pass
- Documented model decisions

---

### 5. Research Lead
**Focus:** Agent logic, domain expertise, and source verification

| Responsibility | Files | Branch Pattern |
|---------------|-------|----------------|
| Research agent logic | `agent/research_agent.py` | `agent/*` |
| Source verification | `agent/source_verification.py` | |
| Groundwater domain focus | Prompt engineering | |
| Quality oversight | Code reviews | |

**Key Metrics:**
- 100% groundwater-relevant KB content
- Agent passes hydrogeology questions
- Proper source citations

---

## 🔀 Git Workflow

### Branch Strategy
```
main (protected)
  │
  └── Requires: PR + 1 approval + passing tests
      │
      └── Feature branches by role:
          ├── data/usgs-expansion
          ├── data/benchmark-tests
          ├── knowledge/accuracy-tests
          ├── knowledge/dedup
          ├── ui/viz-integration
          ├── ui/mobile-responsive
          ├── ml/model-validation
          └── agent/groundwater-focus
```

### Branch Naming
```
<role>/<short-description>

Examples:
  data/add-miami-dade-sites
  knowledge/fix-duplicate-chunks
  ui/add-site-selector
  ml/improve-forecast-accuracy
  agent/optimize-prompts
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

Scopes:
  data, knowledge, ui, ml, agent, ci

Examples:
  feat(data): add 15 new USGS monitoring sites
  test(knowledge): add accuracy tests for aquifer queries
  fix(ui): resolve chart rendering on mobile
  docs(agent): document prompt engineering decisions
```

---

## 📋 PR Review Process

### Before Creating PR
- [ ] All tests pass locally (`pytest tests/`)
- [ ] No linting errors (`flake8`)
- [ ] Code is formatted (`black .`)
- [ ] Documentation updated if needed

### PR Requirements
| Requirement | Details |
|-------------|---------|
| Title | `<type>(<scope>): <description>` |
| Description | What, why, how |
| Tests | New/updated tests included |
| Review | Approved by code owner |
| CI | All checks pass |

### Code Owners
| Directory | Owner | Reviewer |
|-----------|-------|----------|
| `data/`, `continuous_learning.py` | Data Engineer | Knowledge Engineer |
| `agent/knowledge.py`, `chroma_db/` | Knowledge Engineer | Research Lead |
| `research_chat.py`, `dashboard.py` | UI/UX Developer | Any |
| `train_groundwater.py`, `models/` | ML Engineer | Data Engineer |
| `agent/research_agent.py` | Research Lead | Knowledge Engineer |

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
```

---

## 🎯 Current Sprint (Jan 16-22)

| Role | This Week's Focus |
|------|-------------------|
| Data Engineer | Create benchmark tests, validate existing data |
| Knowledge Engineer | Document KB accuracy requirements |
| UI/UX Developer | Plan visualization integration |
| ML Engineer | Review model performance metrics |
| Research Lead | Define groundwater expertise criteria |

---

*For detailed timeline, see [PROJECT_PLAN.md](PROJECT_PLAN.md)*
