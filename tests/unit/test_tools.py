"""Tests for agent tools — data querying, site listing, chart generation.

Validates all ``@tool`` functions in ``src/agent/tools.py`` can be invoked
and return reasonable results when data files are present on disk.
"""

import json
import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import src.agent.tools as tools_module  # noqa: E402
from src.agent.tools import (  # noqa: E402
    GROUNDWATER_TOOLS,
    _load_site_csv,
    _load_site_metadata,
    analyze_seasonal_patterns,
    create_research_experiment_plan,
    detect_anomalies,
    draft_research_paper,
    generate_comparison_chart,
    generate_time_series_plot,
    get_data_quality_report,
    get_water_level_prediction,
    list_available_sites,
    list_research_experiment_plans,
    log_experiment_run,
    query_groundwater_data,
    query_site_data,
)

DATA_DIR = Path(__file__).parent.parent.parent / "data"


def _has_consolidated_data() -> bool:
    """Check if groundwater.csv exists."""
    return (DATA_DIR / "groundwater.csv").exists()


def _first_site_id() -> str:
    """Return the first site ID that has a CSV on disk."""
    meta = _load_site_metadata()
    for sid in meta:
        if (DATA_DIR / f"usgs_{sid}.csv").exists():
            return sid
    pytest.skip("No per-site CSV files on disk")


# ===================================================================
# Tool Registry
# ===================================================================


class TestToolRegistry:
    """Verify the GROUNDWATER_TOOLS list is complete."""

    def test_tool_count(self):
        """All registered tools should be present."""
        assert len(GROUNDWATER_TOOLS) == 13

    def test_all_tools_have_names(self):
        """Each tool has a non-empty name attribute."""
        for t in GROUNDWATER_TOOLS:
            assert hasattr(t, "name") and t.name

    def test_all_tools_have_descriptions(self):
        """Each tool has a non-empty description."""
        for t in GROUNDWATER_TOOLS:
            assert hasattr(t, "description") and t.description

    def test_expected_tool_names(self):
        """Check the expected tool names are present."""
        names = {t.name for t in GROUNDWATER_TOOLS}
        expected = {
            "query_groundwater_data",
            "get_water_level_prediction",
            "analyze_seasonal_patterns",
            "detect_anomalies",
            "get_data_quality_report",
            "generate_time_series_plot",
            "generate_comparison_chart",
            "list_available_sites",
            "query_site_data",
            "create_research_experiment_plan",
            "list_research_experiment_plans",
            "log_experiment_run",
            "draft_research_paper",
        }
        assert names == expected


# ===================================================================
# Site Metadata
# ===================================================================


class TestSiteMetadata:
    """Test the _load_site_metadata helper."""

    def test_returns_dict(self):
        """Metadata loader returns a dictionary."""
        meta = _load_site_metadata()
        assert isinstance(meta, dict)

    def test_has_sites(self):
        """At least one site is present in metadata."""
        meta = _load_site_metadata()
        assert len(meta) > 0

    def test_site_fields(self):
        """Each site entry has name, aquifer, county."""
        meta = _load_site_metadata()
        for sid, m in list(meta.items())[:3]:
            assert "name" in m
            assert "aquifer" in m
            assert "county" in m


# ===================================================================
# list_available_sites
# ===================================================================


class TestListAvailableSites:
    """Test the list_available_sites tool."""

    def test_lists_all_sites(self):
        """Unfiltered call lists all sites."""
        result = list_available_sites.invoke({})
        assert "Available Sites" in result

    def test_filter_by_county(self):
        """County filter returns only matching sites."""
        result = list_available_sites.invoke({"county": "Lee"})
        assert "Lee" in result

    def test_filter_by_aquifer(self):
        """Aquifer filter returns only matching sites."""
        result = list_available_sites.invoke({"aquifer": "Biscayne"})
        assert "Biscayne" in result

    def test_no_match_returns_message(self):
        """Non-existent county returns a helpful message."""
        result = list_available_sites.invoke({"county": "Nonexistent"})
        assert "No sites match" in result


# ===================================================================
# query_site_data
# ===================================================================


class TestQuerySiteData:
    """Test the query_site_data tool."""

    def test_summary(self):
        """Summary stat_type returns key stats."""
        sid = _first_site_id()
        result = query_site_data.invoke({"site_id": sid, "stat_type": "summary"})
        assert "Mean" in result or "mean" in result.lower()

    def test_monthly(self):
        """Monthly stat_type returns month-level data."""
        sid = _first_site_id()
        result = query_site_data.invoke({"site_id": sid, "stat_type": "monthly"})
        assert "Monthly" in result

    def test_yearly(self):
        """Yearly stat_type returns year-level data."""
        sid = _first_site_id()
        result = query_site_data.invoke({"site_id": sid, "stat_type": "yearly"})
        assert "Yearly" in result

    def test_raw(self):
        """Raw stat_type returns recent records."""
        sid = _first_site_id()
        result = query_site_data.invoke({"site_id": sid, "stat_type": "raw"})
        assert "Recent" in result

    def test_unknown_site(self):
        """Unknown site returns error message (not exception)."""
        result = query_site_data.invoke(
            {"site_id": "000000000000000", "stat_type": "summary"}
        )
        assert "No data" in result or "not found" in result.lower()


# ===================================================================
# Consolidated data tools
# ===================================================================


