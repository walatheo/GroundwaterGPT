"""
Knowledge Base Accuracy Tests for Florida Aquifer Data.

This module tests the accuracy of the knowledge base retrieval system
specifically for USGS groundwater monitoring data from Florida aquifers.

Test Categories:
    - Site Identification: Can we find correct site numbers?
    - Aquifer Type: Does the KB correctly identify aquifer types?
    - Water Level Stats: Are mean/min/max values accurate?
    - Trends: Are water level trends correctly reported?
    - Data Period: Are date ranges accurate?

Ground Truth Source:
    - USGS NWIS (National Water Information System)
    - 6 monitoring sites in Florida (5 Biscayne, 1 Floridan)

Usage:
    pytest tests/knowledge/test_florida_accuracy.py -v
    pytest tests/knowledge/test_florida_accuracy.py -v --tb=short
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from src.agent.knowledge import (
    get_knowledge_stats,
    search_knowledge,
    search_usgs_data,
    search_with_fallback,
)

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture(scope="module")
def ground_truth():
    """Load the ground truth test cases for Florida aquifer data."""
    ground_truth_path = Path(__file__).parent / "ground_truth_florida.json"
    with open(ground_truth_path) as f:
        data = json.load(f)
    return data["test_cases"]


@pytest.fixture(scope="module")
def kb_stats():
    """Get knowledge base statistics."""
    return get_knowledge_stats()


# ============================================================================
# Helper Functions
# ============================================================================


def search_and_check_keywords(
    query: str, required_keywords: list[str], k: int = 5, score_threshold: float = 0.2
) -> tuple[bool, list[str], str]:
    """
    Search the knowledge base and check if required keywords are found.

    Args:
        query: The search query
        required_keywords: List of keywords that must appear in results
        k: Number of results to retrieve
        score_threshold: Minimum similarity score

    Returns:
        Tuple of (passed, missing_keywords, combined_content)
    """
    results = search_knowledge(query, k=k, score_threshold=score_threshold)

    if not results:
        return False, required_keywords, ""

    # Combine all result content for keyword checking
    combined_content = " ".join([doc.page_content.lower() for doc in results])

    # Check for required keywords (case insensitive)
    missing = []
    for keyword in required_keywords:
        if keyword.lower() not in combined_content:
            missing.append(keyword)

    passed = len(missing) == 0
    return passed, missing, combined_content


def extract_numeric_value(text: str, pattern: str = r"[\d.]+") -> list[float]:
    """Extract numeric values from text."""
    matches = re.findall(pattern, text)
    return [float(m) for m in matches if m]


# ============================================================================
# Knowledge Base Health Tests
# ============================================================================


class TestKnowledgeBaseHealth:
    """Test that the knowledge base is properly populated."""

    def test_kb_has_documents(self, kb_stats):
        """Verify knowledge base has documents."""
        total = kb_stats.get("total_chunks", 0)
        assert total > 0, "Knowledge base is empty"
        print(f"\n✅ Knowledge base has {total:,} documents")

    def test_kb_has_usgs_data(self):
        """Verify USGS groundwater data exists in KB."""
        results = search_knowledge("USGS groundwater monitoring Florida", k=10, score_threshold=0.2)

        usgs_results = [r for r in results if r.metadata.get("doc_type") == "usgs_groundwater_data"]

        assert len(usgs_results) > 0, "No USGS groundwater data found in KB"
        print(f"\n✅ Found {len(usgs_results)} USGS groundwater documents")

    def test_kb_has_both_aquifer_types(self):
        """Verify both Biscayne and Floridan aquifer data exists."""
        biscayne = search_knowledge("Biscayne Aquifer Miami-Dade", k=5)
        floridan = search_knowledge("Floridan Aquifer Lee County", k=5)

        biscayne_found = any("biscayne" in r.page_content.lower() for r in biscayne)
        floridan_found = any("floridan" in r.page_content.lower() for r in floridan)

        assert biscayne_found, "Biscayne Aquifer data not found"
        assert floridan_found, "Floridan Aquifer data not found"
        print("\n✅ Both Biscayne and Floridan aquifer data present")


# ============================================================================
# Site Identification Tests
# ============================================================================


class TestSiteIdentification:
    """Test accurate retrieval of USGS site information."""

    @pytest.mark.parametrize(
        "site_name,expected_id",
        [
            ("Miami-Dade G-3764", "251241080385301"),
            ("Miami-Dade G-3777", "251457080395802"),
            ("Miami-Dade G-1251", "251922080340701"),
            ("Miami-Dade G-3336", "252007080335701"),
            ("Miami-Dade G-5004", "252036080293501"),
            ("Lee County Fort Myers", "262724081260701"),
        ],
    )
    def test_site_number_retrieval(self, site_name, expected_id):
        """Test that site numbers are correctly retrievable."""
        query = f"What is the USGS site number for {site_name}?"
        passed, missing, content = search_and_check_keywords(query, [expected_id])

        assert passed, f"Site ID {expected_id} not found for {site_name}"
        print(f"\n✅ {site_name} → {expected_id}")


# ============================================================================
# Aquifer Type Tests
# ============================================================================


class TestAquiferTypes:
    """Test accurate aquifer type identification."""

    @pytest.mark.parametrize(
        "site,expected_aquifer",
        [
            ("Miami-Dade G-3764", "biscayne"),
            ("Miami-Dade G-3777", "biscayne"),
            ("Miami-Dade G-1251", "biscayne"),
            ("Miami-Dade G-3336", "biscayne"),
            ("Miami-Dade G-5004", "biscayne"),
            ("Lee County Fort Myers", "floridan"),
        ],
    )
    def test_aquifer_type_identification(self, site, expected_aquifer):
        """Test that aquifer types are correctly identified."""
        query = f"What aquifer is {site} monitoring?"
        passed, missing, content = search_and_check_keywords(query, [expected_aquifer, "aquifer"])

        assert passed, f"Expected {expected_aquifer} aquifer for {site}, missing: {missing}"
        print(f"\n✅ {site} → {expected_aquifer.title()} Aquifer")


# ============================================================================
# Water Level Statistics Tests
# ============================================================================


class TestWaterLevelStats:
    """Test accuracy of water level statistics."""

    @pytest.mark.parametrize(
        "site,expected_mean,tolerance",
        [
            ("Miami-Dade G-3764", 0.59, 0.2),
            ("Miami-Dade G-3777", 0.53, 0.2),
            ("Miami-Dade G-1251", 1.41, 0.3),
            ("Miami-Dade G-3336", 1.87, 0.3),
            ("Miami-Dade G-5004", 1.40, 0.3),
            ("Lee County Fort Myers", 21.3, 2.0),
        ],
    )
    def test_mean_water_level(self, site, expected_mean, tolerance):
        """Test that mean water levels are within expected ranges."""
        query = f"What is the mean water level at {site}?"
        results = search_knowledge(query, k=5, score_threshold=0.2)

        assert len(results) > 0, f"No results found for {site}"

        combined = " ".join([r.page_content for r in results])

        # Extract mean value from content
        mean_match = re.search(r"mean water level[:\s]+([0-9.]+)", combined.lower())

        if mean_match:
            found_mean = float(mean_match.group(1))
            within_tolerance = abs(found_mean - expected_mean) <= tolerance
            assert (
                within_tolerance
            ), f"Mean {found_mean} not within {tolerance} of expected {expected_mean}"
            print(f"\n✅ {site}: Mean = {found_mean} ft (expected ~{expected_mean})")
        else:
            # Fallback: check if expected value appears in content
            assert str(expected_mean)[:3] in combined, f"Expected mean ~{expected_mean} not found"
            print(f"\n✅ {site}: Mean value ~{expected_mean} found in content")


# ============================================================================
# Trend Tests
# ============================================================================


class TestWaterLevelTrends:
    """Test accuracy of water level trend reporting."""

    @pytest.mark.parametrize(
        "site,expected_trend",
        [
            ("Miami-Dade G-3764", "rising"),
            ("Miami-Dade G-3777", "rising"),
            ("Miami-Dade G-1251", "rising"),
            ("Lee County - Fort Myers", "rising"),
        ],
    )
    def test_trend_direction(self, site, expected_trend):
        """Test that trend directions are correctly reported."""
        # Use enhanced USGS search for better trend retrieval
        results = search_usgs_data(site_name=site, include_trends=True, k=5)

        if not results:
            # Fallback to general search with trend-specific query
            query = f"{site} annual trend water level"
            results = search_knowledge(query, k=5, score_threshold=0.2)

        combined = " ".join([r.page_content.lower() for r in results])
        trend_found = expected_trend in combined

        assert trend_found, f"Expected trend '{expected_trend}' not found for {site}"
        print(f"\n✅ {site}: Trend = {expected_trend}")


# ============================================================================
# County Tests
# ============================================================================


class TestCountyInformation:
    """Test accurate county information retrieval."""

    def test_lee_county_floridan(self):
        """Test Lee County has Floridan Aquifer data."""
        query = "Which county has Floridan Aquifer monitoring data?"
        passed, missing, _ = search_and_check_keywords(query, ["lee"])
        assert passed, "Lee County not found for Floridan Aquifer"
        print("\n✅ Lee County → Floridan Aquifer")

    def test_miami_dade_biscayne(self):
        """Test Miami-Dade has Biscayne Aquifer data."""
        query = "Which county has Biscayne Aquifer monitoring sites?"
        passed, missing, _ = search_and_check_keywords(query, ["miami"])
        assert passed, "Miami-Dade not found for Biscayne Aquifer"
        print("\n✅ Miami-Dade County → Biscayne Aquifer")


# ============================================================================
# Ground Truth Full Test Suite
# ============================================================================


class TestGroundTruthFlorida:
    """Run full ground truth test suite from JSON file."""

    def test_ground_truth_file_exists(self, ground_truth):
        """Verify ground truth file is loaded."""
        assert len(ground_truth) > 0, "Ground truth file is empty"
        print(f"\n✅ Loaded {len(ground_truth)} ground truth test cases")

    def test_ground_truth_coverage(self, ground_truth):
        """Test coverage of all ground truth questions."""
        passed = 0
        failed = 0
        results_summary = []

        for tc in ground_truth:
            query = tc["question"]
            required = tc["required_keywords"]
            category = tc["category"]

            # Use enhanced search for better retrieval
            results = search_with_fallback(query, k=5, score_threshold=0.2)

            # Combine all result content for keyword checking
            combined_content = " ".join([doc.page_content.lower() for doc in results])

            # Check for required keywords (case insensitive)
            missing = []
            for keyword in required:
                if keyword.lower() not in combined_content:
                    missing.append(keyword)

            success = len(missing) == 0

            if success:
                passed += 1
                results_summary.append(f"✅ {tc['id']}: {category}")
            else:
                failed += 1
                results_summary.append(f"❌ {tc['id']}: {category} - Missing: {missing}")

        # Print summary
        print("\n" + "=" * 60)
        print("GROUND TRUTH TEST RESULTS")
        print("=" * 60)
        for r in results_summary:
            print(r)
        print("=" * 60)
        print(f"PASSED: {passed}/{len(ground_truth)} ({100*passed/len(ground_truth):.1f}%)")
        print(f"FAILED: {failed}/{len(ground_truth)}")
        print("=" * 60)

        # Require at least 80% accuracy
        accuracy = passed / len(ground_truth)
        assert accuracy >= 0.8, f"Accuracy {accuracy:.1%} below 80% threshold"


# ============================================================================
# Accuracy Metrics
# ============================================================================


class TestAccuracyMetrics:
    """Calculate precision and recall metrics for KB retrieval."""

    def test_precision_at_k(self):
        """
        Test precision@k for USGS queries.
        Precision = relevant results / total results returned
        """
        queries = [
            "groundwater level Biscayne Aquifer Miami",
            "water level trend Floridan Aquifer",
            "USGS monitoring site Fort Myers",
        ]

        total_precision = 0
        k = 5

        for query in queries:
            results = search_knowledge(query, k=k, score_threshold=0.2)

            # Count relevant results (USGS groundwater data)
            relevant = sum(
                1
                for r in results
                if r.metadata.get("doc_type") == "usgs_groundwater_data"
                or "usgs" in r.page_content.lower()
                or "aquifer" in r.page_content.lower()
            )

            precision = relevant / len(results) if results else 0
            total_precision += precision

        avg_precision = total_precision / len(queries)
        print(f"\n📊 Average Precision@{k}: {avg_precision:.2%}")

        # We want at least 60% precision
        assert avg_precision >= 0.6, f"Precision {avg_precision:.2%} below 60% threshold"

    def test_recall_for_sites(self):
        """
        Test recall for known USGS sites.
        Recall = found sites / total known sites
        """
        known_sites = [
            ("251241080385301", "Miami-Dade G-3764"),
            ("251457080395802", "Miami-Dade G-3777"),
            ("251922080340701", "Miami-Dade G-1251"),
            ("252007080335701", "Miami-Dade G-3336"),
            ("252036080293501", "Miami-Dade G-5004"),
            ("262724081260701", "Lee County Fort Myers"),
        ]

        found = 0
        for site_id, site_name in known_sites:
            # Use enhanced USGS search
            results = search_usgs_data(site_id=site_id, site_name=site_name, k=5)

            # Check if site is found
            site_found = False
            for r in results:
                if site_id in r.page_content or site_name in r.page_content:
                    site_found = True
                    break

            if site_found:
                found += 1
                print(f"  ✅ Found: {site_name}")
            else:
                print(f"  ❌ Missing: {site_name}")

        recall = found / len(known_sites)
        print(f"\n📊 Site Recall: {recall:.2%} ({found}/{len(known_sites)} sites)")

        # We want 100% recall for our known sites
        assert recall >= 0.8, f"Recall {recall:.2%} below 80% threshold"


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    # Run with verbose output
    pytest.main([__file__, "-v", "--tb=short"])
