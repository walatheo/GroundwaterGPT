"""Demo-day smoke tests — guard the sponsor chat flows end-to-end.

Run with ``GROUNDWATERGPT_SKIP_AGENT_INIT=1`` so the deterministic path is
exercised (no LLM required). These are meant to be fast (sub-second) and
catch regressions that would break the demo headline moment.
"""

import os
import sys
from pathlib import Path

# Force the deterministic path — no LLM synthesis of any kind.
os.environ.setdefault("GROUNDWATERGPT_SKIP_AGENT_INIT", "1")
os.environ.setdefault("GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS", "1")
os.environ.setdefault("GROUNDWATERGPT_ENABLE_GROUNDED_REASONING", "0")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

client = TestClient(app)


def _post_chat(query: str) -> dict:
    response = client.post(
        "/api/chat",
        json={"message": query, "allow_llm_synthesis": False},
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestDemoSmoke:
    """Sponsor-demo headline moments — must stay green."""

    def test_two_well_comparison_emits_chart(self):
        """`compare G-3336 and G-5004` returns a comparison chart with ≥2 series."""
        data = _post_chat("compare G-3336 and G-5004")
        chart = data.get("chart") or {}
        assert chart.get("chart_type") == "comparison", data
        series = chart.get("series") or chart.get("data") or []
        assert len(series) >= 2, f"expected ≥2 series, got {len(series)}"

    def test_three_well_comparison_emits_chart(self):
        """Three-well overlay renders with ≥3 series."""
        data = _post_chat("compare G-3336, G-5004, and G-3665")
        chart = data.get("chart") or {}
        assert chart.get("chart_type") == "comparison", data
        series = chart.get("series") or chart.get("data") or []
        assert len(series) >= 3, f"expected ≥3 series, got {len(series)}"

    def test_estero_cohort_emits_chart(self):
        """`Estero trends` returns a cohort/network chart."""
        data = _post_chat("Estero trends")
        chart = data.get("chart")
        assert chart, data
        assert chart.get("chart_type") in {
            "comparison",
            "network",
            "cohort",
            "time_series",
        }, chart

    def test_conceptual_query_text_only(self):
        """Conceptual queries return text without forcing a chart."""
        data = _post_chat("which aquifer supplies Estero?")
        response_text = data.get("response") or data.get("report") or ""
        assert response_text, data
        assert len(response_text) > 40
