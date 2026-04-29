"""
Pytest configuration and shared fixtures.

This module provides common test fixtures used across all test modules.
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Unit tests exercise deterministic fallback paths unless a test opts into a
# stubbed live agent. Keep imports offline-safe so pytest never tries to fetch
# embedding or LLM artifacts from external services during collection.
os.environ.setdefault("GROUNDWATERGPT_SKIP_AGENT_INIT", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
# Disable LangGraph self-consistency sampling by default: its sample loop calls
# real LLMs, which would pull Ollama over the wire during unit tests. Tests
# that want to exercise the graph can re-enable it explicitly.
os.environ.setdefault("GROUNDWATERGPT_ENABLE_LANGGRAPH_INTERPRETER", "false")
# Unit tests must not reach real Qwen/Ollama endpoints through
# `_invoke_structured_llm`. Tests that exercise the structured-LLM path opt in
# by deleting this env var (via `monkeypatch.delenv`) and injecting a fake
# `src.agent.llm_factory` into `sys.modules`.
os.environ.setdefault("GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS", "1")


def _install_llm_stubs() -> None:
    """Hard-replace module-level LLM entry points with deterministic no-ops.

    Done at collection time so the stubs survive across every test — a
    per-test autouse ``monkeypatch`` fixture loses its effect if a prior test
    reloads the module or swaps the attribute back before the next test's
    fixture sets up.
    """
    try:
        from api.routes.answering import followups as _ega

        _ega._invoke_progression_rewrite = lambda *a, **k: None  # type: ignore[assignment]
    except Exception:
        pass
    try:
        from src.agent import research_optimizer as _ro

        _ro.get_llm = lambda *a, **k: None  # type: ignore[assignment]
    except Exception:
        pass
    # `_chart_interpreter.invoke_grounded_reasoning` is imported at module
    # load from `answering.reasoning`; without a default stub, tests that
    # don't explicitly patch it will pull Ollama over the wire through the
    # `invoke_with_llm_timeout` ThreadPoolExecutor. Tests that want the real
    # path either patch it themselves (via monkeypatch) or opt in through a
    # dedicated fixture.
    try:
        from api.routes import _chart_interpreter as _ci

        _ci.invoke_grounded_reasoning = lambda *a, **k: None  # type: ignore[assignment]
    except Exception:
        pass


_install_llm_stubs()


@pytest.fixture(autouse=True)
def _isolate_langgraph(request, monkeypatch):
    """Stub ``run_interpretation_graph`` per-test except when the graph is the SUT.

    Tests in ``test_interpretation_graph`` drive the graph directly and do
    their own patching, so they opt out of the stub.
    """
    module_obj = getattr(request.node, "module", None)
    module_name = getattr(module_obj, "__name__", "") if module_obj else ""
    if not module_name.endswith("test_interpretation_graph"):
        try:
            from src.agent import interpretation_graph as _ig

            monkeypatch.setattr(_ig, "run_interpretation_graph", lambda *a, **k: None)
        except Exception:
            pass
    yield


# =============================================================================
# PATH FIXTURES
# =============================================================================


@pytest.fixture
def project_root():
    """Return project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def data_dir(project_root):
    """Return data directory path."""
    return project_root / "data"


# =============================================================================
# DATA FIXTURES
# =============================================================================


@pytest.fixture
def sample_groundwater_data():
    """
    Generate sample groundwater data for testing.

    Creates 365 days of synthetic but realistic groundwater levels
    with seasonal patterns and random noise.
    """
    np.random.seed(42)

    dates = pd.date_range("2023-01-01", periods=365, freq="D")

    # Create realistic seasonal pattern
    day_of_year = np.arange(365)
    seasonal = 2 * np.sin(2 * np.pi * day_of_year / 365)  # ±2 ft seasonal swing
    trend = -0.002 * day_of_year  # Slight declining trend
    noise = np.random.normal(0, 0.3, 365)  # Random noise

    water_level = 5.0 + seasonal + trend + noise  # Base level ~5 ft

    return pd.DataFrame({"date": dates, "water_level": water_level})


@pytest.fixture
def minimal_data():
    """Minimal valid dataset for quick tests."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", periods=100, freq="D"),
            "water_level": np.random.normal(5, 1, 100),
        }
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def assert_no_nan(df: pd.DataFrame, message: str = ""):
    """Assert DataFrame has no NaN values."""
    nan_cols = df.columns[df.isnull().any()].tolist()
    assert len(nan_cols) == 0, f"NaN values in columns: {nan_cols}. {message}"


def assert_date_continuous(dates: pd.Series, max_gap_days: int = 1):
    """Assert dates are continuous with no gaps > max_gap_days."""
    gaps = dates.diff().dt.days
    large_gaps = gaps[gaps > max_gap_days]
    assert len(large_gaps) == 0, f"Found {len(large_gaps)} gaps > {max_gap_days} days"