@pytest.mark.skipif(not _has_consolidated_data(), reason="groundwater.csv not on disk")
class TestConsolidatedTools:
    """Test tools that operate on groundwater.csv."""

    def test_query_summary(self):
        """query_groundwater_data summary returns stats."""
        result = query_groundwater_data.invoke({"stat_type": "summary"})
        assert "Water Level" in result or "water_level" in result.lower()

    def test_query_monthly(self):
        """query_groundwater_data monthly returns month rows."""
        result = query_groundwater_data.invoke({"stat_type": "monthly"})
        assert "Monthly" in result

    def test_seasonal_patterns(self):
        """analyze_seasonal_patterns returns season data."""
        result = analyze_seasonal_patterns.invoke({})
        assert "Wet" in result and "Dry" in result

    def test_anomalies(self):
        """detect_anomalies returns a report."""
        result = detect_anomalies.invoke({"threshold": 2.0})
        assert "Anomaly" in result

    def test_data_quality(self):
        """get_data_quality_report returns a report."""
        result = get_data_quality_report.invoke({})
        assert "Quality" in result or "quality" in result.lower()

    def test_prediction(self):
        """get_water_level_prediction returns a forecast."""
        result = get_water_level_prediction.invoke({"days_ahead": 3})
        assert "Prediction" in result or "Forecast" in result


# ===================================================================
# Chart tools
# ===================================================================


class TestChartTools:
    """Test the visualization / chart tools."""

    def test_time_series_returns_json(self):
        """generate_time_series_plot returns valid JSON with chart type."""
        sid = _first_site_id()
        raw = generate_time_series_plot.invoke({"site_id": sid})
        data = json.loads(raw)
        assert data["type"] == "chart"
        assert data["chart_type"] == "time_series"
        assert len(data["data"]) > 0

    def test_time_series_unknown_site(self):
        """Unknown site returns JSON with error key."""
        raw = generate_time_series_plot.invoke({"site_id": "000000000000000"})
        data = json.loads(raw)
        assert "error" in data

    def test_comparison_chart(self):
        """generate_comparison_chart with valid sites returns data."""
        meta = _load_site_metadata()
        valid = [sid for sid in meta if (DATA_DIR / f"usgs_{sid}.csv").exists()][:2]
        if len(valid) < 2:
            pytest.skip("Need at least 2 site CSVs")
        raw = generate_comparison_chart.invoke({"site_ids": valid})
        data = json.loads(raw)
        assert data["type"] == "chart"
        assert data["chart_type"] == "comparison"

    def test_comparison_max_five(self):
        """Comparison chart caps at 5 sites."""
        meta = _load_site_metadata()
        many = list(meta.keys())[:8]
        raw = generate_comparison_chart.invoke({"site_ids": many})
        data = json.loads(raw)
        assert len(data.get("series", [])) <= 5


# ===================================================================
# _load_site_csv helper
# ===================================================================


class TestLoadSiteCsv:
    """Test the _load_site_csv helper."""

    def test_loads_valid_site(self):
        """A known site CSV loads with date and water_level_ft columns."""
        sid = _first_site_id()
        df = _load_site_csv(sid)
        assert "date" in df.columns
        assert "water_level_ft" in df.columns
        assert len(df) > 0

    def test_raises_for_missing_site(self):
        """Missing CSV raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            _load_site_csv("000000000000000")


# ===================================================================
# Research workflow tools
# ===================================================================


class TestResearchWorkflowTools:
    """Test experiment planning + paper drafting tools."""

    def _redirect_research_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools_module, "OUTPUTS_DIR", tmp_path / "outputs")
        monkeypatch.setattr(
            tools_module, "RESEARCH_DIR", tmp_path / "outputs" / "research"
        )
        monkeypatch.setattr(
            tools_module,
            "EXPERIMENTS_DIR",
            tmp_path / "outputs" / "research" / "experiments",
        )
        monkeypatch.setattr(
            tools_module,
            "MANUSCRIPTS_DIR",
            tmp_path / "outputs" / "research" / "manuscripts",
        )

    def test_create_list_log_and_draft(self, tmp_path, monkeypatch):
        self._redirect_research_dirs(tmp_path, monkeypatch)

        created = create_research_experiment_plan.invoke(
            {
                "title": "Agentic Groundwater Study",
                "research_question": "Can agentic workflows improve reproducibility?",
                "hypothesis": "Structured run logging improves reproducibility.",
                "methodology": "Compare baseline vs agentic workflows.",
                "datasets": ["USGS Florida Sites"],
                "metrics": ["f1", "reproducibility_score"],
                "baselines": ["manual pipeline"],
            }
        )
        assert "Experiment Plan Created" in created

        listed = list_research_experiment_plans.invoke({})
        assert "Experiment Plans" in listed
        plan_id = listed.split("`")[1]

        logged = log_experiment_run.invoke(
            {
                "plan_id": plan_id,
                "run_name": "baseline",
                "config_json": json.dumps({"model": "ridge", "seed": 42}),
                "metrics_json": json.dumps({"f1": 0.81, "reproducibility_score": 0.74}),
                "findings": "Baseline is stable.",
            }
        )
        assert "Run Logged" in logged

        drafted = draft_research_paper.invoke(
            {"plan_id": plan_id, "target_venue": "NeurIPS"}
        )
        assert "Draft saved to" in drafted
        assert "## Abstract (Draft)" in drafted
