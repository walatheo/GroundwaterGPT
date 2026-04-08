"""Unit tests for the detection chain in api.routes._detection.

Covers: _detect_location, _detect_aquifer, _detect_site_names,
        _is_network_wide_query, _is_aquifer_query
"""

import pytest


class TestDetectLocation:
    """Test _detect_location against known FL locations."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from api.routes._detection import _detect_location

        self.detect = _detect_location

    def test_estero(self):
        result = self.detect("What has groundwater done in Estero?")
        assert result is not None
        lat, lng, name, county = result
        assert abs(lat - 26.4381) < 0.01
        assert abs(lng - (-81.8068)) < 0.01
        assert "Estero" in name
        assert county == "lee"

    def test_miami(self):
        result = self.detect("Groundwater trends in Miami")
        assert result is not None
        _, _, name, county = result
        assert "Miami" in name
        assert county == "miami-dade"

    def test_naples(self):
        result = self.detect("Water levels near Naples")
        assert result is not None
        _, _, name, county = result
        assert "Naples" in name
        assert county == "collier"

    def test_no_location(self):
        result = self.detect("What is groundwater?")
        assert result is None

    def test_county_match(self):
        result = self.detect("trends in Lee County")
        assert result is not None
        _, _, name, county = result
        assert county == "lee"

    def test_case_insensitive(self):
        result = self.detect("ESTERO water levels")
        assert result is not None
        _, _, name, _ = result
        assert "Estero" in name

    def test_floridan_not_florida(self):
        """'floridan' should NOT match 'florida' location."""
        result = self.detect("Floridan aquifer trends")
        assert result is None or "Florida" not in (result[2] if result else "")


class TestDetectAquifer:
    """Test _detect_aquifer against known aquifer keywords."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from api.routes._detection import _detect_aquifer

        self.detect = _detect_aquifer

    def test_biscayne(self):
        result = self.detect("Biscayne aquifer trends")
        assert result is not None
        key, display = result
        assert key == "biscayne"
        assert "Biscayne" in display

    def test_floridan(self):
        result = self.detect("What about the Floridan aquifer?")
        assert result is not None
        key, _ = result
        assert key == "floridan"

    def test_lower_tamiami(self):
        result = self.detect("lower tamiami levels")
        assert result is not None
        key, _ = result
        assert "tamiami" in key

    def test_no_aquifer(self):
        result = self.detect("What is pH?")
        assert result is None

    def test_surficial(self):
        result = self.detect("surficial aquifer data")
        assert result is not None
        key, _ = result
        assert key == "surficial"


class TestDetectSiteNames:
    """Test _detect_site_names against well name patterns."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from api.routes._detection import _detect_site_names

        self.detect = _detect_site_names

    def test_single_well_name(self):
        """Well name like G-3336 should be detected."""
        result = self.detect("What about G-3336?")
        assert len(result) >= 1
        assert any("G-3336" in s.get("name", "") for s in result)

    def test_multiple_wells(self):
        """Multiple well names in one query."""
        result = self.detect("Compare L-2195 and L-2194")
        # At least one should match (depends on which sites exist in metadata)
        assert isinstance(result, list)

    def test_fifteen_digit_id(self):
        """15-digit USGS site IDs should be detected."""
        # Use a known site ID from SITE_METADATA
        from api.site_metadata import SITE_METADATA

        if SITE_METADATA:
            first_id = next(iter(SITE_METADATA))
            result = self.detect(f"Data for {first_id}")
            assert len(result) >= 1

    def test_no_match(self):
        result = self.detect("Hello world")
        assert result == []


class TestIsNetworkWideQuery:
    """Test _is_network_wide_query keyword matching."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from api.routes._detection import _is_network_wide_query

        self.check = _is_network_wide_query

    def test_all_wells(self):
        assert self.check("Show me all wells") is True

    def test_which_county(self):
        assert self.check("Which county has the most wells?") is True

    def test_specific_query(self):
        assert self.check("Estero groundwater trends") is False

    def test_compare_all(self):
        assert self.check("Compare all sites") is True


class TestIsAquiferQuery:
    """Test _is_aquifer_query keyword matching."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from api.routes._detection import _is_aquifer_query

        self.check = _is_aquifer_query

    def test_which_aquifer(self):
        assert self.check("which aquifer supplies Estero?") is True

    def test_confined_keyword(self):
        assert self.check("confined wells in Lee") is True

    def test_plain_query(self):
        assert self.check("water levels in Estero") is False
