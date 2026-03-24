# Task 1.1 Analysis: Canonical Pipeline Implementation

**Date:** February 18, 2026  
**Status:** Pre-Implementation Analysis  
**Priority:** ⭐ HIGHEST  

---

## 📋 Executive Summary

This document provides the engineering analysis for implementing Task 1.1: Create a canonical `src/data/pipeline.py` that centralizes all data fetching logic currently scattered across `download_data.py` (422 lines) and `continuous_learning.py` (482 lines).

---

## 🔍 Current State Analysis

### Existing Data Infrastructure

| Component | Location | Lines | Status |
|-----------|----------|-------|--------|
| **USGS Download** | `src/data/download_data.py` | 422 | Functional, single-site |
| **Continuous Learning** | `src/data/continuous_learning.py` | 482 | Multi-site, KB integration |
| **Data Config** | `config/config.py` | 122 | Minimal (needs expansion) |
| **Tests** | `tests/data/` | 493 | Comprehensive integrity tests |
| **API** | `api/main.py` | 661 | Serves 36 sites from CSV files |

### Data Flow

```
USGS NWIS API
    ↓
fetch_usgs_groundwater() [download_data.py:49-155]
    ↓
ContinuousLearner.fetch_usgs_site_data() [continuous_learning.py:162-220]
    ↓
CSV files (data/usgs_*.csv) × 36 sites
    ↓
FastAPI endpoints [api/main.py]
    ↓
React Dashboard (frontend)
```

### Problem Statement

**What's scattered:**
- `fetch_usgs_groundwater()`: Single site, basic retry, parameter code handling
- `ContinuousLearner.fetch_usgs_site_data()`: Multi-site, better error handling, KB integration
- `ContinuousLearner.fetch_all_florida_aquifer_data()`: Orchestrates 36 sites but tightly coupled to KB

**Why it matters:**
- No single source of truth for data pipeline orchestration
- Duplicated API call logic
- Hard to track data flow and quality
- Difficult to implement features like scheduled refreshes or health monitoring
- Testing is fragmented across two modules

---

## 📊 Requirements Specification

### Functional Requirements

#### FR1: Single Orchestrator Function
```python
def run_pipeline(
    sites: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    output_format: str = 'csv',
    parallel: bool = True,
) -> Dict[str, Path]:
    """
    Main pipeline orchestrator for USGS groundwater data.
    
    Returns: {site_id: output_path, ...}
    """
```

**Behavior:**
- If `sites=None`: Process all 36 configured sites
- If `sites=['251241080385301']`: Process only that site
- Return dictionary: `{'251241080385301': Path('data/usgs_251241080385301_20260218.csv'), ...}`

#### FR2: Robust Error Handling
- Exponential backoff retry (max 3 attempts)
- Graceful degradation (log errors, continue with other sites)
- No partial failures block entire pipeline

#### FR3: Data Quality Validation
- Verify timestamp field exists and is parseable
- Verify site_id field matches filename
- Verify water_level values are numeric and in valid range
- Log validation results to structured manifest

#### FR4: Feature Engineering (Optional Layer)
- Compute lag features (1, 3, 7, 14, 30 days)
- Compute rolling means (7, 14, 30 day windows)
- Prevent data leakage (features only for valid targets)

#### FR5: Artifact Management
- Timestamped output files: `usgs_{site_id}_{YYYYMMDD}.csv`
- Manifest file: `pipeline_manifest_{YYYYMMDD}.json`
- Logging: `pipeline_run_{YYYYMMDD}.log`

#### FR6: Parallel Processing
- Optional parallelization for all 36 sites
- Max workers configurable
- Thread-safe file I/O

---

## 🏗️ Architecture Design

### Module Structure

