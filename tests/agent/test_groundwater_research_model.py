"""Tests for Groundwater Research Model.

Tests domain-specific groundwater knowledge and validation.
"""

import pytest
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from src.agent.groundwater_research_model import (
    GroundwaterResearchModel,
    DomainQueryExpander,
    AquiferType,
    AquiferProperties,
    get_groundwater_model,
    expand_groundwater_query,
)


class TestAquiferProperties:
    """Test aquifer property definitions."""
    
    def test_biscayne_aquifer_properties(self):
        """Test Biscayne Aquifer properties."""
        model = get_groundwater_model()
        biscayne = model.get_aquifer_info("biscayne")
        
        assert biscayne is not None
        assert biscayne.aquifer_type == AquiferType.BISCAYNE
        assert biscayne.typical_depth_ft == (10, 50)
        assert biscayne.elevation_range_ft == (-100, 20)
        assert biscayne.high_tide_sensitivity == True
    
    def test_floridan_aquifer_properties(self):
        """Test Floridan Aquifer properties."""
        model = get_groundwater_model()
        floridan = model.get_aquifer_info("floridan")
        
        assert floridan is not None
        assert floridan.aquifer_type == AquiferType.FLORIDAN
        assert floridan.typical_depth_ft == (50, 200)
        assert floridan.elevation_range_ft == (-500, -200)
        assert floridan.high_tide_sensitivity == False
    
    def test_surficial_aquifer_properties(self):
        """Test Surficial Aquifer properties."""
        model = get_groundwater_model()
        surficial = model.get_aquifer_info("surficial")
        
        assert surficial is not None
        assert surficial.aquifer_type == AquiferType.SURFICIAL
        assert surficial.typical_depth_ft == (0, 20)
        assert surficial.elevation_range_ft == (-5, 15)


class TestWaterLevelValidation:
    """Test water level elevation validation."""
    
    def test_valid_biscayne_elevation(self):
        """Test validation of valid Biscayne elevations."""
        model = get_groundwater_model()
        biscayne = model.get_aquifer_info("biscayne")
        
        # Test valid elevations
        is_valid, reason = biscayne.validate_water_level(5.0)  # Typical high
        assert is_valid
        
        is_valid, reason = biscayne.validate_water_level(-20.0)  # Typical low
        assert is_valid
    
    def test_invalid_biscayne_elevation_high(self):
        """Test detection of unrealistically high elevation."""
        model = get_groundwater_model()
        biscayne = model.get_aquifer_info("biscayne")
        
        is_valid, reason = biscayne.validate_water_level(100.0)  # Way too high
        assert not is_valid
        assert "above range" in reason
    
    def test_invalid_biscayne_elevation_low(self):
        """Test detection of unrealistically low elevation."""
        model = get_groundwater_model()
        biscayne = model.get_aquifer_info("biscayne")
        
        is_valid, reason = biscayne.validate_water_level(-200.0)  # Way too low
        assert not is_valid
        assert "below range" in reason


class TestSeasonalAmplitude:
    """Test seasonal amplitude calculations."""
    
    def test_surficial_high_amplitude(self):
        """Surficial aquifer should have high seasonal amplitude."""
        model = get_groundwater_model()
        surficial = model.get_aquifer_info("surficial")
        
        amplitude = surficial.expected_seasonal_amplitude()
        assert amplitude == 3.0  # High variation
    
    def test_biscayne_moderate_amplitude(self):
        """Biscayne aquifer should have moderate amplitude."""
        model = get_groundwater_model()
        biscayne = model.get_aquifer_info("biscayne")
        
        amplitude = biscayne.expected_seasonal_amplitude()
        assert amplitude == 1.5
    
    def test_floridan_low_amplitude(self):
        """Floridan aquifer should have low amplitude."""
        model = get_groundwater_model()
        floridan = model.get_aquifer_info("floridan")
        
        amplitude = floridan.expected_seasonal_amplitude()
        assert amplitude == 0.5


