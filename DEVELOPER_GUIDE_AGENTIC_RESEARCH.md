# Developer Guide: Agentic Deep Research System

**Version:** 1.0  
**Date:** March 16, 2026  
**Status:** Ready for Integration

---

## Quick Start (5 minutes)

### 1. Import the System

```python
from src.agent import (
    GroundwaterResearchWorkflow,
    GroundwaterResearchModel,
    expand_groundwater_query,
    get_groundwater_model,
    AquiferType,
)
```

### 2. Create a Workflow

```python
# Initialize research workflow
workflow = GroundwaterResearchWorkflow(
    max_iterations=2,
    llm_provider="openai",  # or "anthropic", "ollama"
    llm_model="gpt-4",
)

# Execute research
results = workflow.research(
    query="What factors drive water level changes in Biscayne Aquifer over 5 years?"
)
```

### 3. Access Results

```python
# Report
print(results['report']['title'])
print(results['report']['executive_summary'])

# Quality metrics
print(f"Confidence: {results['quality_metrics']['final_confidence']:.2f}/1.0")
print(f"Coverage: {results['quality_metrics']['final_coverage']:.2f}/1.0")

# Statistics
print(f"Sources: {results['sources_count']}")
print(f"Time: {results['total_time_seconds']:.1f}s")
print(f"Cost: ${results['budget_used']['total_cost']:.2f}")
```

---

## Core Components

### 1. GroundwaterResearchWorkflow

**Purpose:** Orchestrates multi-phase research process

**Constructor:**
```python
workflow = GroundwaterResearchWorkflow(
    llm_provider: str | None = None,        # "openai", "anthropic", "ollama"
    llm_model: str | None = None,           # "gpt-4", "claude-3", etc.
    max_iterations: int = 3,                # Max reflection cycles
    session_dir: Path | None = None,        # Session persistence directory
    progress_callback: Callable = None,     # Real-time progress updates
)
```

**Methods:**
```python
# Main research execution
results = workflow.research(
    query: str,                             # Research question
    session_id: str | None = None,          # Resume from saved session
) -> dict

# Session management
sessions = workflow.list_sessions()         # List all saved sessions
context = workflow.get_session(session_id)  # Load a session
```

**Research Phases:**
1. **Planning**: Decompose query into sub-questions (O-Researcher)
2. **Search**: Execute prioritized queries (SmartSearch + ReSeek)
3. **Synthesis**: Build structured report (StructuredReportBuilder)
4. **Reflection**: Evaluate quality (WebSeer)
5. **Iteration**: Continue if gaps identified

**Return Structure:**
```python
{
    "session_id": "gwa_20260316_120000_abc12345",
    "query": "...",
    "research_plan": {...},                 # Sub-questions, search priority
    "report": {
        "title": "...",
        "executive_summary": "...",
        "sections": [...],                  # Multi-section report
        "source_summary": {...},
        "confidence_overall": 0.75,
    },
    "insights_count": 12,
    "sources_count": 8,
    "iterations": 2,
    "total_time_seconds": 45.3,
    "budget_used": {
        "web_searches": 5,
        "kb_searches": 12,
        "total_cost": 0.05,
    },
    "quality_metrics": {
        "final_confidence": 0.85,
        "final_coverage": 0.90,
    },
    "progress": ["Starting research...", "Planning...", "..."],
}
```

### 2. GroundwaterResearchModel

**Purpose:** Domain-specific groundwater knowledge and validation

**Methods:**
```python
# Get aquifer properties
aquifer = model.get_aquifer_info("biscayne")  # Returns AquiferProperties

# Validate water level data
result = model.validate_water_level_data(
    df: pd.DataFrame,                       # Must have 'elevation_ft' column
    aquifer_type: AquiferType,
    site_id: str,
) -> dict                                   # {valid, issues, warnings}

# Detect seasonal patterns
pattern = model.detect_seasonal_pattern(
    df: pd.DataFrame,
    aquifer_type: AquiferType,
    site_id: str,
    min_years: int = 2,
) -> SeasonalPattern | None

# Detect anomalies
anomalies = model.detect_anomalies(
    df: pd.DataFrame,
    aquifer_type: AquiferType,
    site_id: str,
    method: str = "zscore",                # "zscore" or "iqr"
    threshold: float = 3.0,
) -> list[AnomalyDetection]

# Analyze multi-site correlations
corr_matrix = model.analyze_multi_site_correlation(
    sites_data: Dict[str, pd.DataFrame],
    metric: str = "elevation_ft",
) -> Dict[str, Dict[str, float]]

# Expand research query
expanded = model.expand_research_query(query: str) -> list[str]
```

