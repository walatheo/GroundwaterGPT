# Software Engineering Standards

**Last Updated:** February 4, 2026
**Version:** 1.0
**Purpose:** Establish rigorous engineering practices for research-grade accuracy

---

## 📋 Table of Contents

1. [Core Principles](#-core-principles)
2. [Code Review Standards](#-code-review-standards)
3. [Testing Philosophy](#-testing-philosophy)
4. [Code Modularity & Design](#-code-modularity--design)
5. [Research Accuracy Standards](#-research-accuracy-standards)
6. [Bug Resolution Process](#-bug-resolution-process)
7. [Optimization Guidelines](#-optimization-guidelines)
8. [Anti-Patterns to Avoid](#-anti-patterns-to-avoid)

---

## 🎯 Core Principles

### 1. Correctness Over Convenience

```
❌ WRONG: Make the test pass by any means
✅ RIGHT: Understand WHY the test fails, then fix the ROOT CAUSE
```

**The Research Integrity Rule:**
> This project serves research purposes. Inaccurate data or incorrect implementations
> can lead to flawed scientific conclusions. Every line of code must be defensible.

### 2. Understand Before Implementing

Before writing any code:
1. **Understand the problem** - What are we solving?
2. **Research approaches** - What are the standard solutions?
3. **Evaluate alternatives** - Which approach fits our constraints?
4. **Document the decision** - Why did we choose this approach?

### 3. Simplicity Hierarchy

Prefer solutions in this order:
1. **Use existing, proven library** (e.g., pandas, scikit-learn)
2. **Compose existing functions** (reuse what we have)
3. **Write simple, single-purpose function** (do one thing well)
4. **Build complex solution** (only if absolutely necessary)

---

## 🔍 Code Review Standards

### Pre-Review Checklist (Author)

Before requesting review:

```markdown
- [ ] Code compiles and runs without errors
- [ ] All tests pass (existing + new)
- [ ] I understand every line of code I wrote
- [ ] I can explain WHY I chose this approach
- [ ] I considered at least 2 alternative approaches
- [ ] No commented-out code or TODO hacks
- [ ] Documentation is updated
- [ ] No hardcoded values (use config)
```

### Review Criteria (Reviewer)

| Category | Questions to Ask |
|----------|------------------|
| **Correctness** | Does this solve the actual problem? |
| **Edge Cases** | What happens with empty data? Null values? |
| **Data Integrity** | Can this corrupt or misrepresent data? |
| **Simplicity** | Is there a simpler way to do this? |
| **Duplication** | Does similar code exist elsewhere? |
| **Dependencies** | Does this create tight coupling? |
| **Testability** | Can this be unit tested in isolation? |
| **Performance** | Will this scale with more data/users? |

### Review Response Standards

**When providing feedback:**

```markdown
# Good Review Comment
"This approach uses O(n²) time complexity due to the nested loop on lines 45-52.
Consider using a dictionary lookup instead, which would be O(n). Here's an example:
```python
lookup = {item.id: item for item in items}  # O(n)
result = lookup.get(target_id)  # O(1)
```"

# Bad Review Comment
"This is slow, fix it."
```

**When receiving feedback:**
- Don't take it personally
- Ask clarifying questions if unclear
- Explain your reasoning if you disagree
- Document the final decision

---

## 🧪 Testing Philosophy

### The Cardinal Rule of Testing

> **NEVER modify a test just to make it pass.**
> If a test fails, the test is telling you something important.

### When a Test Fails

Follow this decision tree:

```
Test Fails
    │
    ├── Is the test correct?
    │   ├── YES → Fix the implementation
    │   └── NO → Why is the test wrong?
    │           ├── Requirements changed → Update test WITH documentation
    │           ├── Test has a bug → Fix the test bug
    │           └── Test is flaky → Make test deterministic
    │
    └── Document WHY the test failed and what you learned
```

### Test Categories

| Category | Purpose | When to Write |
|----------|---------|---------------|
| **Unit Tests** | Test single functions in isolation | Every new function |
| **Integration Tests** | Test components working together | Every API endpoint |
| **Data Validation Tests** | Verify data integrity | Data pipeline changes |
| **Regression Tests** | Prevent bugs from returning | Every bug fix |
| **Accuracy Tests** | Verify research correctness | Model/analysis changes |

### Testing Anti-Patterns

```python
# ❌ ANTI-PATTERN: Overly permissive assertion
def test_water_level():
    result = get_water_level()
    assert result is not None  # Too weak! What value?

# ✅ CORRECT: Specific, meaningful assertion
def test_water_level_for_known_site():
    """Test water level for USGS site 262724081260701 (Lee County).

    Expected value based on verified USGS API response for 2024-01-01.
    """
    result = get_water_level("262724081260701", "2024-01-01")
    assert 20.0 <= result <= 35.0, f"Water level {result} outside expected range"
    assert isinstance(result, float), "Water level should be float"
```

```python
# ❌ ANTI-PATTERN: Catching all exceptions to make test pass
def test_data_processing():
    try:
        result = process_data(bad_data)
        assert True  # NEVER DO THIS
    except:
        pass  # Hiding the real problem

# ✅ CORRECT: Test specific exception behavior
def test_data_processing_with_invalid_input():
    """Verify proper error handling for malformed data."""
    with pytest.raises(ValueError, match="Missing required column"):
        process_data({"wrong_column": [1, 2, 3]})
```

### Test Documentation Requirements

Every test file must include:

```python
"""
Test Module: [Name]

Purpose:
    [What aspect of the system is being tested]

Ground Truth Source:
    [Where did expected values come from? USGS API? Manual calculation?]

Coverage:
    - [List of scenarios covered]
    - [Edge cases tested]

Known Limitations:
    - [What is NOT tested and why]
"""
```

---

## 🧱 Code Modularity & Design

### Single Responsibility Principle

Each module/function should have ONE reason to change.

```python
# ❌ BAD: Function does too many things
def process_and_save_and_visualize(data):
    cleaned = clean_data(data)
    model = train_model(cleaned)
    save_model(model)
    create_plot(model)
    save_plot()
    send_email()

# ✅ GOOD: Separate concerns
def clean_data(data: pd.DataFrame) -> pd.DataFrame:
    """Clean and validate groundwater data."""
    ...

def train_model(data: pd.DataFrame) -> Model:
    """Train prediction model on cleaned data."""
    ...

def save_model(model: Model, path: Path) -> None:
    """Persist model to disk."""
    ...

# Compose in orchestration layer
def run_pipeline():
    data = load_data()
    cleaned = clean_data(data)
    model = train_model(cleaned)
    save_model(model, MODEL_PATH)
```

### Dependency Injection

Functions should receive their dependencies, not create them.

```python
# ❌ BAD: Hidden dependency
def get_water_level(site_id: str) -> float:
    df = pd.read_csv("data/groundwater.csv")  # Hidden file dependency
    return df[df["site"] == site_id]["level"].iloc[0]

# ✅ GOOD: Explicit dependency
def get_water_level(site_id: str, data: pd.DataFrame) -> float:
    """Get water level for a site from provided data.

    Args:
        site_id: USGS 15-digit site identifier
        data: DataFrame with 'site' and 'level' columns

    Returns:
        Water level in feet
    """
    return data[data["site"] == site_id]["level"].iloc[0]
```

### Configuration Management

```python
# ❌ BAD: Magic numbers scattered in code
def predict(data):
    if len(data) < 30:  # What is 30?
        return None
    window = data[-7:]  # What is 7?
    threshold = 0.85  # What is 0.85?

# ✅ GOOD: Named configuration
# config.py
class ModelConfig:
    MIN_TRAINING_SAMPLES = 30  # Minimum days for reliable prediction
    PREDICTION_WINDOW_DAYS = 7  # Days of history for prediction
    CONFIDENCE_THRESHOLD = 0.85  # Minimum R² for valid model

# model.py
from config import ModelConfig

def predict(data, config: ModelConfig = ModelConfig()):
    if len(data) < config.MIN_TRAINING_SAMPLES:
        raise InsufficientDataError(
            f"Need {config.MIN_TRAINING_SAMPLES} samples, got {len(data)}"
        )
    window = data[-config.PREDICTION_WINDOW_DAYS:]
    ...
```

### When to Delete Code

Delete code when:

1. **Duplicate functionality exists** - Keep the better implementation
2. **Code is unreachable** - No execution path leads to it
3. **Feature is abandoned** - Requirements changed
4. **Workaround is no longer needed** - Root cause was fixed
5. **Abstraction is wrong** - Simpler approach exists

**Before deleting:**
- Verify no other code depends on it
- Check git history for context on why it was added
- Document the deletion in commit message

---

## 📊 Research Accuracy Standards

### Data Quality Principles

For research-grade accuracy:

| Principle | Implementation |
|-----------|----------------|
| **No data fabrication** | All data from verified sources (USGS API) |
| **No cherry-picking** | Include ALL sites, not just favorable ones |
| **Transparent processing** | Document every transformation |
| **Reproducibility** | Same inputs → same outputs |
| **Version control** | Track data lineage |

### Machine Learning Accuracy

#### Preventing Data Leakage

```python
# ❌ DATA LEAKAGE: Using future data to predict past
df['rolling_mean'] = df['value'].rolling(7).mean()  # Uses future values!
X = df[['rolling_mean']]
y = df['value']

# ✅ CORRECT: Only use past data
def create_lag_features(df: pd.DataFrame, lags: list[int]) -> pd.DataFrame:
    """Create features using only past data.

    Note: This prevents data leakage by only looking backward.
    """
    result = df.copy()
    for lag in lags:
        result[f'value_lag_{lag}'] = result['value'].shift(lag)
    # Drop rows where lag features are NaN (insufficient history)
    return result.dropna()
```

#### Proper Train/Test Split

```python
# ❌ WRONG: Random split for time series (data leakage)
X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)

# ✅ CORRECT: Temporal split (respect time order)
def temporal_split(df: pd.DataFrame, test_ratio: float = 0.2) -> tuple:
    """Split time series data respecting temporal order.

    Training data is ALWAYS before test data. This prevents
    using future information to predict the past.
    """
    split_idx = int(len(df) * (1 - test_ratio))
    train = df.iloc[:split_idx]
    test = df.iloc[split_idx:]

    # Verify no overlap
    assert train.index.max() < test.index.min(), "Data leakage detected!"

    return train, test
```

#### Overfitting Detection

Signs of overfitting:
- Training R² much higher than test R² (e.g., 0.99 vs 0.70)
- Model complexity much higher than necessary
- Performance degrades with new data

```python
def check_overfitting(train_score: float, test_score: float) -> str:
    """Detect potential overfitting.

    Returns warning message if overfitting suspected.
    """
    gap = train_score - test_score

    if gap > 0.15:
        return f"WARNING: Likely overfitting. Train R²={train_score:.3f}, Test R²={test_score:.3f}, Gap={gap:.3f}"
    elif gap > 0.10:
        return f"CAUTION: Possible overfitting. Gap={gap:.3f}. Consider regularization."
    else:
        return f"OK: Train-test gap acceptable ({gap:.3f})"
```

#### Underfitting Detection

Signs of underfitting:
- Both train and test scores are low
- Model is too simple for the data complexity
- Clear patterns visible in residuals

```python
def check_underfitting(train_score: float, baseline_score: float = 0.0) -> str:
    """Detect potential underfitting.

    Args:
        train_score: Model's R² on training data
        baseline_score: R² of naive baseline (e.g., predicting mean)
    """
    if train_score < 0.5:
        return f"WARNING: Likely underfitting. Train R²={train_score:.3f} is low."
    elif train_score < baseline_score + 0.1:
        return f"WARNING: Model barely beats baseline. Consider more features or complexity."
    else:
        return f"OK: Training score acceptable ({train_score:.3f})"
```

### Evaluation Best Practices

| Metric | Use Case | Pitfall |
|--------|----------|---------|
| **R²** | Overall fit | Can be misleading for non-linear relationships |
| **RMSE** | Penalizes large errors | Sensitive to outliers |
| **MAE** | Average error magnitude | Less sensitive to outliers |
| **MAPE** | Percentage error | Undefined when actual = 0 |

**Always report multiple metrics:**

```python
def evaluate_model(y_true, y_pred) -> dict:
    """Comprehensive model evaluation.

    Returns multiple metrics for complete picture.
    """
    return {
        'r2': r2_score(y_true, y_pred),
        'rmse': np.sqrt(mean_squared_error(y_true, y_pred)),
        'mae': mean_absolute_error(y_true, y_pred),
        'max_error': np.max(np.abs(y_true - y_pred)),
        'n_samples': len(y_true),
        'date_range': f"{y_true.index.min()} to {y_true.index.max()}"
    }
```

---

## 🐛 Bug Resolution Process

### When a Bug is Found

1. **Reproduce** - Can you consistently trigger the bug?
2. **Isolate** - What is the minimal input that causes it?
3. **Understand** - WHY does it happen? (Don't guess!)
4. **Fix** - Address the ROOT CAUSE, not symptoms
5. **Test** - Write a test that catches this bug
6. **Document** - What was learned?

### Bug Fix Template

```markdown
## Bug Report

**Observed Behavior:**
[What actually happens]

**Expected Behavior:**
[What should happen]

**Reproduction Steps:**
1. [Step 1]
2. [Step 2]
3. [Bug occurs]

**Root Cause Analysis:**
[WHY did this bug occur? What was the actual problem?]

**Fix Applied:**
[What code was changed and why]

**Regression Test Added:**
[Link to test that prevents this bug from returning]

**Lessons Learned:**
[What can we do to prevent similar bugs?]
```

### Common Data Science Bugs

| Bug Type | Symptom | Real Cause |
|----------|---------|------------|
| **Data leakage** | Unrealistically high accuracy | Future data in training |
| **Off-by-one** | Predictions shifted by 1 day | Index alignment error |
| **NaN propagation** | Model returns NaN | Missing data not handled |
| **Type coercion** | Wrong calculations | String vs numeric types |
| **Timezone issues** | Data misalignment | Mixed or missing timezones |

---

## ⚡ Optimization Guidelines

### When to Optimize

**Don't optimize unless:**
1. You have measured a performance problem
2. You know WHERE the bottleneck is (profile first!)
3. The optimization is worth the complexity cost

### Optimization Decision Framework

```
Performance Problem Detected
    │
    ├── Is it actually slow? (Measure!)
    │   └── NO → Don't optimize
    │
    ├── Profile to find bottleneck
    │   └── Is the bottleneck in YOUR code?
    │       ├── NO → Can't optimize (library/system)
    │       └── YES → Continue
    │
    ├── Can you use a better algorithm?
    │   └── YES → Do that first (biggest gains)
    │
    ├── Can you reduce work done?
    │   └── YES → Cache, batch, or skip unnecessary work
    │
    └── Only then consider micro-optimizations
```

### Common Performance Patterns

```python
# ❌ SLOW: Appending to list in loop, then converting
result = []
for item in large_list:
    result.append(expensive_calculation(item))
df = pd.DataFrame(result)

# ✅ FASTER: Use pandas vectorized operations
df['result'] = df['input'].apply(expensive_calculation)

# ✅ EVEN FASTER: Use numpy vectorization if possible
results = vectorized_calculation(df['input'].values)
```

---

## 🚫 Anti-Patterns to Avoid

### 1. Copy-Paste Programming

```python
# ❌ BAD: Duplicated code
def get_miami_dade_sites():
    df = pd.read_csv("data/sites.csv")
    return df[df["county"] == "Miami-Dade"]

def get_lee_sites():
    df = pd.read_csv("data/sites.csv")
    return df[df["county"] == "Lee"]

# ✅ GOOD: Parameterized function
def get_sites_by_county(county: str) -> pd.DataFrame:
    df = pd.read_csv("data/sites.csv")
    return df[df["county"] == county]
```

### 2. God Functions

```python
# ❌ BAD: Function does everything
def do_everything(input_file, output_file, model_type, ...):
    # 500 lines of code doing 20 different things
    ...

# ✅ GOOD: Composable functions
def load_data(path: Path) -> pd.DataFrame: ...
def validate_data(df: pd.DataFrame) -> pd.DataFrame: ...
def train_model(df: pd.DataFrame) -> Model: ...
def evaluate_model(model: Model, test_data: pd.DataFrame) -> Metrics: ...
def save_results(metrics: Metrics, path: Path) -> None: ...
```

### 3. Silent Failures

```python
# ❌ BAD: Swallowing exceptions
try:
    result = risky_operation()
except:
    pass  # What went wrong? We'll never know

# ✅ GOOD: Explicit error handling
try:
    result = risky_operation()
except ValueError as e:
    logger.error(f"Invalid value in operation: {e}")
    raise
except ConnectionError as e:
    logger.warning(f"Connection failed, using cached data: {e}")
    result = load_cached_data()
```

### 4. Premature Abstraction

```python
# ❌ BAD: Over-engineering for imaginary requirements
class AbstractDataLoaderFactory(ABC):
    @abstractmethod
    def create_loader(self, loader_type: str) -> DataLoader:
        ...

# ✅ GOOD: Simple solution for current needs
def load_usgs_data(site_id: str) -> pd.DataFrame:
    """Load USGS data for a specific site."""
    return pd.read_csv(f"data/usgs_{site_id}.csv")
```

---

## 📚 Resources

### Recommended Reading

- **Clean Code** by Robert Martin - Code quality principles
- **Refactoring** by Martin Fowler - Improving existing code
- **The Pragmatic Programmer** - General software craftsmanship
- **Python Data Science Handbook** - Data analysis best practices
- **Scikit-learn Documentation** - ML best practices

### Data Science Specific

- [Scikit-learn: Avoiding Data Leakage](https://scikit-learn.org/stable/common_pitfalls.html)
- [Google ML Best Practices](https://developers.google.com/machine-learning/guides/rules-of-ml)
- [USGS Water Data Documentation](https://waterdata.usgs.gov/nwis/help)

---

*This document is a living standard. Propose changes via PR with justification.*