class TestDomainQueryExpander:
    """Test domain-aware query expansion."""
    
    def test_expand_water_level_query(self):
        """Test expansion of water level query."""
        query = "What is the water level in Florida?"
        expanded = expand_groundwater_query(query)
        
        assert len(expanded) > 1
        assert expanded[0] == query  # Original query first
        # Check for synonyms
        expanded_text = " ".join(expanded)
        assert "elevation" in expanded_text or "aquifer" in expanded_text
    
    def test_expand_biscayne_query(self):
        """Test expansion of Biscayne-specific query."""
        query = "Biscayne Aquifer trends"
        expanded = expand_groundwater_query(query)
        
        assert len(expanded) > 1
        # May include regional terms
        all_text = " ".join(expanded)
        assert "biscayne" in all_text.lower()
    
    def test_synonym_replacement(self):
        """Test that synonyms are used in expansion."""
        expander = DomainQueryExpander()
        
        # Direct synonym replacement
        original = "water level trends"
        expanded = expander.expand_query(original)
        
        # Should include variations
        assert len(expanded) > 1
        expanded_text = " ".join(expanded)
        assert any(
            term in expanded_text.lower()
            for term in ["elevation", "head", "piezometric"]
        )


class TestDataFrameValidation:
    """Test validation of water level DataFrames."""
    
    def test_valid_dataframe(self):
        """Test validation of valid water level data."""
        model = get_groundwater_model()
        
        # Create valid data
        dates = pd.date_range("2023-01-01", periods=100, freq="D")
        df = pd.DataFrame({
            "date": dates,
            "elevation_ft": np.random.normal(5.0, 1.0, 100),
        })
        
        result = model.validate_water_level_data(df, AquiferType.BISCAYNE, "USG_12345")
        
        assert result["valid"] == True
        assert result["site_id"] == "USG_12345"
        assert result["records"] == 100
    
    def test_empty_dataframe(self):
        """Test validation of empty DataFrame."""
        model = get_groundwater_model()
        
        df = pd.DataFrame()
        result = model.validate_water_level_data(df, AquiferType.BISCAYNE, "USG_12345")
        
        assert result["valid"] == False
        assert "Empty" in result["issues"][0]
    
    def test_missing_columns(self):
        """Test detection of missing required columns."""
        model = get_groundwater_model()
        
        df = pd.DataFrame({"wrong_column": [1, 2, 3]})
        result = model.validate_water_level_data(df, AquiferType.BISCAYNE, "USG_12345")
        
        assert result["valid"] == False
        assert any("elevation" in issue for issue in result["issues"])


class TestSeasonalPatternDetection:
    """Test seasonal pattern detection."""
    
    def test_detect_clear_seasonal_pattern(self):
        """Test detection of clear seasonal pattern."""
        model = get_groundwater_model()
        
        # Create synthetic data with seasonal pattern
        dates = pd.date_range("2021-01-01", periods=730, freq="D")  # 2 years
        months = dates.month
        
        # High in summer, low in winter
        elevation = 5.0 + 2.0 * np.sin(2 * np.pi * months / 12)
        elevation += np.random.normal(0, 0.2, len(elevation))  # Add noise
        
        df = pd.DataFrame({
            "date": dates,
            "elevation_ft": elevation,
        })
        
        pattern = model.detect_seasonal_pattern(df, AquiferType.BISCAYNE, "USG_12345")
        
        assert pattern is not None
        assert pattern.site_id == "USG_12345"
        assert pattern.peak_month != pattern.trough_month
        assert pattern.annual_amplitude > 0
    
    def test_insufficient_data_for_pattern(self):
        """Test that short time series don't detect pattern."""
        model = get_groundwater_model()
        
        # Only 6 months of data
        dates = pd.date_range("2023-01-01", periods=180, freq="D")
        df = pd.DataFrame({
            "date": dates,
            "elevation_ft": np.random.normal(5.0, 1.0, 180),
        })
        
        pattern = model.detect_seasonal_pattern(
            df, AquiferType.BISCAYNE, "USG_12345", min_years=2
        )
        
        assert pattern is None


