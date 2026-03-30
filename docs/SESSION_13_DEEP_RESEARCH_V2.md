# Deep Research Agent v2 - Implementation Guide

**Date:** March 16, 2026  
**Session:** 13  
**Status:** Implemented  
**Priority:** HIGH  

---

## 📋 Executive Summary

This guide documents the implementation of **Deep Research Agent v2**, which enhances the groundwater research agent with advanced patterns from [Awesome-Deep-Research](https://github.com/DavidZWZ/Awesome-Deep-Research).

The enhanced agent now supports:
- **Research Planning** - Decompose complex queries into structured sub-questions
- **Priority Ranking** - Intelligently rank search results by relevance, trust, and recency
- **Self-Reflection** - Quality control loops that identify knowledge gaps and trigger re-search
- **Search Budget Management** - Track API usage and costs for efficient operation
- **Session Persistence** - Save and resume long-running research investigations

---

## 🎯 What Changed

### Before (v1)
```python
agent = DeepResearchAgent(max_depth=3, timeout_seconds=300)
result = agent.research("What is saltwater intrusion?")
# Returns: Dict with report and insights only
```

### After (v2)
```python
agent = DeepResearchAgent(
    enable_planning=True,           # New: Multi-step planning
    enable_reflection=True,         # New: Quality control
    enable_budget_management=True,  # New: Cost tracking
    enable_persistence=True,        # New: Resume capability
)

# Complex query analyzed with multi-step planning
result = agent.research(
    query="What are the long-term impacts of sea level rise on the Biscayne Aquifer?",
    session_id="research_001",      # New: Resumable sessions
)

# Returns enhanced result with:
# - research_plan: Structured breakdown of the question
# - report: Multi-section structured report (not just prose)
# - reflection: Quality assessment and confidence scores
# - search_budget: API usage tracking
```

---

## 📚 New Components

### 1. Research Planner (`ResearchPlanner`)

**Purpose:** Decompose complex questions into structured research plans.

**Pattern:** O-Researcher (multi-agent decomposition)

**Usage:**
```python
from src.agent.research_optimizer import ResearchPlanner

planner = ResearchPlanner()

plan = planner.plan_research(
    "What are the long-term impacts of sea level rise on the Biscayne Aquifer?",
    domain="groundwater"
)

# Output structure:
# - main_question: Refined version of query
# - sub_questions: 3-5 specific questions that together answer it
# - research_areas: Key topics (e.g., ["hydrology", "climate", "economics"])
# - expected_sections: Report structure headings
# - search_priority: Ordered search queries (most important first)

print(f"Main Q: {plan.main_question}")
for i, sub_q in enumerate(plan.sub_questions, 1):
    print(f"  {i}. {sub_q}")
```

**Key Benefits:**
- Breaks down complex queries automatically
- Prioritizes search queries by importance
- Pre-defines report structure
- Enables multi-agent decomposition patterns

---

### 2. Priority Ranker (`PriorityRanker`)

**Purpose:** Intelligently rank search results by relevance, trust, and recency.

**Pattern:** SmartSearch (iterative query optimization)

**Usage:**
```python
from src.agent.research_optimizer import PriorityRanker

ranker = PriorityRanker()

results = [
    {"title": "...", "url": "https://usgs.gov/...", "snippet": "..."},
    {"title": "...", "url": "https://blog.com/...", "snippet": "..."},
    {"title": "...", "url": "https://edu.gov/...", "snippet": "..."},
]

ranked = ranker.rank_results(
    results,
    query="groundwater aquifer",
    research_context="Florida aquifer systems"
)

# Sorted by combined_score (highest first)
# Each result now has:
# - relevance_score: Query match (0.0-1.0)
# - trust_score: Source authority (0.0-1.0)
# - recency_score: Freshness (0.0-1.0)
# - combined_score: Weighted average
# - reasoning: Explanation of ranking

for i, ranked_result in enumerate(ranked, 1):
    print(f"{i}. {ranked_result.title}")
    print(f"   Score: {ranked_result.combined_score:.2f}")
    print(f"   Trust: {ranked_result.trust_score:.2f} | Relevance: {ranked_result.relevance_score:.2f}")
    print(f"   URL: {ranked_result.url}")
```

**Scoring Strategies:**
- **Relevance (50% weight):** Query term overlap in title + snippet
- **Trust (30% weight):** Domain authority (USGS=0.9, .edu=0.7, unknown=0.5)
- **Recency (20% weight):** Year mention in URL/snippet (2024+)

**Trust Hierarchy:**
```
Knowledge Base (0.95)
    ↓
USGS, NOAA (0.9)
    ↓
EPA, Geology.gov (0.85)
    ↓
Universities (.edu) (0.7)
    ↓
ResearchGate (0.6)
    ↓
Unknown sources (0.5)
```

---

### 3. Self-Reflection Evaluator (`SelfReflectionEvaluator`)

**Purpose:** Assess research quality and identify knowledge gaps.

**Pattern:** WebSeer (quality control with guided re-search)

**Usage:**
```python
from src.agent.research_optimizer import SelfReflectionEvaluator, ResearchPlan

reflector = SelfReflectionEvaluator(min_quality_threshold=0.7)

# Evaluate a synthesized answer
result = reflector.evaluate_synthesis(
    synthesis="The synthesized research answer...",
    research_plan=plan,  # From ResearchPlanner
    insights=[{"confidence": 0.8}, {"confidence": 0.7}]
)

# Returns ReflectionResult with:
# - is_high_quality: Boolean (based on threshold)
# - confidence_score: 0.0-1.0 overall confidence
# - coverage_score: How well all sub-questions are answered
# - missing_areas: List of gaps
# - follow_up_queries: Auto-generated re-search queries
# - sections_requiring_more_research: Specific sections

if not result.is_high_quality:
    print(f"Quality too low ({result.confidence_score:.2f})")
    print("Missing areas:")
    for area in result.missing_areas:
        print(f"  - {area}")
    print("Suggested re-search:")
    for query in result.follow_up_queries:
        print(f"  - {query}")
```

**Quality Assessment Criteria:**
- **Coverage:** Do all sub-questions get answered?
- **Confidence:** Are claims well-supported?
- **Completeness:** Is the answer comprehensive?
- **Clarity:** Is it well-structured and clear?

---

### 4. Structured Report Builder (`StructuredReportBuilder`)

**Purpose:** Generate multi-section reports with per-section citations.

**Pattern:** Structured synthesis (vs. simple prose)

**Usage:**
```python
from src.agent.research_optimizer import StructuredReportBuilder

builder = StructuredReportBuilder()

report = builder.build_report(
    query="How does climate change affect aquifers?",
    insights=[
        {"content": "Rising temps increase evaporation", "source_url": "https://..."},
        {"content": "Changed precipitation patterns", "source_url": "https://..."},
    ],
    research_plan=plan,
    visited_urls={"https://usgs.gov/...", "https://..."}
)

# Output structure:
# {
#   "title": "Research Report: ...",
#   "executive_summary": "...",
#   "sections": [
#     {
#       "heading": "Section 1 Title",
#       "content": "2-3 paragraphs of substantive content",
#       "confidence": 0.85,
#       "citations": ["url1", "url2"]  # Per-section
#     },
#     ...
#   ],
#   "conclusion": "...",
#   "further_research": "...",
#   "source_summary": {
#     "total_sources": 12,
#     "sources": [...]
#   },
#   "confidence_overall": 0.79,
#   "generated_at": "2026-03-16T..."
# }

# Access report
print(f"Title: {report['title']}")
print(f"Summary: {report['executive_summary']}")
print(f"Overall Confidence: {report['confidence_overall']:.2f}")

for section in report['sections']:
    print(f"\n## {section['heading']}")
    print(f"   Confidence: {section['confidence']:.2f}")
    print(f"   Citations: {len(section['citations'])} sources")
```

**Benefits:**
- Organized, professional structure
- Per-section confidence and citations
- Traceable sourcing
- Better for academic/formal use

---

### 5. Search Budget Manager (`SearchBudget`)

**Purpose:** Track API usage and enforce cost limits.

**Pattern:** ReSeek (budget-aware tool use for efficiency)

**Usage:**
```python
from src.agent.research_optimizer import SearchBudget

budget = SearchBudget(
    max_web_searches=10,
    max_kb_searches=20,
    cost_per_web_search=0.01,      # $0.01 per web search
    cost_per_kb_search=0.0,         # Free local KB search
)

# Check availability before searching
if budget.can_do_web_search():
    # Perform web search
    budget.record_web_search()

# Track usage
print(f"Web searches: {budget.web_searches_used}/{budget.max_web_searches}")
print(f"Total cost: ${budget.total_cost:.2f}")
print(f"Remaining budget: ${budget.remaining_budget():.2f}")

# Persist for resuming sessions
state = budget.to_dict()
# Later...
budget = SearchBudget.from_dict(state)
```

**Budget Tracking:**
- Per-type search limits (web, KB, API calls)
- Cost tracking by search type
- Remaining budget calculation
- Enforcement during research

---

### 6. Research Session Persistence (`ResearchSessionPersistence`)

**Purpose:** Save and restore research sessions for resumability.

**Pattern:** Session persistence (enables long-running research)

**Usage:**
```python
from src.agent.research_optimizer import ResearchSessionPersistence
from pathlib import Path

persistence = ResearchSessionPersistence(session_dir=Path("./research_sessions"))

# Save a session
session_data = {
    "original_query": "What is saltwater intrusion?",
    "current_query": "saltwater intrusion mechanisms",
    "insights_count": 5,
    "depth": 2,
    "max_depth": 3,
}
persistence.save_session("session_001", session_data)

# List saved sessions
sessions = persistence.list_sessions()  # ["session_001", "session_002", ...]

# Load a session
loaded = persistence.load_session("session_001")

# Delete a session
persistence.delete_session("session_001")
```

**Session Directory Structure:**
```
research_sessions/
├── session_001.json
├── session_002.json
└── session_abc123.json
```

---

## 🔄 Enhanced Research Flow

### Original Flow (v1)
```
Query → Search → Extract Insights → Synthesize Report → Return
```

### Enhanced Flow (v2)
```
Query
  ↓
[PLAN] Decompose into sub-questions & prioritize searches
  ↓
[SEARCH + RANK] Multi-source search with priority ranking
  ↓
[EXTRACT] Get insights from ranked results
  ↓
[BUILD REPORT] Create structured multi-section report
  ↓
[REFLECT] Evaluate quality & identify gaps
  ├→ If low quality: Re-search gaps & rebuild report (up to 2 loops)
  └→ If high quality: Continue
  ↓
[SAVE SESSION] Persist state for resumability
  ↓
Return (report, plan, reflection scores, budget info)
```

---

## 💻 API Reference

### Enhanced `DeepResearchAgent.research()`

```python
result = agent.research(
    query: str,                                    # Research question
    max_depth: int | None = None,                 # Override default depth
    timeout: float | None = None,                 # Override timeout
    progress_callback: Callable[[str, float], None] | None = None,
    session_id: str | None = None,                # Unique session ID
    resume: bool = False,                         # Resume saved session?
) -> dict:
    """
    Returns:
    {
        "session_id": "abc123",
        "query": "original query",
        "report": {...},                      # Structured report
        "research_plan": {...},               # Plan used (if planning enabled)
        "insights": [...],                     # Raw insights
        "reflection": {                        # Quality assessment (if reflection enabled)
            "quality_score": 0.78,
            "coverage_score": 0.82,
            "is_high_quality": True,
        },
        "search_budget": {...},                # Usage tracking (if budget enabled)
        "sources": ["url1", "url2", ...],
        "elapsed_seconds": 45.2,
        "stopped": False,
        "timed_out": False,
    }
    """
```

### Session Management

```python
# List all saved sessions
sessions = agent.list_sessions()  # ["session_001", "session_002", ...]

# Load a saved session
session_data = agent.load_session("session_001")

# Delete a session
agent.delete_session("session_001")

# Check search budget
status = agent.get_search_budget_status()
# {
#     "web_searches_used": 5,
#     "web_searches_max": 10,
#     "total_cost": 0.05,
#     "remaining_budget": 9.95,
#     "can_do_more_searches": True,
# }
```

---

## 🧪 Testing

Comprehensive test suite in `tests/agent/test_research_agent_v2.py`:

```bash
# Run all tests
pytest tests/agent/test_research_agent_v2.py -v

# Run specific test class
pytest tests/agent/test_research_agent_v2.py::TestPriorityRanker -v

# Run with coverage
pytest tests/agent/test_research_agent_v2.py --cov=src.agent
```

**Test Coverage:**
- Research planning decomposition
- Priority ranking algorithms
- Self-reflection quality detection
- Search budget tracking
- Session persistence
- All Awesome-Deep-Research patterns

---

## ✅ Acceptance Criteria (Session 13)

### 1. Research Planning
- ✅ Complex questions decomposed into 3-5 sub-questions
- ✅ Multiple research areas identified
- ✅ Search queries prioritized

### 2. Self-Reflection Quality Control
- ✅ Low-quality answers trigger re-search
- ✅ Quality scores calculated per section
- ✅ Missing areas automatically identified

### 3. Structured Report Output
- ✅ Multi-section report format (not prose)
- ✅ Per-section confidence scores
- ✅ Per-section citations
- ✅ Overall confidence calculation

### 4. Session Persistence
- ✅ Research state saved to disk
- ✅ Sessions resumable (with session_id + resume=True)
- ✅ Session listing and deletion

### 5. Reference Patterns Implemented
- ✅ **SmartSearch**: Priority ranking by relevance/trust/recency
- ✅ **ReSeek**: Budget-aware search with cost tracking
- ✅ **WebSeer**: Self-reflection quality control
- ✅ **O-Researcher**: Multi-step question decomposition

---

## 🚀 Usage Examples

### Example 1: Complex Research with All Features

```python
from src.agent.research_agent import DeepResearchAgent

agent = DeepResearchAgent(
    enable_planning=True,
    enable_reflection=True,
    enable_budget_management=True,
    enable_persistence=True,
    timeout_seconds=600,  # 10 minutes for complex query
)

def progress_update(message: str, progress: float):
    print(f"[{progress:.0%}] {message}")

result = agent.research(
    query="What are the long-term impacts of sea level rise on the Biscayne Aquifer?",
    session_id="biscayne_slr_2026",
    progress_callback=progress_update,
)

# Access structured report
report = result["report"]
print(f"Title: {report['title']}")
print(f"Summary: {report['executive_summary']}")
print(f"Sections: {len(report['sections'])}")
print(f"Overall confidence: {report['confidence_overall']:.2f}")

# Check if quality was satisfactory
reflection = result["reflection"]
print(f"Quality sufficient: {reflection['is_high_quality']}")

# Track API usage
budget = result["search_budget"]
print(f"Web searches used: {budget['web_searches_used']}/{budget['web_searches_max']}")
print(f"Total cost: ${budget['total_cost']:.2f}")
```

### Example 2: Resume Interrupted Research

```python
# Start research (might be interrupted)
result = agent.research(
    query="Complex research question",
    session_id="research_001",
)

# Later, resume if interrupted
if agent.is_running():
    agent.stop()

# Load and continue
resumed = agent.research(
    query="Complex research question",
    session_id="research_001",
    resume=True,  # Load previous state
)
```

### Example 3: Budget-Constrained Research

```python
agent = DeepResearchAgent(
    enable_budget_management=True,
)

# Set strict budget
agent.search_budget.max_web_searches = 5
agent.search_budget.cost_per_web_search = 0.02

result = agent.research(
    query="Research topic",
)

# Check final usage
budget_status = agent.get_search_budget_status()
print(f"Budget ratio: {budget_status['web_searches_used']}/{budget_status['web_searches_max']}")
```

---

## 📊 Performance Metrics

**Typical Research Session (Complex Query):**
- Planning: 2-3 seconds
- Search depth 1: 15-20 seconds
- Search depth 2: 20-30 seconds
- Search depth 3: 20-30 seconds
- Self-reflection: 5-10 seconds
- Report building: 5-10 seconds
- Total: 60-120 seconds

**Resource Usage:**
- Memory: ~50-100MB (knowledge base + session state)
- API calls: 5-15 web searches per session (configurable)
- Disk I/O: Session persistence (JSON, ~10-50KB per session)

---

## 🔧 Configuration

Enable/disable features at initialization:

```python
agent = DeepResearchAgent(
    # Core settings
    max_depth=3,
    timeout_seconds=300,
    
    # Advanced features (Session 13)
    enable_planning=True,           # Research decomposition
    enable_reflection=True,          # Quality control
    enable_budget_management=True,   # Cost tracking
    enable_persistence=True,         # Resume capability
)
```

Or configure via environment variables:

```bash
export GROUNDWATER_AGENT_PLANNING=true
export GROUNDWATER_AGENT_REFLECTION=true
export GROUNDWATER_AGENT_BUDGET_MGMT=true
export GROUNDWATER_AGENT_PERSISTENCE=true
```

---

## 🐛 Troubleshooting

### Research Quality Too Low
- Increase `max_depth` to allow more iterations
- Lower `reflector.min_quality_threshold` (default 0.7)
- Provide more context in research query

### Budget Exhausted Too Quickly
- Increase `SearchBudget.max_web_searches`
- Discard `enable_budget_management=False` for unlimited
- Focus research scope (use planning to target key queries)

### Research Times Out
- Increase `timeout_seconds`
- Reduce `max_depth`
- Use `session_id` + `resume=True` to continue

---

## 📚 References

- **Original Paper:** [Awesome-Deep-Research](https://github.com/DavidZWZ/Awesome-Deep-Research)
- **SmartSearch:** Iterative query optimization for relevance
- **ReSeek:** Budget-aware search strategies
- **WebSeer:** Self-reflection for quality control
- **O-Researcher:** Multi-agent query decomposition

---

## 🎯 Next Steps

**Future Enhancements:**
1. Parallel search execution (depth 2+ in parallel)
2. Multi-modal insights (images, tables, charts)
3. Human-in-the-loop refinement
4. Active learning (learn from user feedback)
5. Cross-domain knowledge synthesis

---

**Implemented by:** GitHub Copilot  
**Date:** March 2026  
**Status:** Ready for Production
