"""Publication-grade guardrails on the grounded-reasoning interpreter.

These tests pin the behaviors that keep chat answers credible for the paper:
the validator must flag fabricated site codes, fabricated years, and driver
hypotheses lacking a falsification test or valid evidence keys. The CI helper
must return a non-degenerate interval for clean inputs.
"""

from __future__ import annotations

import pytest

from api.routes._grounded_reasoning import (
    DriverHypothesis,
    GroundedFraming,
    GroundedInterpretation,
    ReasoningStep,
    SiteQuantBlock,
    validate_against_pack,
)
from api.routes._site_analysis import _ols_rate_ci95


def _pack() -> dict:
    return {
        "cohort_period_start": "2005-01-01",
        "cohort_period_end": "2023-12-31",
        "sites": [{"site_id": "A1", "name": "Lee L-100"}],
        "wells": [
            {
                "site_id": "A1",
                "name": "Lee L-100",
                "record_window": ["2005-01-01", "2023-12-31"],
                "rate_ci95": [-0.12, 0.04],
                "mk_p": 0.03,
                "sens_ft_yr": -0.05,
                "pelt_breaks": [{"date": "2017-06-01", "pre": 0.1, "post": -0.3}],
            }
        ],
        "well_summaries": [
            {"name": "Lee L-100", "site_id": "A1", "record_start": "2005", "record_end": "2023"}
        ],
        "comparison_features": {"cohort_mean_annual_change_ft_yr": -0.05},
    }


def _interp(**overrides) -> GroundedInterpretation:
    base = dict(
        intent="explain",
        framing=GroundedFraming(
            scope_type="well",
            focus_entities=["Lee L-100"],
            question_goal="explain",
            required_evidence_sections=["well_summaries"],
        ),
        reasoning_steps=[
            ReasoningStep(
                step_label="Frame",
                observation="Lee L-100 shows a falling trend at the cohort scale.",
                evidence_keys=["well_summaries", "comparison_features"],
                inference="The trend is consistent with the pack.",
                confidence="medium",
            )
        ],
        direct_answer=(
            "USGS well Lee L-100 falls at -0.05 ft/yr over 2005 to 2023; "
            "the record window is documented in the evidence pack."
        ),
        what_matters_most="Lee L-100 deviates from the cohort mean.",
        why_it_matters="Monitoring level matters for supply.",
        grounding_status="grounded",
    )
    base.update(overrides)
    return GroundedInterpretation(**base)


def test_fabricated_site_code_is_flagged():
    interp = _interp(
        direct_answer=("USGS well Lee L-100 and unrelated Lee L-9999 both fall over 2005 to 2023.")
    )
    flags = validate_against_pack(interp, _pack())
    assert any(f.startswith("grounded_reasoning_fabricated_site_code:") for f in flags)


def test_fabricated_year_is_flagged():
    interp = _interp(
        direct_answer=("USGS well Lee L-100 records 2005 to 2023 but 1974 is not in the pack.")
    )
    flags = validate_against_pack(interp, _pack())
    assert any(f.startswith("grounded_reasoning_fabricated_year:1974") for f in flags), flags


def test_driver_hypothesis_without_falsifier_is_flagged():
    interp = _interp(
        driver_hypotheses=[
            DriverHypothesis(
                claim="Pumping may be driving the decline",
                mechanism="pumping",
                evidence_keys=["comparison_features"],
                confidence="medium",
                falsification_test="",
            )
        ]
    )
    flags = validate_against_pack(interp, _pack())
    assert "grounded_reasoning_driver_missing_falsifier" in flags


def test_driver_hypothesis_bad_evidence_key_is_flagged():
    interp = _interp(
        driver_hypotheses=[
            DriverHypothesis(
                claim="Sea-level rise may be masking the trend",
                mechanism="sea_level",
                evidence_keys=["nonexistent_section"],
                confidence="low",
                falsification_test="A tide-gauge co-trend would disprove this.",
            )
        ]
    )
    flags = validate_against_pack(interp, _pack())
    assert any(f.startswith("grounded_reasoning_driver_bad_evidence_key:") for f in flags), flags


def test_per_site_quant_fabricated_site_is_flagged():
    interp = _interp(
        per_site_quant=[
            SiteQuantBlock(
                site="Lee L-100",
                site_id="A1",
                rate_ft_yr=-0.05,
            ),
            SiteQuantBlock(
                site="Lee L-9999",
                site_id="X9",
                rate_ft_yr=0.2,
            ),
        ]
    )
    flags = validate_against_pack(interp, _pack())
    assert any(f.startswith("grounded_reasoning_unknown_quant_site:") for f in flags), flags


def test_clean_interp_passes_new_guardrails():
    """Sanity: an interpretation that only uses pack-approved numbers stays clean."""
    interp = _interp(
        per_site_quant=[
            SiteQuantBlock(
                site="Lee L-100",
                site_id="A1",
                rate_ft_yr=-0.05,
                mk_pvalue=0.03,
                record_start="2005-01-01",
                record_end="2023-12-31",
            )
        ],
        driver_hypotheses=[
            DriverHypothesis(
                claim="Dry-season pumping aligns with the 2017 break",
                mechanism="pumping",
                evidence_keys=["comparison_features", "well_summaries"],
                confidence="medium",
                falsification_test=(
                    "A constant post-2017 pumping record with no water-level change "
                    "would disprove this."
                ),
            )
        ],
    )
    flags = validate_against_pack(interp, _pack())
    for flag in flags:
        assert not flag.startswith("grounded_reasoning_fabricated_"), flags
        assert not flag.startswith("grounded_reasoning_unknown_quant_site:"), flags
        assert flag != "grounded_reasoning_driver_missing_falsifier", flags


def test_ols_rate_ci_is_non_degenerate_for_clean_signal():
    values = [float(i) * 0.1 for i in range(24)]  # perfectly linear
    low, high = _ols_rate_ci95(values, step_years=1 / 12)
    assert low is not None and high is not None
    # Perfect linear fit -> zero residuals -> CI collapses near the slope (1.2 ft/yr).
    assert low == pytest.approx(1.2, abs=1e-6)
    assert high == pytest.approx(1.2, abs=1e-6)


def test_ols_rate_ci_widens_with_noise():
    import random

    random.seed(7)
    clean = [float(i) * 0.1 for i in range(48)]
    noisy = [v + random.gauss(0, 0.3) for v in clean]
    low_c, high_c = _ols_rate_ci95(clean, step_years=1 / 12)
    low_n, high_n = _ols_rate_ci95(noisy, step_years=1 / 12)
    clean_width = (high_c or 0) - (low_c or 0)
    noisy_width = (high_n or 0) - (low_n or 0)
    assert noisy_width > clean_width > -1e-9