**Data Classes:**
```python
# Aquifer properties
@dataclass
class AquiferProperties:
    name: str
    aquifer_type: AquiferType                # BISCAYNE, FLORIDAN, SURFICIAL
    typical_depth_ft: Tuple[float, float]    # (min, max) below surface
    elevation_range_ft: Tuple[float, float]  # (min, max) MSL
    high_tide_sensitivity: bool
    rainfall_sensitivity_lag_days: int
    # ... more fields

# Detected seasonal pattern
@dataclass
class SeasonalPattern:
    site_id: str
    peak_month: int                          # 1-12
    peak_elevation: float                    # feet MSL
    trough_month: int
    trough_elevation: float
    annual_amplitude: float                  # feet
    predictability_score: float              # 0.0-1.0

# Detected anomaly
@dataclass
class AnomalyDetection:
    site_id: str
    date: datetime
    value: float                             # feet MSL
    expected_value: float
    deviation: float                         # feet
    anomaly_type: str                        # "spike", "drop", etc.
    severity: float                          # 0.0-1.0
    potential_cause: str
```

### 3. Priority Search Engine

**Purpose:** Intelligent multi-source searching with prioritization

**Components:**

1. **QueryPrioritizer**
```python
prioritizer = QueryPrioritizer(llm_provider="openai")

prioritized = prioritizer.prioritize_queries(
    queries: list[str],
    research_context: str = "",
    budget: SearchBudget | None = None,
) -> list[SearchQuery]                      # Sorted by priority
```

2. **MultiSourceSearchEngine**
```python
engine = MultiSourceSearchEngine(
    kb_searcher: Callable | None = None,    # Knowledge base search fn
    web_searcher: Callable | None = None,   # Web search function
    data_searcher: Callable | None = None,  # USGS data search fn
)

# Single search
results = engine.search(
    query: SearchQuery,
    num_results: int = 5,
    enforce_budget: bool = True,
) -> list[SearchResult]

# Batch search
all_results = engine.batch_search(
    queries: list[SearchQuery],
    num_results: int = 5,
) -> dict[str, list[SearchResult]]
```

3. **SearchPipeline**
```python
pipeline = SearchPipeline(
    kb_searcher=my_kb_search,
    web_searcher=my_web_search,
    data_searcher=my_data_search,
)

results = pipeline.execute(
    research_queries: list[str],
    research_context: str = "",
    num_results_per_query: int = 5,
) -> dict[str, list[SearchResult]]
```

---

## Integration Examples

### Example 1: Web Application

```python
# In FastAPI route
from fastapi import FastAPI
from src.agent import GroundwaterResearchWorkflow

app = FastAPI()

@app.post("/research")
async def start_research(query: str):
    def progress_callback(msg: str):
        # Send progress via WebSocket
        pass
    
    workflow = GroundwaterResearchWorkflow(
        progress_callback=progress_callback
    )
    results = workflow.research(query)
    return results

@app.get("/research/{session_id}")
async def get_research(session_id: str):
    workflow = GroundwaterResearchWorkflow()
    context = workflow.get_session(session_id)
    return context
```

### Example 2: Data Pipeline

```python
# Validate USGS data before analysis
from src.agent import validate_groundwater_data, AquiferType
import pandas as pd

df = pd.read_csv("usgs_biscayne_data.csv")
validation = validate_groundwater_data(df, AquiferType.BISCAYNE, "USG_001")

if validation["valid"]:
    # Process data
    model = get_groundwater_model()
    pattern = model.detect_seasonal_pattern(df, AquiferType.BISCAYNE)
else:
    # Handle validation errors
    print(f"Data issues: {validation['issues']}")
```

### Example 3: Research Notebook

```python
# In Jupyter notebook
from src.agent import GroundwaterResearchWorkflow

workflow = GroundwaterResearchWorkflow(max_iterations=3)

# Execute research
results = workflow.research(
    query="How has Biscayne Aquifer responded to climate change?"
)

# Analyze results
import json
print(json.dumps(results['report'], indent=2))

# Visualize research quality
import matplotlib.pyplot as plt
plt.bar(
    ["Confidence", "Coverage"],
    [
        results['quality_metrics']['final_confidence'],
        results['quality_metrics']['final_coverage'],
    ]
)
plt.show()
```

---

## Advanced Usage

### Custom LLM Provider

```python
workflow = GroundwaterResearchWorkflow(
    llm_provider="anthropic",
    llm_model="claude-3-opus",
)

# Or with Ollama locally
workflow = GroundwaterResearchWorkflow(
    llm_provider="ollama",
    llm_model="llama2",
)
```

