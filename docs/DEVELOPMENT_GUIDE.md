# GroundwaterGPT Development Guide

**Last Updated:** February 27, 2026
**Purpose:** Engineering specification for an agentic deep-research platform for groundwater science, built on verified USGS data, modular AI agents, and interactive data visualization.

**Core Goals:**
1. **Agentic Deep Research** — An AI research agent that iteratively searches, synthesizes, and verifies groundwater information across local knowledge, web sources, and live USGS data
2. **Interactive Data Visualization** — React dashboard with time series plots, heatmaps, and map views driven by direct USGS API queries
3. **Modular, Extensible Architecture** — Cleanly separated layers (Presentation, Agent, Knowledge, Verification, Data/ML) so each can evolve independently
4. **Research Integrity** — Every claim is source-verified; every data point traces back to USGS or peer-reviewed literature

> **References:** Architecture patterns informed by:
> - [Awesome-Deep-Research](https://github.com/DavidZWZ/Awesome-Deep-Research) — survey of 60+ agentic search systems (Zhang et al., 2025)
> - [Anthropic Multi-Agent Research System](https://www.anthropic.com/engineering/built-multi-agent-research-system) — orchestrator-worker production architecture
> - 35+ domain-specific papers in `resources/pdfs/references/` covering environmental AI, scientific agents, LLM dashboards, and FAIR data principles

---

## 📋 Table of Contents

1. [System Architecture](#-system-architecture)
2. [Technology Stack](#-technology-stack)
3. [User Types & Use Cases](#-user-types--use-cases)
4. [Project Roles](#-project-roles)
5. [Modular Development Sessions](#-modular-development-sessions)
6. [Code Quality Standards](#-code-quality-standards)
7. [CI/CD Pipeline](#-cicd-pipeline)
8. [Data Engineering Best Practices](#-data-engineering-best-practices)
9. [Testing & Benchmarking Strategy](#-testing--benchmarking-strategy)
10. [Quick Start Guide](#-quick-start-guide)
11. [Future Research Directions](#-future-research-directions)

---

## 🏗️ System Architecture

### Design Principles

| Principle | Application |
|-----------|-------------|
| **Modularity** | Each layer has a single responsibility with well-defined interfaces |
| **Efficiency** | Local-first LLM (Ollama), cached embeddings, incremental data updates |
| **Usability** | React UI for visual exploration, natural-language chat for research |
| **Verifiability** | Every response cites sources; trust scores are transparent |

### Layered Architecture

The system is organized into five layers. Data flows downward for queries and upward for responses. Each layer is independently deployable and testable.

```
┌──────────────────────────────────────────────────────────────┐
│                   1. PRESENTATION LAYER                      │
│                                                              │
│  React Dashboard (localhost:3000)                            │
│  ├── MapView.jsx        — Leaflet interactive map (36 sites) │
│  ├── TimeSeriesChart    — Recharts with trend lines          │
│  ├── HeatmapChart       — Monthly/yearly patterns            │
│  ├── AnalysisView       — Statistics & seasonal analysis     │
│  ├── ChatView.jsx       — Research chat interface            │
│  └── Sidebar            — Site selector + mode toggle        │
│                                                              │
│  Streamlit Research UI (localhost:8502)                       │
│  └── research_chat.py   — Query Mode + Deep Research Mode    │
│                                                              │
│  FastAPI (localhost:8000)                                     │
│  ├── GET /api/sites              — List all USGS sites       │
│  ├── GET /api/sites/{id}/data    — Time series data          │
│  ├── GET /api/sites/{id}/heatmap — Monthly averages          │
│  ├── GET /api/compare            — Multi-site comparison     │
│  ├── POST /api/chat              — Agent chat endpoint       │
│  ├── POST /api/research          — Deep research endpoint    │
│  ├── POST /api/research/plans    — Create experiment plan    │
│  └── POST /api/research/plans/{id}/runs — Log experiment run │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                    2. AGENT LAYER                             │
│                                                              │
│  research_agent.py   — Deep Research Agent                   │
│  ├── Iterative search with configurable depth (default: 3)   │
│  ├── Query optimization via LLM                              │
│  ├── Multi-source search (KB + web + USGS API)               │
│  ├── Insight extraction with confidence scoring              │
│  └── Follow-up query generation + report synthesis           │
│                                                              │
│  groundwater_agent.py — Conversational Agent                 │
│  ├── Intent detection (prediction, seasonal, quality, etc.)  │
│  ├── Simple RAG mode (small models) / ReAct mode (GPT-4+)   │
│  └── Streaming chat with history                             │
│                                                              │
│  llm_factory.py — Swappable LLM Providers                   │
│  └── Ollama (local) | OpenAI | Anthropic | Gemini            │
│                                                              │
│  tools.py — Groundwater Analysis Tools                       │
│  ├── query_groundwater_data()     — USGS data querying       │
│  ├── get_water_level_prediction() — ML-based forecasts       │
│  ├── analyze_seasonal_patterns()  — Wet/dry season analysis  │
│  ├── detect_anomalies()           — Z-score outlier detection │
│  └── get_data_quality_report()    — Completeness & gaps      │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                   3. KNOWLEDGE LAYER                          │
│                                                              │
│  knowledge.py — ChromaDB + HuggingFace Embeddings            │
│  ├── 1,901 document chunks (PDFs + USGS data + research)     │
│  ├── BAAI/bge-small-en-v1.5 embeddings (384 dim)            │
│  ├── Semantic search with similarity threshold               │
│  └── Auto-learning: saves verified insights back to KB       │
│                                                              │
│  continuous_learning.py — Live Data Collection                │
│  ├── 40+ Florida aquifer monitoring sites                    │
│  └── Incremental USGS data updates                           │
│                                                              │
│  resources/pdfs/ — Reference Documents                       │
│  ├── Hydrogeology glossary                                   │
│  ├── Surface & near-surface brines and evaporite minerals    │
│  ├── Age dating young groundwater                            │
│  └── (Future research documents added here)                  │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                  4. VERIFICATION LAYER                        │
│                                                              │
│  source_verification.py — Whitebox Trust Scoring             │
│  ├── USGS / NOAA (numerical data)        → 1.0  VERIFIED    │
│  ├── Peer-reviewed journals (DOI)        → 0.95 VERIFIED    │
│  ├── Government reports (.gov, EPA)      → 0.9  VERIFIED    │
│  ├── Academic institutions (.edu)        → 0.85 TRUSTED     │
│  ├── General references (Wikipedia)      → 0.7  MODERATE    │
│  └── Unknown / blogs / social media      → 0.0  UNTRUSTED   │
│                                                              │
│  Rules: Reject sources below 0.6 | Prioritize numerical     │
│  data > research papers > government > academic              │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                 5. DATA & ML LAYER                            │
│                                                              │
│  USGS NWIS API (live)                                        │
│  ├── 36 monitoring sites across 5 Florida counties           │
│  ├── 106,628 verified records                                │
│  └── Direct API queries for real-time data                   │
│                                                              │
│  ML Models (scikit-learn)                                    │
│  ├── 7-day water level prediction (R² = 0.93)               │
│  ├── Feature engineering with leakage prevention             │
│  └── Seasonal pattern analysis                               │
│                                                              │
│  Data files: data/usgs_*.csv (36 sites)                      │
│  Models: models/*.joblib                                     │
└──────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
GroundwaterGPT/
├── api/                          # FastAPI backend
│   ├── main.py                   #   REST API endpoint registration
│   └── routes/research_workflow.py # Research plan/run/draft endpoints
├── frontend/                     # React frontend (Vite + Tailwind)
│   ├── src/
│   │   ├── App.jsx               #   Main application shell
│   │   ├── api/client.js         #   API client (axios)
│   │   └── components/           #   UI components (Map, Charts, Chat, etc.)
│   ├── package.json
│   └── vite.config.js
├── src/                          # Python source code
│   ├── agent/                    #   AI agent layer
│   │   ├── research_agent.py     #     Deep Research Agent (iterative search)
│   │   ├── groundwater_agent.py  #     Conversational agent (RAG + ReAct)
│   │   ├── llm_factory.py        #     LLM provider factory (Ollama/OpenAI/etc.)
│   │   ├── tools.py              #     Groundwater analysis tools
│   │   ├── knowledge.py          #     ChromaDB knowledge base
│   │   └── source_verification.py#     Source trust scoring
│   ├── data/                     #   Data pipelines
│   │   ├── download_data.py      #     USGS data acquisition
│   │   └── continuous_learning.py#     Live data collection & KB updates
│   ├── ml/                       #   Machine learning
│   │   └── train_groundwater.py  #     Model training & feature engineering
│   └── ui/                       #   Streamlit UIs (research chat, dashboard)
│       ├── research_chat.py      #     Deep research chat interface
│       ├── chat_app.py           #     Simple chat interface
│       ├── integrated_app.py     #     Full integrated app
│       └── visualization.py      #     Plotly visualizations
├── tests/                        # Test suite
│   ├── unit/                     #   Unit tests (features, chat API)
│   ├── data/                     #   Data quality & USGS integrity tests
│   ├── model/                    #   ML performance tests
│   └── knowledge/                #   Florida accuracy ground truth tests
├── config/                       # Configuration
│   ├── config.py                 #   App configuration
│   ├── requirements.txt          #   Python dependencies
│   └── .env.example              #   Environment variable template
├── resources/pdfs/               # Reference documents (hydrogeology)
├── knowledge_base/               # ChromaDB persistent vector store
├── models/                       # Trained model artifacts (.joblib)
├── docs/                         # Project documentation
└── main.py                       # CLI entry point
```

---

## 🛠️ Technology Stack

### Frontend (Presentation Layer)
| Technology | Version | Purpose |
|------------|---------|---------|
| React | 18.2.0 | UI framework — dashboard + chat interface |
| Vite | 5.0.0 | Fast build tool with HMR |
| Tailwind CSS | 3.3.5 | Utility-first styling |
| Recharts | 2.10.0 | Time series charts, bar charts |
| Leaflet | 1.9.4 | Interactive maps (USGS site locations) |
| react-leaflet | 4.2.1 | React bindings for Leaflet |

### Backend (API + Agent Layer)
| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.11+ | Runtime |
| FastAPI | ≥0.109.1 | REST API + WebSocket for chat |
| uvicorn | ≥0.24.0 | ASGI server |
| LangChain | ≥0.3.81 | Agent framework (tools, chains, graphs) |
| LangGraph | ≥0.0.1 | Stateful agent graph execution |
| Ollama | local | Default LLM provider (llama3.2, qwen2.5) |

### Knowledge & Verification
| Technology | Purpose |
|------------|---------|
| ChromaDB | Persistent vector store (1,901 chunks) |
| HuggingFace Embeddings | BAAI/bge-small-en-v1.5 (384 dim) |
| DuckDuckGo Search | Web search fallback for deep research |
| Source Verification Engine | Whitebox trust scoring (custom) |

### Data & ML
| Technology | Purpose |
|------------|---------|
| USGS NWIS API | Live groundwater data source (36 sites) |
| pandas | Data processing & analysis |
| scikit-learn | ML models (Ridge Regression, Gradient Boosting) |
| joblib | Model serialization |
| Plotly | Server-side visualization |

### Streamlit (Legacy/Research UI)
| Technology | Purpose |
|------------|---------|
| Streamlit | Research chat UI (localhost:8502) |

---

## 👤 User Types & Use Cases

Each user type maps to specific agent capabilities and UI flows. The research agent must handle all of these naturally through conversational interaction.

### 1. 🔬 Researcher / Scientist

**Goal:** Analyze groundwater trends, validate hypotheses, deep-dive research

**Key Interactions:**
- Time series analysis with trend lines and rolling averages
- Deep research mode: multi-step investigation with source citations
- Multi-site comparison and statistical analysis
- Data export for external analysis

**Example Queries:**
```
"What are the long-term trends for Biscayne Aquifer sites?"
"Compare water levels in Miami-Dade vs Collier County over the last 5 years"
"What does the literature say about saltwater intrusion in Southeast Florida?"
```

**Agent Flow:** Query → Deep Research Agent (depth=3) → KB + Web + USGS API → Synthesis with citations

---

### 2. 🏛️ Government / Water Manager

**Goal:** Monitor aquifer health, plan water resources, generate reports

**Key Interactions:**
- Regional overview map with anomaly highlighting
- Automated trend reports with confidence intervals
- Multi-county dashboard view
- Alert on declining water levels

**Example Queries:**
```
"Which sites show declining water levels this quarter?"
"Generate a summary report of aquifer health for Hendry County"
"Are there any anomalies in the last 30 days?"
```

**Agent Flow:** Query → Intent Detection → Tools (anomaly, quality report) → Formatted report

---

### 3. 🎓 Student / Educator

**Goal:** Learn about groundwater systems, explore data visually

**Key Interactions:**
- Interactive Florida map exploration
- Visual comparison of aquifer types
- Natural language Q&A about hydrogeology concepts
- Access to verified reference documents

**Example Queries:**
```
"What is the difference between the Biscayne and Floridan aquifers?"
"Show me seasonal patterns for site L-2194"
"How does groundwater recharge work in Florida?"
```

**Agent Flow:** Query → KB semantic search → Reference documents → Clear explanation with sources

---

### 4. 🌾 Agricultural / Private Well Owner

**Goal:** Understand local groundwater conditions for irrigation and crop planning

**Key Interactions:**
- Find nearest monitoring sites on map
- Seasonal patterns for irrigation scheduling
- Crop suitability based on water availability
- Year-over-year trend tracking

**Example Queries:**
```
"What is a good crop to grow in this area given the water table?"
"When is the best time to irrigate in Lee County?"
"How have water levels near Fort Myers changed over the past 3 years?"
```

**Agent Flow:** Query → USGS data tools + KB search → Seasonal analysis → Practical recommendation with data backing

---

## 👥 Project Roles

### Role Definitions

Four key roles ensure comprehensive coverage from data to deployment.

---

### 1. 📊 Data Engineer

**Focus:** Data acquisition, pipeline reliability, USGS API integration, feature engineering

**Key Responsibilities:**
- Maintain USGS data download pipeline (`src/data/download_data.py`)
- Implement direct USGS API query tools for the agent layer
- Data quality validation and schema enforcement
- Feature engineering for ML models (leakage prevention)
- Continuous learning pipeline (`src/data/continuous_learning.py`)

**Key Files:** `src/data/`, `config/config.py`, `tests/data/`

**Quality Gates:**
- [ ] All data tests pass (`pytest tests/data/`)
- [ ] No data gaps > 7 days in time series
- [ ] USGS API queries return verified results
- [ ] Feature engineering documented with rationale

---

### 2. 🤖 ML Engineer

**Focus:** Model development, prediction quality, agent tool performance

**Key Responsibilities:**
- Train and evaluate prediction models (scikit-learn)
- Prevent data leakage in feature/target setup
- Build ML-backed agent tools (prediction, anomaly detection)
- Model versioning and performance monitoring
- Benchmarking against ground truth

**Key Files:** `src/ml/`, `src/agent/tools.py` (prediction tools), `tests/model/`

**Quality Gates:**
- [ ] R² ≥ 0.80 on test set (7-day ahead)
- [ ] RMSE ≤ 0.5 ft
- [ ] No data leakage (verified by tests)
- [ ] Benchmark results documented per session

---

### 3. 🎨 Software Engineer

**Focus:** Architecture, code quality, agent framework, testing, CI/CD

**Key Responsibilities:**
- Maintain layered architecture (separation of concerns)
- Design agent orchestration (research_agent, groundwater_agent)
- FastAPI endpoint design and React component architecture
- Write and maintain tests across all layers
- CI/CD pipeline and pre-commit hooks

**Key Files:** `src/agent/`, `api/`, `frontend/`, `.github/`, `tests/`

**Quality Gates:**
- [ ] All tests pass (89+ tests)
- [ ] No linting errors
- [ ] Each layer independently testable
- [ ] Agent responses include source citations

---

### 4. 📈 Research Analyst

**Focus:** Domain expertise, knowledge base curation, visualization design

**Key Responsibilities:**
- Curate knowledge base (PDFs, research documents, ground truth)
- Design dashboard visualizations for each user type
- Validate agent responses against hydrogeological knowledge
- Maintain benchmark question sets for accuracy testing
- Identify new research documents and data sources

**Key Files:** `resources/pdfs/`, `knowledge_base/`, `tests/knowledge/`, `docs/`

**Quality Gates:**
- [ ] KB covers all Florida aquifer topics
- [ ] Ground truth tests pass (Florida accuracy)
- [ ] Benchmark questions answered correctly
- [ ] New research documents integrated within 1 sprint

---

## 📅 Modular Development Sessions

Development is organized into focused sessions, each delivering a working increment. Sessions are designed to be completable in 1–2 weeks and are ordered by dependency — earlier sessions provide the foundation for later ones.

### Completed Sessions

| Session | Focus | Status | Key Deliverables |
|---------|-------|--------|------------------|
| **S1** | Data Pipeline & Foundation | ✅ Done | USGS download, 36 sites, 106K records |
| **S2** | ML Models & Prediction | ✅ Done | R²=0.93 (7-day), feature engineering |
| **S3** | Quality Infrastructure | ✅ Done | CI/CD, 89 tests, pre-commit hooks |
| **S4** | React Dashboard | ✅ Done | Map, time series, heatmap, sidebar |
| **S5** | Knowledge Base & RAG | ✅ Done | ChromaDB, 1,901 chunks, PDF ingestion |
| **S6** | Agent Architecture | ✅ Done | LLM factory, tools, research agent, chat |
| **S7** | Agent ↔ API Integration | ✅ Done | POST /api/chat, /api/research, ChatView.jsx, mode toggle |
| **S8** | Data Visualization Layer | ✅ Done | Chart tools, AgentChart.jsx, /api/sites/{id}/chart, /api/compare/chart |

---

### Session 7: Agent ↔ API Integration
*Role Lead: Software Engineer + Data Engineer*

**Goal:** Connect the research agent to the React frontend via FastAPI so users can chat and trigger deep research from the dashboard.

**Deliverables:**
- [x] `POST /api/chat` — Conversational agent endpoint (streaming)
- [x] `POST /api/research` — Deep research endpoint (returns structured report)
- [x] React `ChatView.jsx` connected to live agent backend
- [x] Mode toggle in UI: Quick Query vs Deep Research
- [x] Error handling and loading states in frontend

**Acceptance Criteria:**
- [x] User can ask "What are the water level trends for Lee County?" in the React chat and get a sourced response
- [x] Deep research mode runs iterative search and returns a multi-section report
- [x] All responses include source citations with trust scores

**Key Files:**
- `api/routes/chat.py` — Chat/research endpoints (refactored from api/main.py)
- `frontend/src/components/ChatView.jsx` — Wire to backend
- `frontend/src/api/client.js` — Add chat API methods

---

### Session 8: Data Visualization Layer
*Role Lead: Software Engineer + Research Analyst*

**Goal:** Enable the agent to generate and return data visualizations (time series plots, seasonal charts) as part of its responses, and allow users to plot USGS data directly.

**Deliverables:**
- [x] Agent tool: `generate_time_series_plot()` — returns Recharts JSON data
- [x] Agent tool: `generate_comparison_chart()` — multi-site overlay
- [x] React component to render agent-returned chart data (`AgentChart.jsx`)
- [ ] Direct USGS API time series plotting from the dashboard (depends on S9 live API)
- [ ] Heatmap and seasonal pattern visualization from live data (depends on S9)

**Acceptance Criteria:**
- [x] User asks "Show me water levels for site G-1251 over the last 2 years" → gets an interactive chart
- [ ] Dashboard can plot time series from USGS API directly (real-time) (depends on S9)
- [x] Charts are interactive (zoom, pan, tooltips)

**Key Files:**
- `src/agent/tools.py` — Visualization tools (`generate_time_series_plot`, `generate_comparison_chart`)
- `frontend/src/components/AgentChart.jsx` — Recharts renderer for agent chart data
- `api/routes/data.py` — Chart data endpoints (refactored from api/main.py)

---

### Session 9: USGS Live Query Integration
*Role Lead: Data Engineer*

**Goal:** Agent can query the USGS NWIS API in real time to answer questions about current conditions, not just historical CSV data.

**Deliverables:**
- [ ] Agent tool: `query_usgs_live()` — Fetch current/recent data from USGS API
- [ ] Caching layer to avoid redundant API calls (TTL-based)
- [ ] Fallback to local CSV if USGS API is unreachable
- [ ] Rate limiting per USGS guidelines (1 req/sec)

**Acceptance Criteria:**
- [ ] "What is the current water level at site L-2194?" returns today's data from USGS
- [ ] Repeated queries within 15 minutes use cached results
- [ ] API failures gracefully fall back to local data with a note

**Key Files:**
- `src/data/usgs_api.py` — New live query module
- `src/agent/tools.py` — Register new tool
- `config/config.py` — Cache TTL and rate limit settings

---

### Session 10: Benchmarking & Accuracy Testing
*Role Lead: Research Analyst + ML Engineer*

**Goal:** Establish a benchmark suite that measures agent answer quality against ground-truth questions, and ML model performance against holdout data.

**Deliverables:**
- [ ] Benchmark question set: 30+ questions across all user types
- [ ] Automated benchmark runner that scores agent responses
- [ ] Ground-truth answers for Florida aquifer questions (expand `tests/knowledge/ground_truth_florida.json`)
- [ ] ML benchmark: backtesting on 2023–2024 holdout data
- [ ] Benchmark report output (JSON + summary)

**Acceptance Criteria:**
- [ ] Agent achieves ≥85% accuracy on benchmark questions
- [ ] ML model R² ≥ 0.80 on holdout data
- [ ] Hallucination rate < 5% (verified by source checking)
- [ ] Response time < 5s for query mode, < 30s for deep research

**Benchmark Question Categories:**
| Category | Example Question | Expected Source |
|----------|------------------|-----------------|
| Factual (USGS) | "What is the average water level at G-1251?" | USGS data |
| Trend Analysis | "Is the Biscayne Aquifer declining?" | USGS + KB |
| Hydrogeology | "What is aquifer recharge?" | PDF knowledge base |
| Agricultural | "What crop grows well in Lee County given water table?" | KB + web |
| Comparison | "Compare water levels in Miami-Dade vs Collier" | USGS data |
| Anomaly | "Were there any unusual readings last month?" | USGS + anomaly tool |

**Key Files:**
- `tests/knowledge/ground_truth_florida.json` — Expand ground truth
- `tests/benchmark/` — New benchmark runner
- `tests/model/test_performance.py` — Holdout backtesting

---

### Session 11: Multi-Horizon Forecasting
*Role Lead: ML Engineer*

**Goal:** Extend predictions from 7-day to 14/30/90-day horizons with confidence intervals.

**Deliverables:**
- [ ] Multi-horizon models: 7, 14, 30, 90 day
- [ ] Confidence intervals (quantile regression or bootstrap)
- [ ] Agent tool: `get_forecast()` with horizon parameter
- [ ] Forecast comparison visualization in React dashboard

**Acceptance Criteria:**
- [ ] 7-day: R² ≥ 0.80 | 14-day: R² ≥ 0.70 | 30-day: R² ≥ 0.60
- [ ] Confidence intervals displayed on time series charts
- [ ] User asks "What will water levels be next month?" → gets forecast with uncertainty

---

### Session 12: Research Document Ingestion Pipeline
*Role Lead: Research Analyst + Data Engineer*

**Goal:** Streamlined pipeline for adding new research documents (PDFs, papers) to the knowledge base, with automatic chunking, embedding, and verification.

**Deliverables:**
- [x] CLI command: `python main.py ingest --path <file_or_dir>`
- [x] Automatic PDF parsing, chunking (512 chars), embedding
- [x] Source verification before ingestion (trust score ≥ 0.7)
- [x] Metadata extraction (title, author, date, DOI if available)
- [x] KB statistics endpoint (`GET /api/knowledge/stats`)
- [x] KB runtime health endpoint (`GET /api/knowledge/status`)

**Acceptance Criteria:**
- [x] Drop a PDF into `resources/pdfs/` → run ingest → KB updated
- [ ] Agent can answer questions from newly ingested documents
- [x] Duplicate detection prevents re-ingesting the same document

**Key Files:**
- `src/agent/knowledge.py` — Ingest pipeline
- `main.py` — CLI ingest command
- `resources/pdfs/` — Document drop zone

---

### Session 13: Deep Research Agent v2 — Multi-Agent Architecture
*Role Lead: Software Engineer*

**Goal:** Re-architect the research agent using an **orchestrator-worker pattern** informed by Anthropic's multi-agent research system, the Awesome-Deep-Research survey (60+ papers), and domain-specific patterns from WaterGPT, GAIA, and LLM dashboard literature.

> **Key Insight (Anthropic):** "Token usage by itself explains 80% of performance variance in browsing agent evaluations. Multi-agent architectures effectively scale token usage for tasks that exceed the limits of single agents." Multi-agent systems outperform single agents by 90.2% on research tasks.

**Architecture — Orchestrator-Worker Pattern:**

```
┌──────────────────────────────────────────────────────────────┐
│                     LeadResearcher                           │
│  ├── Analyzes query complexity (simple / moderate / complex) │
│  ├── Creates research plan (saved to memory)                 │
│  ├── Spawns 1-N SubAgents based on complexity                │
│  ├── Synthesizes subagent findings                           │
│  ├── Decides: more research needed? → spawn more subagents   │
│  └── Passes final report to CitationAgent                    │
└──────────┬────────────────────────┬──────────────────────────┘
           │                        │
┌──────────▼──────────┐  ┌─────────▼───────────┐
│    SubAgent A       │  │    SubAgent B        │
│  (KB + PDF search)  │  │  (USGS data query)   │  ... SubAgent N
│  ├── Web/KB search  │  │  ├── API queries     │
│  ├── Evaluate results│  │  ├── Stat analysis   │
│  ├── Refine query   │  │  ├── Trend detection  │
│  └── Return findings│  │  └── Return findings  │
└─────────────────────┘  └──────────────────────┘
           │                        │
┌──────────▼────────────────────────▼──────────────────────────┐
│                    CitationAgent                              │
│  ├── Processes documents + research report                   │
│  ├── Identifies specific source locations for citations      │
│  ├── Applies trust scoring (source_verification.py)          │
│  └── Returns final cited report                              │
└──────────────────────────────────────────────────────────────┘
```

**Deliverables:**
- [ ] `LeadResearcher` class: query analysis, plan creation, subagent orchestration
- [ ] `SubAgent` class: independent KB/web/data search with own context window
- [ ] `CitationAgent`: source attribution and trust scoring post-processing
- [ ] Research planner: break complex questions into parallelizable sub-queries
- [ ] Self-reflection loop: agent evaluates answer quality before responding (WebSeer pattern)
- [ ] Structured report output (sections, citations, confidence per section)
- [ ] Configurable search depth, timeout, and token budget
- [ ] Research session persistence (resume interrupted research via memory/checkpoints)
- [ ] Effort scaling: 1 agent / 3-10 tool calls for simple queries → 5+ agents for complex

**Acceptance Criteria:**
- [ ] Complex question "What are the long-term impacts of sea level rise on the Biscayne Aquifer?" produces a multi-section report with 5+ sources
- [ ] SubAgents execute in parallel (3-5 concurrent), reducing research time by ≥ 50%
- [ ] Self-reflection catches low-confidence sections and triggers re-search
- [ ] Research can be stopped and resumed (checkpoint persistence)
- [ ] Token budget controls prevent runaway costs (≤ 15× single chat interaction)
- [ ] LLM-as-judge evaluation scores ≥ 0.7 on factual accuracy, citation accuracy, completeness

**Research-Backed Implementation Patterns:**

| Pattern | Source Paper/System | How to Apply |
|---------|-------------------|--------------|
| **Orchestrator-Worker** | Anthropic Research System | LeadResearcher delegates to SubAgents with specific objectives, output format, tool guidance, and task boundaries |
| **Iterative Query Optimization** | SmartSearch, ReSeek (2025) | SubAgents start with broad queries, evaluate results, then progressively narrow focus |
| **Self-Reflection** | WebSeer (2025), Interleaved Thinking | After tool results, SubAgents use thinking to evaluate quality, identify gaps, refine next query |
| **Context Summarization** | ReSum (2025) | Compress completed research phases to memory before proceeding; prevents context overflow |
| **Budget-Aware Tool Use** | Budget-Aware (2025) | Embed scaling rules in prompts: simple fact-finding = 1 agent / 3-10 calls; complex research = 5+ agents |
| **Filesystem Output** | Anthropic Appendix | SubAgents write findings to shared memory/filesystem, pass lightweight references to LeadResearcher |
| **Atomic Thought Reward** | Atom-Searcher (2025) | Fine-grained reward signals for each reasoning step, not just final output |
| **Process Reward** | HiPRAG, Process vs Outcome (2025) | Reward intermediate search decisions, not just final answer quality |

**Prompt Engineering Principles (from Anthropic):**
1. **Think like your agents** — simulate in console, watch step-by-step for failure modes
2. **Teach delegation** — lead agent must give subagents: objective, output format, tool list, task boundaries
3. **Scale effort to complexity** — explicit rules for agent count and tool call budget
4. **Tool design is critical** — explicit heuristics: examine tools first, match to intent, prefer specialized over generic
5. **Start wide, then narrow** — broad initial queries before drilling into specifics
6. **Guide the thinking process** — extended thinking for planning, interleaved thinking after tool results
7. **Parallel tool calling** — subagents use 3+ tools in parallel; lead spawns 3-5 subagents concurrently

**Evaluation Strategy (from Anthropic):**
- Start with ~20 representative queries covering real usage patterns
- LLM-as-judge scoring (0.0-1.0) on: factual accuracy, citation accuracy, completeness, source quality, tool efficiency
- Human evaluation to catch hallucinations, source selection biases, edge cases
- End-state evaluation (judge outcome, not process) since agents take different valid paths

**Key Files:**
- `src/agent/research_agent.py` — Refactor into multi-agent architecture
- `src/agent/lead_researcher.py` — New: orchestrator agent
- `src/agent/sub_agent.py` — New: specialized worker agents
- `src/agent/citation_agent.py` — New: post-processing citations
- `src/agent/source_verification.py` — Trust scoring integration

---

### Session 14: Production Deployment
*Role Lead: Software Engineer*

**Goal:** Deploy the full stack (React + FastAPI + Agent) for public access.

**Deliverables:**
- [ ] Docker Compose for full stack deployment
- [ ] Environment configuration for production (API keys, CORS, etc.)
- [ ] Health check endpoints
- [ ] Monitoring and alerting (response times, error rates)
- [ ] User documentation and onboarding guide

---

### Session Dependency Graph

```
S1─S2─S3─S4 ─────── S7 ──── S8
         │           │        │
         S5─S6 ──────┤   S9 ──┤
                     │        │
                     S10 ─────┤
                              │
                     S11 ─────┤
                              │
                     S12 ── S13 ── S14
```

| Session | Depends On | Can Parallel With |
|---------|-----------|-------------------|
| S7 (API Integration) | S4, S6 | S9, S10 |
| S8 (Data Viz) | S7 | S9, S10, S11 |
| S9 (USGS Live) | S6 | S7, S10 |
| S10 (Benchmarking) | S6 | S7, S8, S9 |
| S11 (Multi-Horizon) | S2, S7 | S10, S12 |
| S12 (Doc Ingestion) | S5 | S10, S11 |
| S13 (Agent v2) | S7, S12 | S11 |
| S14 (Production) | S7, S8, S13 | — |

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

## 🧪 Testing & Benchmarking Strategy

### Test Categories

| Type | Purpose | Coverage Target |
|------|---------|-----------------|
| **Unit** | Individual functions | 90% |
| **Integration** | Component interactions (API ↔ Agent ↔ KB) | 80% |
| **Data** | Data quality, schema, USGS integrity | 100% of pipelines |
| **Model** | ML performance metrics | Key thresholds |
| **Knowledge** | Agent accuracy vs ground truth | Benchmark suite |
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

---

## 🚀 Quick Start Guide

### Prerequisites

- Python 3.11+
- Node.js 18+
- Git

### Installation

```bash
# Clone repository
git clone https://github.com/walatheo/GroundwaterGPT.git
cd GroundwaterGPT

# Python environment
python -m venv .venv
source .venv/bin/activate
pip install -r GroundwaterGPT/requirements.txt

# Frontend dependencies
cd GroundwaterGPT/frontend
npm install
```

### Running the Application

**Terminal 1 - Start API:**
```bash
cd GroundwaterGPT/api
uvicorn main:app --reload --port 8000
```

**Terminal 2 - Start Frontend:**
```bash
cd GroundwaterGPT/frontend
npm run dev
```

### Access Points

| Service | URL | Description |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | React dashboard |
| API | http://localhost:8000 | FastAPI backend |
| API Docs | http://localhost:8000/docs | Swagger UI |

---

## 📊 Data Sources

### USGS Sites (36 Total)

| County | Sites | Example IDs |
|--------|-------|-------------|
| Miami-Dade | 16 | G-1251, G-3777, G-3356 |
| Lee | 7 | L-2194, L-581, L-1999 |
| Collier | 5 | C-951R, C-953R, C-948R |
| Sarasota | 4 | Multiple wells |
| Hendry | 4 | HE-1042, HE-859 |

### Data Verification

All data is verified against the official USGS NWIS API:
- Site IDs match official database
- Values confirmed against live API
- 106,628 total records

---

*Last updated: February 3, 2026*

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

## 🔮 Future Research Directions

This project is designed as an extensible foundation for agentic groundwater research. The following directions synthesize insights from three bodies of literature:

1. **Agentic Deep Research** — [Awesome-Deep-Research](https://github.com/DavidZWZ/Awesome-Deep-Research) survey (60+ papers, 20+ open-source implementations) and [Anthropic's multi-agent research system](https://www.anthropic.com/engineering/built-multi-agent-research-system)
2. **Domain-Specific AI** — Reference PDFs in `resources/pdfs/references/` covering agentic data analysts, LLM dashboards, scientific agents, and environmental LLM applications
3. **FAIR Data Principles** — Wilkinson et al. (2016) guidelines for findable, accessible, interoperable, reusable data

---

### 📖 Literature-Informed Architecture Patterns

#### A. Multi-Agent Research Systems

The state of the art in agentic deep research has converged on the **orchestrator-worker pattern** (Anthropic, DeerFlow, GPT-Researcher). Key findings:

| Finding | Source | Implication for GroundwaterGPT |
|---------|--------|-------------------------------|
| Token usage explains 80% of research quality variance | Anthropic (2025) | Multi-agent architecture is essential for complex groundwater questions |
| Multi-agent outperforms single-agent by 90.2% | Anthropic BrowseComp eval | Session 13 should implement full orchestrator-worker decomposition |
| Agents use ~4× more tokens than chat; multi-agent uses ~15× | Anthropic production data | Budget controls critical — embed token limits in prompts |
| Start wide, then narrow search queries | Anthropic, SimpleDeepSearcher | SubAgents should begin with "groundwater Florida aquifer" not "Biscayne aquifer saltwater intrusion 2024 USGS data" |
| Subagent filesystem output reduces "telephone game" errors | Anthropic Appendix | SubAgents write to shared memory, pass lightweight references |
| Context summarization prevents overflow | ReSum (2025) | Compress completed phases before spawning new subagents |

**Open-Source Implementations to Study:**

| Project | Architecture | Why Relevant |
|---------|-------------|--------------|
| [gemini-fullstack-langgraph-quickstart](https://github.com/google-gemini/gemini-fullstack-langgraph-quickstart) | LangGraph + Gemini fullstack | Closest to our stack (LangGraph + React) |
| [DeerFlow](https://github.com/bytedance/deer-flow) | ByteDance research framework | Production-grade multi-agent with planning |
| [GPT-Researcher](https://github.com/assafelovic/gpt-researcher) | Autonomous research agent | Iterative search + report synthesis |
| [langgraph-deep-research](https://github.com/foreveryh/langgraph-deep-research) | LangGraph workflows | Direct LangGraph patterns for deep research |
| [nanoDeepResearch](https://github.com/liyuan24/nanoDeepResearch) | Lightweight toolkit | Minimal implementation for learning |
| [Anthropic multi-agent prompts](https://platform.claude.com/cookbook/patterns-agents-basic-workflows) | Cookbook patterns | Open-source prompts from production system |

#### B. Reinforcement Learning for Search Agents

The most active research frontier (2025-2026) is training search agents via RL:

| Approach | Papers | Key Idea | Applicability |
|----------|--------|----------|---------------|
| **GRPO** (Group Relative Policy Optimization) | DeepResearcher, ReSeek, SmartSearch, Atom-Searcher | Train search policy from group-level reward comparisons | Future: fine-tune local model for groundwater search |
| **Process Rewards** | HiPRAG, Process vs Outcome (2025) | Reward each search step, not just final answer | Improve intermediate tool selection in research agent |
| **Self-Reflection** | WebSeer (2025) | Agent corrects itself after observing search results | Near-term: add reflection step to DeepResearchAgent |
| **Self-Evolving Agents** | Dr. Zero (2026) | Agents improve without training data | Long-term: autonomous improvement loop |
| **Budget-Aware Reasoning** | Budget-Aware Tool-Use (2025) | Scale effort to query complexity | Near-term: effort scaling in Session 13 |

> **Practical Note:** Most RL approaches require Qwen2.5-7B+ class models. Our Ollama-first architecture supports this via local fine-tuning with `ollama create` from GGUF exports.

#### C. Domain-Specific Environmental AI

From the reference PDFs in `resources/pdfs/references/`:

| Paper/System | Key Pattern | Application to GroundwaterGPT |
|-------------|-------------|-------------------------------|
| **GAIA** (Harsuko et al., 2026) | Agentic AI for geothermal analytics — automated field development with domain tools | Model for our groundwater analytics agent: domain-specific tools + LLM reasoning |
| **WaterGPT** (Ren et al., 2024) | LLM for water/wastewater management tasks | Validates our approach: domain-adapted LLM + specialized tools for hydrology |
| **Spec-Driven AI for Science** | Specification-driven agent design | Define formal specs for each tool's inputs/outputs/constraints |
| **Understanding Agentic AI for Data Analysis** | Taxonomy of agentic data analysis patterns | Framework for classifying our agent's analysis capabilities |
| **Eythorsson & Clark (2025)** | Toward automated scientific discovery in hydrology | Long-term vision: agent proposes and tests hypotheses |
| **Zhang et al. (2025)** | Foundation models as assistive tools in hydrometeorology | Integration patterns for combining LLMs with numerical weather/hydro models |
| **Iyer et al. (2025)** | GeoAI review | Best practices for geospatial AI applications |

#### D. LLM-Powered Dashboard Patterns

From `resources/pdfs/references/LLM dashboards/`:

| Paper | Pattern | Relevance |
|-------|---------|-----------|
| **Becker et al. (2023)** — RIXA | Explaining AI in natural language alongside dashboards | Add natural language explanations to each chart/visualization |
| **Jin et al. (2025)** — Chatting with LA Dashboard | Conversational interface layered on analytics dashboard | Our ChatView.jsx approach validated; extend with contextual suggestions |
| **Stock et al. (2025)** — Dashboard Filtering via LLM | LLM interprets user intent to filter dashboard data | "Show me only drought months" → agent filters time series in real time |
| **Shih et al. (2024)** — Data Science Workflows | LLM-orchestrated data science pipelines | Agent can generate and execute analysis code on demand |
| **Mathur et al. (2025)** — PyEvoCell | LLM-augmented trajectory analysis | Pattern for LLM + domain-specific analysis tools working together |

#### E. Scientific Agent Patterns

From `resources/pdfs/references/Training LLM on Env Data/Scientific agents/`:

| Paper | Key Contribution | Implementation Path |
|-------|-----------------|---------------------|
| **Boiko et al. (2023)** — Chemical agents with LLMs | Autonomous experimental design: plan → execute → analyze → iterate | Template for our research agent's iterative hypothesis-testing loop |
| **Romera-Paredes et al. (2023)** — Math discovery | LLM discovers new mathematical relationships | Long-term: agent discovers novel groundwater correlations |
| **Wang (2023)** — Scientific discovery in age of AI | Framework for AI-augmented research workflows | Validates our 5-layer architecture (Presentation → Agent → Knowledge → Verification → Data) |
| **Zheng et al. (2025)** — LLMs for reticular chemistry | Domain-specific fine-tuning + tool use | Pattern for fine-tuning on groundwater literature |

#### F. Research Integrity & Bias

| Paper | Key Finding | Design Principle |
|-------|-------------|-----------------|
| **van der Ven (2025)** — AI bias in environmental challenges | LLMs can perpetuate biases in environmental data interpretation | Always verify agent claims against USGS numerical data; trust scores essential |
| **Wilkinson et al. (2016)** — FAIR principles | Data must be Findable, Accessible, Interoperable, Reusable | All data endpoints include metadata; knowledge base maintains provenance |
| **Larosa et al. (2025)** — LLM climate text analysis | LLMs effective for analyzing climate literature but prone to overconfidence | Self-reflection loop must flag uncertainty; present confidence intervals |

---

### 🗺️ Implementation Roadmap (Research-Informed)

### Current Development Execution Plan (As of February 27, 2026)

The next implementation cycle is intentionally ordered to reduce rework:
stability first, then workflow exposure, then multi-agent scaling.

#### Sprint 1 — Operational Hardening (In Progress)
- [x] Normalize style/quality gates so pre-commit passes without bypass.
- [x] Stabilize test suite behavior across local environments and data snapshots.
- [x] Add explicit KB runtime readiness checks (embedding dependencies + storage state).
- [x] Surface KB runtime health in API responses/endpoints.
- [x] Add graceful 503 errors for ingestion/search when runtime requirements are missing.

**Why first:** This removes high-probability runtime failures that would otherwise
invalidate downstream work in ingestion, UI integration, and multi-agent orchestration.

#### Sprint 2 — Research Workflow Productization
- [x] Expose experiment-plan/run/paper-draft tools as first-class API flows.
- [x] Add frontend workflow UI: create plan → log runs → generate draft manuscript.
- [x] Enforce reproducibility schema for run configs, metrics, and artifacts.
- [x] Persist provenance metadata with manuscript drafts.

**Why second:** These capabilities already exist at the tool layer; making them
user-facing creates direct researcher value with limited architectural risk.

#### Sprint 3 — Evaluation + Citation Integrity
- [x] Add retrieval and report-quality benchmark harness in CI.
- [x] Add claim-to-source citation structure in deep research reports.
- [ ] Track confidence/trust per section in generated research outputs.
- [x] Define quality thresholds for factual accuracy and citation coverage.

**Why third:** Quality gates are critical before scaling to a multi-agent pipeline.

#### Sprint 4 — Multi-Agent Research Architecture
- [ ] Implement `LeadResearcher`, `SubAgent`, and `CitationAgent`.
- [ ] Add planner-based subtask decomposition and parallel execution.
- [ ] Add checkpoint/resume support for long research sessions.
- [ ] Add budget controls for depth/tool usage by query complexity.

**Why fourth:** Multi-agent complexity is justified only after stable runtime,
usable workflows, and objective quality evaluation are in place.

#### Near-Term (Sessions 8-11)
- [ ] **Dashboard NL filtering** — LLM interprets "show dry season data" to filter charts (Stock et al. pattern)
- [ ] **Contextual explanations** — ChatView generates plain-language summaries of visible charts (RIXA pattern)
- [ ] **NOAA data integration** — Correlate rainfall/tide with water levels (multi-source research)
- [ ] **FAIR metadata** — All API endpoints return source provenance and data lineage

#### Medium-Term (Sessions 12-13)
- [ ] **Multi-agent research** — Orchestrator-worker with parallel SubAgents (Anthropic pattern)
- [ ] **Self-reflection loop** — Agent evaluates own answer quality before responding (WebSeer)
- [ ] **Document ingestion pipeline** — Auto-ingest PDFs from `resources/pdfs/references/` with trust scoring
- [ ] **LLM-as-judge evaluation** — Automated quality scoring for research outputs
- [ ] **Research session memory** — Persist research state across sessions (context summarization)

#### Long-Term (Post Session 14)
- [ ] **RL-trained search agent** — GRPO fine-tuning on groundwater question-answer pairs
- [ ] **Hypothesis generation** — Agent proposes testable groundwater hypotheses (Boiko et al. pattern)
- [ ] **Satellite data fusion** — NDVI/soil moisture via NASA EarthData (GeoAI patterns)
- [ ] **Causal inference** — Bayesian networks for climate → water level causation
- [ ] **Automated scientific reports** — Monthly trend reports with citations (Multimodal DeepResearcher pattern)
- [ ] **Cross-domain transfer** — Apply architecture to other environmental monitoring domains

### Data Sources (planned)
- [ ] NOAA precipitation data (correlate rainfall with water levels)
- [ ] Sea level monitoring (NOAA tide gauges)
- [ ] Satellite imagery (NDVI, soil moisture via NASA EarthData)
- [ ] Additional USGS sites beyond Florida

### ML & Modeling (planned)
- [ ] LSTM/Transformer models for sequence prediction
- [ ] Bayesian uncertainty quantification
- [ ] Causal inference for climate impact analysis
- [ ] Ensemble methods combining multiple model architectures

### Research Outputs (planned)
- [ ] Automated monthly trend reports
- [ ] Seasonal forecasts with confidence intervals
- [ ] Drought/flood risk assessment
- [ ] Publication-ready figures and data exports

### Document Integration (planned)
New research documents will be added to `resources/pdfs/` and ingested via the document pipeline (Session 12). The knowledge base is designed to grow over time while maintaining source verification standards.

### 📚 Reference Library Index

The following documents in `resources/pdfs/references/` inform this project's design:

```
resources/pdfs/references/
├── Agentic Data Analysts/
│   ├── GAIA Geothermal Analytics and Intelligent Agent.pdf    → Agent architecture model
│   ├── Spec-Driven AI for Science.pdf                         → Formal tool specifications
│   └── Understanding Agentic AI Systems for Data Analysis.pdf → Taxonomy of agent patterns
├── FAIR data/
│   └── Wilkinson et al 2016 FAIR guiding principles.pdf       → Data provenance standards
├── LLM dashboards/
│   ├── Becker et al 2023 RIXA (NL explanations).pdf          → Dashboard NL layer
│   ├── Jin et al 2025 Chatting with LA Dashboard.pdf          → Conversational dashboard
│   ├── Stock et al 2025 Dashboard Filtering via LLM.pdf       → NL-driven data filtering
│   ├── Shih et al 2024 Data Science Workflows.pdf             → LLM-orchestrated analysis
│   └── Mathur et al 2025 PyEvoCell.pdf                        → LLM + domain analysis
├── Training LLM on Env Data/
│   ├── General/ (WaterGPT, GeoAI, Foundation Models, etc.)   → Domain validation
│   ├── Scientific agents/ (Chemical agents, Math discovery)   → Hypothesis-testing patterns
│   ├── Text analysis/ (Climate NLP, bias detection)           → Literature mining
│   └── Accuracy Score/ (Hydro LLM benchmark, LUR)            → Evaluation benchmarks
└── Academic writing/
    └── Editorial – Why it is a blessing to be rejected.pdf    → Publication guidance
```

---

*This guide is a living document. Update as practices evolve.*