```
src/data/
├── __init__.py              (export run_pipeline)
├── pipeline.py              (NEW: Main orchestrator)
│   ├── run_pipeline()       (Main entry point)
│   ├── validate_data()      (Schema validation)
│   ├── engineer_features()  (Feature generation)
│   └── _fetch_single_site() (Internal: fetch one site)
├── download_data.py         (EXISTING: Keep for CLI, refactor to use pipeline)
├── continuous_learning.py   (EXISTING: Refactor to use pipeline)
└── config/
    └── usgs_sites.json      (NEW: Site configuration)
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Function-based** | Simple, testable, easy to parallelize |
| **Dict return value** | Enables flexible output handling |
| **Optional parallel** | Default parallel=True for speed, can disable for debugging |
| **Separated concerns** | fetch → validate → engineer → save |
| **Stateless design** | No global state, easy to run multiple times |
| **Manifest tracking** | Enables audit trail and health monitoring |

---

## 🧪 Testing Strategy

### Unit Tests (test_pipeline.py)

| Test | Purpose | Acceptance Criteria |
|------|---------|-------------------|
| `test_run_pipeline_all_sites` | All 36 sites fetchable | Returns 36 file paths |
| `test_run_pipeline_single_site` | Single site works | Returns 1 file path |
| `test_run_pipeline_empty_sites` | Empty list handled | Returns {} |
| `test_data_validation_passes` | Valid data accepted | No errors logged |
| `test_data_validation_fails` | Invalid data rejected | Error logged, continues |
| `test_feature_engineering` | Features computed | Lag columns exist, no NaN in early rows |
| `test_parallel_vs_sequential` | Parallel returns same as sequential | Deterministic results |
| `test_manifest_generation` | Manifest created | Valid JSON with all sites |
| `test_timestamp_output` | Output files timestamped | Pattern: `usgs_{site}_{YYYYMMDD}.csv` |
| `test_logging_created` | Log file created | Path exists, contains info level |

### Integration Tests (test_usgs_data_integrity.py)

Extend existing tests to verify pipeline output:
- Verify pipeline output matches fastAPI expectations
- Verify manifest statistics match actual files
- Verify all 36 sites can be fetched in <30 minutes

---

## 📦 Implementation Plan

### Phase 1: Core Pipeline (1.5 days)

**Deliverables:**
- `src/data/pipeline.py` with `run_pipeline()` function
- Schema validation module
- Proper exception handling and logging
- 95%+ test coverage

**Acceptance:**
- Can fetch all 36 sites
- Produces timestamped CSV files
- Validation catches bad data
- Runs in <30 minutes

### Phase 2: Feature Engineering (0.5 days)

**Deliverables:**
- Optional feature engineering layer
- Lag and rolling window features
- Prevent data leakage checks

### Phase 3: Refactoring (0.5 days)

**Deliverables:**
- Update `download_data.py` to use `run_pipeline()`
- Update `continuous_learning.py` to use `run_pipeline()`
- Update tests to use new pipeline
- Verify no regressions

---

## 🔗 Dependencies & Integration Points

### Upstream Dependencies
- `config.config`: REGIONS, TIME_CONFIG, DATA_DIR, USGS_SITES
- `src/agent/source_verification`: verify_usgs_data() (optional)
- External: USGS NWIS API

### Downstream Consumers
- `api/main.py`: Serves pipeline outputs
- `src/data/continuous_learning.py`: Adds to KB
- `src/ml/train_groundwater.py`: Trains models

### Breaking Changes
None. Pipeline is additive. Existing code continues working.

---

## 📋 Success Criteria

- [ ] `run_pipeline()` completes for all 36 sites in <30 minutes
- [ ] Returns Dict[str, Path] with correct file paths
- [ ] Each CSV has 3+ columns: site_no, datetime, value
- [ ] Data validation catches 100% of schema errors
- [ ] Manifest JSON tracks all sites and metrics
- [ ] Logging captures complete pipeline execution
- [ ] 95%+ test coverage of new code
- [ ] No regression in existing tests
- [ ] Inline documentation explains design decisions
- [ ] Follows ENGINEERING_STANDARDS.md

---

## 📚 Reference Implementation Details

### Config Structure (src/data/config/usgs_sites.json)
```json
{
  "biscayne": [
    {"site_id": "251241080385301", "name": "Miami-Dade G-3764", "county": "Miami-Dade"},
    ...
  ],
  "floridan": [...],
  ...
}
```

### Return Value Structure
```python
{
  '251241080385301': Path('data/usgs_251241080385301_20260218.csv'),
  '251457080395802': Path('data/usgs_251457080395802_20260218.csv'),
  ...
}
```

### Manifest Structure (data/pipeline_manifest_20260218.json)
```json
{
  "timestamp": "2026-02-18T14:30:00Z",
  "duration_seconds": 125,
  "sites_processed": 36,
  "sites_successful": 36,
  "sites_failed": 0,
  "total_records": 106628,
  "output_format": "csv",
  "output_files": {
    "251241080385301": "data/usgs_251241080385301_20260218.csv",
    ...
  },
  "validation_results": {
    "schema_errors": 0,
    "value_range_errors": 0,
    "datetime_errors": 0
  },
  "errors": []
}
```

---

## ⚙️ Configuration

### Environment Variables
```bash
USGS_API_TIMEOUT=60          # seconds
USGS_API_RETRY_MAX=3
USGS_API_BACKOFF_FACTOR=2
USGS_PIPELINE_PARALLEL=true
USGS_PIPELINE_MAX_WORKERS=8
```

### Code Configuration (config.py)
```python
USGS_PIPELINE = {
    'timeout': 60,
    'retry_max': 3,
    'backoff_factor': 2,
    'parallel': True,
    'max_workers': 8,
}
```

---

## 🚀 Next Steps

1. **Review this analysis** with team (if applicable)
2. **Implement core pipeline** (1.5 days)
3. **Write comprehensive tests** (parallel)
4. **Refactor existing code** to use pipeline
5. **Verify no regressions** against test suite
6. **Document decisions** in code comments