### Session Management

```python
# Save session after research
results = workflow.research(query)
session_id = results['session_id']

# Later: Resume research
results = workflow.research(query, session_id=session_id)

# List all sessions
sessions = workflow.list_sessions()
# → ["gwa_20260316_120000_abc12345", "gwa_20260316_130000_def67890", ...]

# Load session data
context = workflow.get_session(session_id)
```

### Progress Tracking

```python
def my_progress_callback(message: str):
    print(f"[PROGRESS] {message}")
    # Or send to frontend via WebSocket
    # Or log to monitoring system

workflow = GroundwaterResearchWorkflow(
    progress_callback=my_progress_callback
)

results = workflow.research("Your question")
# Prints progress at each phase
```

### Batch Research

```python
questions = [
    "What drives Biscayne water levels?",
    "How does rainfall affect Floridan Aquifer?",
    "What are Surficial Aquifer trends?",
]

workflow = GroundwaterResearchWorkflow()

results_list = []
for question in questions:
    results = workflow.research(question)
    results_list.append(results)

# Analyze combined results
total_sources = sum(r['sources_count'] for r in results_list)
avg_confidence = np.mean([r['quality_metrics']['final_confidence'] for r in results_list])
```

---

## Configuration

### Aquifer Properties

Edit in `src/agent/groundwater_research_model.py`:
```python
FLORIDA_AQUIFERS = {
    "biscayne": AquiferProperties(...),
    "floridan": AquiferProperties(...),
    "surficial": AquiferProperties(...),
}
```

### Search Budget

Edit in `src/agent/research_optimizer.py`:
```python
SearchBudget(
    max_web_searches=10,          # Limit API calls
    max_kb_searches=20,           # Free, local
    max_api_calls=50,
    cost_per_web_search=0.01,
    total_budget=10.0,            # $10 limit
)
```

### LLM Models

Supported providers:
- **OpenAI**: `gpt-4`, `gpt-3.5-turbo`
- **Anthropic**: `claude-3-opus`, `claude-3-sonnet`
- **Ollama**: `llama2`, `llama2-uncensored`, etc.

Set via environment:
```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

---

## Troubleshooting

### LLM Not Responding

```python
# Check LLM connection
from src.agent import get_llm

llm = get_llm(provider="openai")
response = llm.invoke("Hello, world!")
print(response.content)
```

### Search Budget Exhausted

```python
# Check budget status
status = engine.search_engine.get_budget_status()
print(f"Web searches used: {status['web_searches_used']}/{status['web_searches_max']}")
print(f"Cost: ${status['total_cost']:.2f}")
print(f"Remaining: ${status['remaining_budget']:.2f}")
```

### No Patterns Detected

```python
# Ensure sufficient data
if len(df) < 730:  # ~2 years
    print("Need at least 2 years of data for seasonal pattern detection")

# Check data quality
validation = model.validate_water_level_data(df, aquifer_type, site_id)
if not validation["valid"]:
    print(f"Data issues: {validation['issues']}")
```

---

## Testing

### Run All Tests

```bash
pytest tests/agent/test_groundwater_research_model.py -v
pytest tests/agent/test_priority_search_engine.py -v
```

### Run Specific Test

```bash
pytest tests/agent/test_groundwater_research_model.py::TestSeasonalPatternDetection -v
```

### Test with Coverage

```bash
pytest tests/agent/ --cov=src.agent --cov-report=html
```

---

## Performance Tips

1. **Reuse Workflow Instance**
   ```python
   workflow = GroundwaterResearchWorkflow()  # Create once
   for query in queries:
       results = workflow.research(query)    # Reuse instance
   ```

2. **Use Session Persistence**
   ```python
   # Save after long operations
   results = workflow.research(query)
   session_id = results['session_id']
   
   # Resume later without re-searching
   results = workflow.research(query, session_id=session_id)
   ```

3. **Limit Iterations**
   ```python
   workflow = GroundwaterResearchWorkflow(max_iterations=1)  # Fast but less thorough
   ```

4. **Cache Results**
   ```python
   import pickle
   with open(f"research_{session_id}.pkl", "wb") as f:
       pickle.dump(results, f)
   ```

---

## API Reference

See docstrings in source files:
- `src/agent/research_workflow.py`
- `src/agent/groundwater_research_model.py`
- `src/agent/priority_search_engine.py`
- `src/agent/research_optimizer.py`

---

**Version:** 1.0  
**Last Updated:** March 16, 2026  
**Status:** Production Ready
