# Task 2: Agentic Deep Research with Priority Ranking & Searching

**Date:** March 16, 2026  
**Status:** Active Development  
**Priority:** ⭐ HIGH  

---

## 📋 Executive Summary

Build an integrated **agentic deep research system** for groundwater analysis that combines:

1. **Priority Ranking** (SmartSearch pattern) - intelligently order search results
2. **Iterative Searching** (ReSeek pattern) - budget-aware, multi-phase search
3. **Research Planning** (O-Researcher pattern) - decompose complex questions
4. **Self-Reflection** (WebSeer pattern) - evaluate quality and identify gaps
5. **Groundwater Domain Model** - specialized knowledge and validation

**Goal:** Enable autonomous research agents to conduct sophisticated groundwater investigations using canonical data pipeline + deep research techniques.

---

## 🎯 Objectives

### O1: Integrate Research Optimizer with Agent System
- [ ] Connect `ResearchPlanner` to agent initialization
- [ ] Wire `PriorityRanker` to search result processing
- [ ] Implement `SelfReflectionEvaluator` feedback loop
- [ ] Add `ResearchSessionPersistence` for long-running research

### O2: Build Groundwater-Specific Research Model
- [ ] Domain-aware query expansion (hydrology terms)
- [ ] Aquifer-specific validation rules
- [ ] Seasonal pattern detection integration
- [ ] Multi-site correlation analysis

### O3: Implement Priority-Based Search Pipeline
- [ ] Multi-phase search strategy (planning → searching → reflecting)
- [ ] Search budget management
- [ ] Source verification integration
- [ ] Confidence-aware result filtering

### O4: Create Research Workflow Examples
- [ ] Example: "Compare water levels across Biscayne Aquifer sites"
- [ ] Example: "Analyze climate impact on Floridan Aquifer"
- [ ] Example: "Investigate anomalies in surficial aquifer data"
- [ ] Executable notebooks demonstrating workflows

---

## 📦 Deliverables

### Core Implementation Files
| File | Purpose | Status |
|------|---------|--------|
| `src/agent/research_workflow.py` | Integrated research workflow orchestrator | In Progress |
| `src/agent/groundwater_research_model.py` | Domain-specific research model | Planned |
| `src/agent/priority_search_engine.py` | Priority-ranked search implementation | Planned |
| `api/routes/research_workflow.py` | API endpoints for research workflows | Planned |

### Examples & Documentation
| File | Purpose | Status |
|------|---------|--------|
| `notebooks/deep_research_examples.ipynb` | Executable research examples | Planned |
| `TASK_2_IMPLEMENTATION.md` | Implementation progress | Planned |
| `TASK_2_TESTING.md` | Test strategy & results | Planned |

### Reference Documentation
- Evidence of patterns from Awesome-Deep-Research
- SmartSearch: Prioritized result ranking
- ReSeek: Budget-aware multi-phase search
- WebSeer: Quality evaluation & gap detection
- O-Researcher: Query decomposition

---

## 🏗️ Architecture

### Research Pipeline Architecture
```
User Query (Groundwater Research Question)
    ↓
research_workflow.execute()
    ├─→ 1. PLANNING PHASE
    │   ├─→ Query decomposition (ResearchPlanner)
    │   ├─→ Domain expansion (groundwater terms, site aliases)
    │   └─→ Output: ResearchPlan with ordered search queries
    ├─→ 2. SEARCH PHASE (Budget-Aware)
    │   ├─→ KB search (local knowledge base)
    │   ├─→ Web search (prioritized queries)
    │   ├─→ Data search (USGS sites, pipeline results)
    │   ├─→ Priority ranking (PriorityRanker)
    │   └─→ Output: RankedSearchResults (top N results)
    ├─→ 3. INSIGHT EXTRACTION
    │   ├─→ Extract key facts from results
    │   ├─→ Verify sources (SourceVerification)
    │   ├─→ Add to knowledge base (auto-learn)
    │   └─→ Output: Insights with metadata
    ├─→ 4. SYNTHESIS
    │   ├─→ Build structured report (StructuredReportBuilder)
    │   ├─→ Self-evaluation (SelfReflectionEvaluator)
    │   └─→ Output: Report + ReflectionResult
    └─→ 5. ITERATION (if quality < threshold)
        └─→ Follow-up queries based on reflection
            
Final Output: Comprehensive research report with sources, confidence, and gaps
```

### Integration Points
```
research_workflow.py
├─→ research_optimizer.py (ResearchPlanner, PriorityRanker, etc.)
├─→ research_agent.py (web search, knowledge integration)
├─→ groundwater_agent.py (domain-specific context)
├─→ tools.py (data querying, analysis)
├─→ data/pipeline.py (fresh data fetching)
└─→ knowledge.py (KB management)
```

---

## 🔬 Groundwater Domain Model

### Domain-Aware Query Expansion
```python
# Example: User asks "How are water levels changing?"
# System expands to:
- "water level trends"
- "aquifer elevation changes"
- "groundwater depth variations"
- "piezometric surface changes"
- "seasonal patterns"
- "long-term trends"
```