class TestAnomalyDetection:
    """Test anomaly detection in water levels."""
    
    def test_detect_spike_anomaly(self):
        """Test detection of spike anomaly."""
        model = get_groundwater_model()
        
        # Normal data with one spike
        values = [5.0] * 100
        values[50] = 15.0  # Spike
        
        dates = pd.date_range("2023-01-01", periods=100, freq="D")
        df = pd.DataFrame({
            "date": dates,
            "elevation_ft": values,
        })
        
        anomalies = model.detect_anomalies(df, AquiferType.BISCAYNE, "USG_12345")
        
        assert len(anomalies) > 0
        # Check that spike was detected
        spike_detected = any(a.anomaly_type == "spike" for a in anomalies)
        assert spike_detected
    
    def test_detect_drop_anomaly(self):
        """Test detection of drop anomaly."""
        model = get_groundwater_model()
        
        # Normal data with one drop
        values = [5.0] * 100
        values[50] = -5.0  # Drop
        
        dates = pd.date_range("2023-01-01", periods=100, freq="D")
        df = pd.DataFrame({
            "date": dates,
            "elevation_ft": values,
        })
        
        anomalies = model.detect_anomalies(df, AquiferType.BISCAYNE, "USG_12345")
        
        assert len(anomalies) > 0
        # Check that drop was detected
        drop_detected = any(a.anomaly_type == "drop" for a in anomalies)
        assert drop_detected
    
    def test_no_anomalies_in_normal_data(self):
        """Test that normal data has no anomalies."""
        model = get_groundwater_model()
        
        # Normal data
        dates = pd.date_range("2023-01-01", periods=100, freq="D")
        df = pd.DataFrame({
            "date": dates,
            "elevation_ft": np.random.normal(5.0, 0.1, 100),
        })
        
        anomalies = model.detect_anomalies(df, AquiferType.BISCAYNE, "USG_12345")
        
        assert len(anomalies) == 0


class TestMultiSiteCorrelation:
    """Test multi-site correlation analysis."""
    
    def test_synchronous_sites_correlation(self):
        """Test that synchronous sites show high correlation."""
        model = get_groundwater_model()
        
        # Create two sites with correlated data
        dates = pd.date_range("2023-01-01", periods=100, freq="D")
        base_signal = np.sin(2 * np.pi * np.arange(100) / 50)
        
        site1_data = pd.DataFrame({
            "date": dates,
            "elevation_ft": 5.0 + base_signal + np.random.normal(0, 0.1, 100),
        })
        
        site2_data = pd.DataFrame({
            "date": dates,
            "elevation_ft": 5.0 + base_signal + np.random.normal(0, 0.1, 100),
        })
        
        sites_data = {
            "site1": site1_data,
            "site2": site2_data,
        }
        
        correlations = model.analyze_multi_site_correlation(sites_data)
        
        assert "site1" in correlations
        assert "site2" in correlations
        # Correlation should be high (>0.7)
        site_corr = correlations["site1"]["site2"]
        assert site_corr > 0.7
    
    def test_independent_sites_low_correlation(self):
        """Test that independent sites show low correlation."""
        model = get_groundwater_model()
        
        # Create independent data
        dates = pd.date_range("2023-01-01", periods=100, freq="D")
        
        site1_data = pd.DataFrame({
            "date": dates,
            "elevation_ft": np.random.normal(5.0, 1.0, 100),
        })
        
        site2_data = pd.DataFrame({
            "date": dates,
            "elevation_ft": np.random.normal(10.0, 1.0, 100),
        })
        
        sites_data = {
            "site1": site1_data,
            "site2": site2_data,
        }
        
        correlations = model.analyze_multi_site_correlation(sites_data)
        
        if correlations:
            # Correlation should be lower
            site_corr = abs(correlations["site1"]["site2"])
            assert site_corr < 0.7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
