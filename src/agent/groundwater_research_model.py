"""Groundwater Domain-Specific Research Model.

Implements groundwater-specific knowledge for research:
- Aquifer properties and characteristics
- Domain-aware query expansion
- Validation rules for water level data
- Seasonal patterns and anomaly detection
- Multi-site correlation analysis

Enables research agents to conduct sophisticated groundwater investigations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class AquiferType(Enum):
    """Florida aquifer types."""

    BISCAYNE = "biscayne"
    FLORIDAN = "floridan"
    SURFICIAL = "surficial"


@dataclass
class AquiferProperties:
    """Properties and characteristics of a Florida aquifer."""

    name: str
    aquifer_type: AquiferType
    typical_depth_ft: Tuple[float, float]  # (min, max) below surface
    elevation_range_ft: Tuple[float, float]  # (min, max) MSL
    transmissivity_ft2_day: Optional[float] = None  # Gallons/day/ft
    storativity: Optional[float] = None
    specific_yield: Optional[float] = None
    recharge_rate_in_yr: Optional[float] = None

    # Sensitivity to drivers
    high_tide_sensitivity: bool = False
    rainfall_sensitivity_lag_days: int = 7
    evapotranspiration_sensitivity: bool = True
    pumping_sensitivity: bool = True

    # Monitoring sites in this aquifer
    typical_site_count: int = 0

    def validate_water_level(self, elevation_ft: float) -> Tuple[bool, str]:
        """
        Validate if a water level elevation is physically plausible.

        Args:
            elevation_ft: Water level elevation in feet MSL

        Returns:
            (is_valid, reason)
        """
        min_el, max_el = self.elevation_range_ft

        if elevation_ft < min_el - 50:  # Allow 50 ft buffer
            return (
                False,
                f"Elevation {elevation_ft} ft below range {min_el}-{max_el} ft",
            )
        if elevation_ft > max_el + 50:
            return (
                False,
                f"Elevation {elevation_ft} ft above range {min_el}-{max_el} ft",
            )

        return True, "Valid elevation range"

    def expected_seasonal_amplitude(self) -> float:
        """Expected seasonal water level variation in feet."""
        if self.aquifer_type == AquiferType.SURFICIAL:
            return 3.0  # Highly variable
        elif self.aquifer_type == AquiferType.BISCAYNE:
            return 1.5  # Moderate variation
        else:  # FLORIDAN
            return 0.5  # Minimal seasonal variation (confined)


# Florida Aquifer Database
FLORIDA_AQUIFERS = {
    "biscayne": AquiferProperties(
        name="Biscayne Aquifer",
        aquifer_type=AquiferType.BISCAYNE,
        typical_depth_ft=(10, 50),
        elevation_range_ft=(-100, 20),
        transmissivity_ft2_day=500000,  # Very high
        storativity=0.1,
        specific_yield=0.25,
        recharge_rate_in_yr=12,
        high_tide_sensitivity=True,  # Tidal fluctuations
        rainfall_sensitivity_lag_days=3,
        typical_site_count=16,
    ),
    "floridan": AquiferProperties(
        name="Floridan Aquifer System",
        aquifer_type=AquiferType.FLORIDAN,
        typical_depth_ft=(50, 200),
        elevation_range_ft=(-500, -200),
        transmissivity_ft2_day=50000,  # High
        storativity=0.0001,  # Confined
        specific_yield=0.01,
        recharge_rate_in_yr=4,
        high_tide_sensitivity=False,  # Too deep
        rainfall_sensitivity_lag_days=30,  # Lag of ~month
        typical_site_count=17,
    ),
    "surficial": AquiferProperties(
        name="Surficial Aquifer",
        aquifer_type=AquiferType.SURFICIAL,
        typical_depth_ft=(0, 20),
        elevation_range_ft=(-5, 15),
        transmissivity_ft2_day=5000,  # Low (sandy)
        storativity=0.2,
        specific_yield=0.2,
        recharge_rate_in_yr=20,  # Direct rainfall
        high_tide_sensitivity=True,
        rainfall_sensitivity_lag_days=1,
        typical_site_count=3,
    ),
}


class DomainQueryExpander:
    """
    Expands user queries with groundwater domain-specific terminology.

    Implements smart query augmentation for better search results.
    """

    # Domain terminology mappings
    SYNONYMS = {
        "water level": [
            "water elevation",
            "groundwater elevation",
            "aquifer elevation",
            "piezometric surface",
            "head",
            "static head",
            "hydraulic head",
        ],
        "aquifer": [
            "aquifer system",
            "aquifer unit",
            "water-bearing formation",
            "confining layer",
            "artesian aquifer",
        ],
        "recharge": [
            "groundwater recharge",
            "infiltration",
            "aquifer recharge",
            "water input",
            "rainfall infiltration",
        ],
        "discharge": [
            "groundwater discharge",
            "spring discharge",
            "baseflow",
            "submarine discharge",
            "groundwater outflow",
        ],
        "seasonal": [
            "seasonal variation",
            "seasonal fluctuation",
            "seasonal pattern",
            "annual cycle",
            "wet season",
            "dry season",
        ],
        "trend": [
            "long-term trend",
            "water level trend",
            "declining water level",
            "rising water level",
            "trend analysis",
        ],
        "drought": [
            "water deficit",
            "dry period",
            "precipitation deficit",
            "water shortage",
            "extreme drought",
        ],
        "flood": [
            "flooding",
            "high water",
            "inundation",
            "flooding event",
            "flood hazards",
        ],
    }

    REGIONAL_TERMS = {
        "florida": ["south florida", "florida aquifer", "florida groundwater"],
        "biscayne": ["miami", "dade county", "broward county", "biscayne aquifer"],
        "floridan": ["deep aquifer", "confined aquifer", "floridan system"],
        "surficial": ["shallow aquifer", "unconfined aquifer", "sandy aquifer"],
    }

    @staticmethod
    def expand_query(query: str) -> List[str]:
        """
        Expand a query with related terminology.

        Args:
            query: User query

        Returns:
            List of expanded queries to search
        """
        queries = [query]  # Original query
        query_lower = query.lower()

        # Add synonym variations
        for term, synonyms in DomainQueryExpander.SYNONYMS.items():
            if term in query_lower:
                for synonym in synonyms[:2]:  # Top 2 synonyms per term
                    expanded = query_lower.replace(term, synonym)
                    if expanded not in queries:
                        queries.append(expanded)

        # Add regional context
        for region, terms in DomainQueryExpander.REGIONAL_TERMS.items():
            if region in query_lower:
                for term in terms[:1]:  # One term per region
                    if term not in query_lower:
                        expanded = f"{query} {term}"
                        if expanded not in queries:
                            queries.append(expanded)

        # Add groundwater-specific context
        if "florida" in query_lower and "groundwater" not in query_lower:
            queries.append(f"florida groundwater {query}")

        return queries[:8]  # Limit to 8 expanded queries


@dataclass
class SeasonalPattern:
    """Detected seasonal pattern in water level time series."""

    site_id: str
    aquifer_type: AquiferType
    peak_month: int  # 1-12
    peak_elevation: float  # feet MSL
    trough_month: int
    trough_elevation: float
    annual_amplitude: float  # feet
    predictability_score: float  # 0.0-1.0

    def interpret(self) -> str:
        """Human-readable interpretation."""
        months = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]
        return (
            f"Peaks in {months[self.peak_month-1]} ({self.peak_elevation:.1f} ft), "
            f"troughs in {months[self.trough_month-1]} ({self.trough_elevation:.1f} ft), "
            f"amplitude {self.annual_amplitude:.1f} ft"
        )


@dataclass
class AnomalyDetection:
    """Detected anomaly in water level time series."""

    site_id: str
    date: datetime
    value: float
    expected_value: float
    deviation: float  # feet
    anomaly_type: str  # "spike", "drop", "sustained_high", "sustained_low"
    severity: float  # 0.0-1.0
    potential_cause: str

    def interpret(self) -> str:
        """Human-readable interpretation."""
        return (
            f"{self.anomaly_type.upper()}: {self.date.strftime('%Y-%m-%d')} "
            f"({self.value:.1f} ft, deviation {self.deviation:+.1f} ft) - "
            f"{self.potential_cause}"
        )


class GroundwaterResearchModel:
    """
    Implements groundwater domain knowledge for research.

    Combines aquifer properties, data validation, pattern detection,
    and multi-site analysis to support sophisticated research workflows.
    """

    def __init__(self):
        """Initialize groundwater research model."""
        self.aquifers = FLORIDA_AQUIFERS
        self.query_expander = DomainQueryExpander()

    def get_aquifer_info(self, aquifer_code: str) -> Optional[AquiferProperties]:
        """Get aquifer properties by code."""
        return self.aquifers.get(aquifer_code.lower())

    def classify_aquifer(self, site_id: str) -> Optional[AquiferType]:
        """
        Classify aquifer type by site ID (heuristic).

        Florida USGS site naming conventions vary, but elevation helps.
        """
        # This would use a real mapping in production
        for aquifer_code, props in self.aquifers.items():
            min_el, max_el = props.elevation_range_ft
            # Would need actual elevation data to classify
        return None

    def expand_research_query(self, query: str) -> List[str]:
        """Expand research query with domain terminology."""
        return self.query_expander.expand_query(query)

    def validate_water_level_data(
        self,
        df: pd.DataFrame,
        aquifer_type: AquiferType,
        site_id: str,
    ) -> Dict[str, any]:
        """
        Validate water level dataframe for a specific aquifer.

        Args:
            df: DataFrame with columns [date, elevation_ft]
            aquifer_type: Type of aquifer
            site_id: Site identifier

        Returns:
            Dict with validation results
        """
        aquifer = self.aquifers.get(aquifer_type.value)
        if not aquifer:
            return {"valid": False, "error": f"Unknown aquifer type: {aquifer_type}"}

        results = {
            "site_id": site_id,
            "aquifer": aquifer.name,
            "records": len(df),
            "issues": [],
            "warnings": [],
        }

        if df.empty:
            results["valid"] = False
            results["issues"].append("Empty DataFrame")
            return results

        # Check required columns
        if "elevation_ft" not in df.columns:
            results["issues"].append("Missing 'elevation_ft' column")

        if not df.empty and "elevation_ft" in df.columns:
            elevations = df["elevation_ft"]

            # Validate elevations
            min_el, max_el = aquifer.elevation_range_ft
            out_of_range = (elevations < min_el - 50) | (elevations > max_el + 50)

            if out_of_range.any():
                count = out_of_range.sum()
                results["warnings"].append(
                    f"{count} records outside typical range {min_el}-{max_el} ft"
                )

            # Check for gaps
            if "date" in df.columns:
                df_sorted = df.sort_values("date")
                date_diffs = df_sorted["date"].diff()
                expected_diff = pd.Timedelta(days=1)
                gaps = date_diffs[date_diffs > expected_diff * 2]

                if len(gaps) > 0:
                    results["warnings"].append(f"{len(gaps)} data gaps detected")

        results["valid"] = len(results["issues"]) == 0
        return results

    def detect_seasonal_pattern(
        self,
        df: pd.DataFrame,
        aquifer_type: AquiferType,
        site_id: str,
        min_years: int = 2,
    ) -> Optional[SeasonalPattern]:
        """
        Detect seasonal pattern in water level time series.

        Args:
            df: DataFrame with columns [date, elevation_ft]
            aquifer_type: Type of aquifer
            site_id: Site identifier
            min_years: Minimum years of data required

        Returns:
            SeasonalPattern if detected, None otherwise
        """
        if df.empty or "elevation_ft" not in df.columns:
            return None

        # Check data span
        if "date" in df.columns:
            date_span = (df["date"].max() - df["date"].min()).days / 365.25
            if date_span < min_years:
                logger.warning(
                    f"Insufficient data span: {date_span:.1f} years < {min_years} year(s)"
                )
                return None
        else:
            return None

        # Group by month and compute statistics
        df_copy = df.copy()
        df_copy["month"] = pd.to_datetime(df_copy["date"]).dt.month

        monthly_stats = df_copy.groupby("month")["elevation_ft"].agg(
            ["mean", "std", "count"]
        )

        # Find peak and trough
        peak_month = monthly_stats["mean"].idxmax()
        trough_month = monthly_stats["mean"].idxmin()

        peak_elevation = monthly_stats.loc[peak_month, "mean"]
        trough_elevation = monthly_stats.loc[trough_month, "mean"]
        annual_amplitude = peak_elevation - trough_elevation

        # Calculate predictability (inverse of variability)
        cv = (
            monthly_stats["std"].mean() / df_copy["elevation_ft"].mean()
        )  # Coefficient of variation
        predictability = max(0.0, 1.0 - cv)

        aquifer = self.aquifers.get(aquifer_type.value)
        expected_amplitude = aquifer.expected_seasonal_amplitude() if aquifer else 1.0

        pattern = SeasonalPattern(
            site_id=site_id,
            aquifer_type=aquifer_type,
            peak_month=int(peak_month),
            peak_elevation=float(peak_elevation),
            trough_month=int(trough_month),
            trough_elevation=float(trough_elevation),
            annual_amplitude=float(annual_amplitude),
            predictability_score=float(min(1.0, max(0.0, predictability))),
        )

        return pattern

    def detect_anomalies(
        self,
        df: pd.DataFrame,
        aquifer_type: AquiferType,
        site_id: str,
        method: str = "zscore",
        threshold: float = 3.0,
    ) -> List[AnomalyDetection]:
        """
        Detect anomalies in water level time series.

        Args:
            df: DataFrame with columns [date, elevation_ft]
            aquifer_type: Type of aquifer
            site_id: Site identifier
            method: Detection method ('zscore' or 'iqr')
            threshold: Threshold for anomaly detection

        Returns:
            List of detected anomalies
        """
        if df.empty or "elevation_ft" not in df.columns:
            return []

        anomalies = []
        elevations = df["elevation_ft"].values

        if method == "zscore":
            # Z-score based detection
            mean = np.nanmean(elevations)
            std = np.nanstd(elevations)

            if std == 0:
                return []

            z_scores = np.abs((elevations - mean) / std)
            anomaly_mask = z_scores > threshold

            aquifer = self.aquifers.get(aquifer_type.value)
            expected_amplitude = (
                aquifer.expected_seasonal_amplitude() if aquifer else 1.0
            )

            for idx, is_anomaly in enumerate(anomaly_mask):
                if is_anomaly and "date" in df.columns:
                    value = elevations[idx]
                    deviation = value - mean

                    # Classify anomaly type
                    if value > mean + 2 * std:
                        anomaly_type = "spike"
                        cause = "Unusual high value (possibly measurement error or flooding)"
                    elif value < mean - 2 * std:
                        anomaly_type = "drop"
                        cause = (
                            "Unusual low value (possibly drought or excessive pumping)"
                        )
                    else:
                        continue

                    anomaly = AnomalyDetection(
                        site_id=site_id,
                        date=df.iloc[idx]["date"],
                        value=float(value),
                        expected_value=float(mean),
                        deviation=float(deviation),
                        anomaly_type=anomaly_type,
                        severity=float(min(1.0, abs(z_scores[idx]) / (threshold * 2))),
                        potential_cause=cause,
                    )
                    anomalies.append(anomaly)

        return anomalies

    def analyze_multi_site_correlation(
        self,
        sites_data: Dict[str, pd.DataFrame],
        metric: str = "elevation_ft",
    ) -> Dict[str, float]:
        """
        Analyze correlations between water levels across multiple sites.

        Identifies regional synchrony (climate-driven) vs local patterns.

        Args:
            sites_data: Dict mapping site_id -> DataFrame
            metric: Field to correlate

        Returns:
            Correlation matrix as dict of dicts
        """
        if len(sites_data) < 2:
            return {}

        # Align data by date
        all_dates = None
        processed = {}

        for site_id, df in sites_data.items():
            if metric not in df.columns or "date" not in df.columns:
                continue

            df_sorted = df.sort_values("date")
            processed[site_id] = df_sorted.set_index("date")[metric]

            if all_dates is None:
                all_dates = set(df_sorted["date"])
            else:
                all_dates &= set(df_sorted["date"])

        if not processed or not all_dates:
            return {}

        # Create aligned DataFrame
        aligned_dates = sorted(list(all_dates))
        aligned_data = {}

        for site_id, series in processed.items():
            aligned_data[site_id] = series[aligned_dates]

        df_aligned = pd.DataFrame(aligned_data)

        # Compute correlations
        correlations = df_aligned.corr().to_dict()

        return correlations

    def summarize_research_context(self, sites: List[str]) -> str:
        """
        Generate research context summary for given sites.

        Args:
            sites: List of site IDs

        Returns:
            Human-readable context summary
        """
        summary = "## Research Context\n\n"
        summary += f"**Sites Under Investigation:** {len(sites)}\n"
        summary += f"Sites: {', '.join(sites[:5])}"
        if len(sites) > 5:
            summary += f", ... and {len(sites) - 5} more"
        summary += "\n\n"

        summary += "### Aquifer Information\n"
        for aquifer_code, props in self.aquifers.items():
            summary += f"\n**{props.name}**\n"
            summary += f"- Depth: {props.typical_depth_ft[0]}-{props.typical_depth_ft[1]} ft below surface\n"
            summary += f"- Elevation range: {props.elevation_range_ft[0]}-{props.elevation_range_ft[1]} ft MSL\n"
            summary += f"- Sites: {props.typical_site_count}\n"
            summary += f"- Sensitivity: Tides={props.high_tide_sensitivity}, "
            summary += f"Rainfall lag={props.rainfall_sensitivity_lag_days}d\n"

        return summary


# Convenience functions
def get_groundwater_model() -> GroundwaterResearchModel:
    """Get the groundwater domain model."""
    return GroundwaterResearchModel()


def validate_groundwater_data(
    df: pd.DataFrame,
    aquifer_type: AquiferType,
    site_id: str,
) -> Dict[str, any]:
    """Validate groundwater data for research use."""
    model = get_groundwater_model()
    return model.validate_water_level_data(df, aquifer_type, site_id)


def expand_groundwater_query(query: str) -> List[str]:
    """Expand a groundwater research query with domain terminology."""
    model = get_groundwater_model()
    return model.expand_research_query(query)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example: Query expansion
    query = "How has water level changed in Florida?"
    expanded = expand_groundwater_query(query)

    print(f"Original: {query}")
    print(f"Expanded queries:")
    for q in expanded:
        print(f"  - {q}")

    # Example: Aquifer info
    model = get_groundwater_model()
    biscayne = model.get_aquifer_info("biscayne")
    print(f"\nBiscayne Aquifer:")
    print(f"  Depth: {biscayne.typical_depth_ft} ft")
    print(f"  Elevation: {biscayne.elevation_range_ft} ft MSL")
    print(f"  Seasonal amplitude: {biscayne.expected_seasonal_amplitude()} ft")