### Aquifer-Specific Validation
```python
# Biscayne Aquifer
- Elevation range: -100 to +20 feet (MSL)
- Typical depth: 10-50 feet below surface
- Sensitivity: High (influenced by tides, rainfall)

# Floridan Aquifer
- Elevation range: -200 to -500 feet (MSL)
- Typical depth: 50-200 feet below surface
- Sensitivity: Moderate (deep, confined aquifer)

# Surficial Aquifer
- Elevation range: -5 to +15 feet (MSL)
- Typical depth: 0-20 feet below surface
- Sensitivity: Very high (influence by rainfall)
```

### Multi-Site Correlation Analysis
```python
def analyze_correlations(sites: List[str], parameter: str = "water_level"):
    """
    Compare patterns across multiple sites.
    Identifies regional synchrony (climate-driven)
    vs local patterns (site-specific).
    """
```

---

## 📚 Reference Patterns

### SmartSearch (Priority Ranking)
**Source:** Awesome-Deep-Research  
**Purpose:** Rank search results by relevance, trust, and recency  
**Implementation:** `PriorityRanker` in research_optimizer.py

**Key Metrics:**
- **Relevance Score:** Query term overlap in title/snippet (0.0-1.0)
- **Trust Score:** Domain reputation (USGS=0.9, .edu=0.7, web=0.5)
- **Recency Score:** Publication date (2025=0.8, 2023=0.5, older=0.3)
- **Combined Score:** Weighted average (0.5×relevance + 0.3×trust + 0.2×recency)

### ReSeek (Budget-Aware Search)
**Source:** Awesome-Deep-Research  
**Purpose:** Manage search API costs and optimize query sequences  
**Implementation:** `SearchBudget` in research_optimizer.py

**Budget Constraints:**
- Max web searches: 10
- Max KB searches: 20 (free, local)
- Max API calls: 50
- Total budget: $10

### WebSeer (Self-Reflection)
**Source:** Awesome-Deep-Research  
**Purpose:** Evaluate synthesis quality and identify research gaps  
**Implementation:** `SelfReflectionEvaluator` in research_optimizer.py

**Evaluation Dimensions:**
- Coverage: Do all sub-questions get answered?
- Confidence: Is answer well-supported by evidence?
- Completeness: Is answer comprehensive?
- Clarity: Is answer well-structured?

### O-Researcher (Query Decomposition)
**Source:** Awesome-Deep-Research  
**Purpose:** Break down complex questions into sub-research tasks  
**Implementation:** `ResearchPlanner` in research_optimizer.py

**Output:**
- Main question (refined)
- 3-5 sub-questions
- Research areas
- Expected report sections
- Priority-ordered search queries

---

## 🧪 Test Strategy

### Unit Tests
- [ ] Research planner creates multi-part plans
- [ ] Priority ranker orders results correctly
- [ ] Search budget enforcement
- [ ] Self-reflection evaluation logic
- [ ] Report building with citations
- [ ] Session persistence

### Integration Tests
- [ ] End-to-end workflow (plan → search → synthesize)
- [ ] Budget exhaustion handling
- [ ] Multi-phase iteration (reflection loop)
- [ ] Groundwater domain validation
- [ ] API integration

### Evaluation Tests
- [ ] Research quality metrics (coverage, confidence)
- [ ] Source diversity (KB, web, data)
- [ ] Groundwater-specific accuracy
- [ ] Response time constraints

---

## 📊 Success Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| **Planning Accuracy** | >80% | User agrees research plan covers question |
| **Result Relevance** | >70% | Top 5 results relevant to query |
| **Source Quality** | >75% | Trusted sources in top results |
| **Report Completeness** | >80% | All sub-questions addressed |
| **Synthesis Quality** | >0.7 | Self-reflection confidence score |
| **Performance** | <30s | Time to research report (excluding web search) |

---

## 🔒 Data & Research Quality

### Source Verification
- USGS sites: Highly trusted (0.95)
- Academic papers: Trusted (0.7-0.8)
- News articles: Medium trust (0.4-0.6)
- Social media: Low trust (0.1-0.3)

### Confidence Computation
- Per-insight confidence (source + content quality)
- Per-section confidence (average of supporting insights)
- Overall report confidence (weighted section average)

### Freshness Management
- Pipeline data: Always fresh (run_pipeline before research)
- Knowledge base: Hybrid (verified insights + recent papers)
- Web search: Real-time but filtered for quality

---

## 📝 Next Steps

1. **Immediate (This session):**
   - [ ] Create `src/agent/research_workflow.py` (orchestrator)
   - [ ] Create `src/agent/groundwater_research_model.py` (domain model)
   - [ ] Integrate with existing `research_optimizer.py`
   - [ ] Add tests and examples

2. **Follow-up:**
   - [ ] API endpoints for workflow submission
   - [ ] Frontend integration for research interface
   - [ ] Performance optimization
   - [ ] Production deployment

---

## 📎 References

- **Awesome-Deep-Research:** https://github.com/DavidZWZ/Awesome-Deep-Research
- **SmartSearch Paper:** Research planning and query optimization
- **ReSeek:** Budget-aware knowledge-seeking systems
- **WebSeer:** Self-reflection for web-based research
- **O-Researcher:** Multi-agent research decomposition

---

**Status:** Ready for implementation  
**Assigned:** Development Team  
**Target Completion:** March 23, 2026
