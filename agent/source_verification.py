"""
Source Verification Module.

Validates that data sources are trusted and accurate before
being added to the knowledge base or used in research.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from urllib.parse import urlparse


class TrustLevel(Enum):
    """Trust levels for data sources."""

    VERIFIED = "verified"  # Official government/scientific sources
    TRUSTED = "trusted"  # Reputable academic/research institutions
    MODERATE = "moderate"  # General reliable sources
    UNKNOWN = "unknown"  # Unverified sources
    UNTRUSTED = "untrusted"  # Known unreliable sources


class SourceCategory(Enum):
    """Categories of data sources - prioritized by research value."""

    NUMERICAL_DATA = "numerical_data"  # APIs, databases with raw data
    RESEARCH_PAPER = "research_paper"  # Peer-reviewed publications
    GOVERNMENT_REPORT = "government_report"  # Official reports
    ACADEMIC = "academic"  # University/research institution
    REFERENCE = "reference"  # Encyclopedias, general reference
    NEWS = "news"  # News articles
    BLOG = "blog"  # Blogs, social media
    UNKNOWN = "unknown"


@dataclass
class SourceVerification:
    """Result of source verification."""

    url: str
    trust_level: TrustLevel
    source_type: str
    organization: str
    is_approved: bool
    reason: str
    category: SourceCategory = SourceCategory.UNKNOWN
    priority_score: float = 0.5  # 0.0 to 1.0, higher = more valuable

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "trust_level": self.trust_level.value,
            "source_type": self.source_type,
            "organization": self.organization,
            "is_approved": self.is_approved,
            "reason": self.reason,
            "category": self.category.value,
            "priority_score": self.priority_score,
        }


# =============================================================================
# TRUSTED SOURCE DEFINITIONS
# Priority: numerical_data > research_paper > government_report > academic > reference
# =============================================================================

# NUMERICAL DATA SOURCES (Highest Priority - score: 1.0)
# These provide raw, quantitative data for analysis
NUMERICAL_DATA_DOMAINS = {
    "waterdata.usgs.gov": ("USGS NWIS", "USGS National Water Information System - Real-time data"),
    "waterservices.usgs.gov": ("USGS API", "USGS Water Services API - Numerical data"),
    "water.usgs.gov": ("USGS Water", "USGS Water Resources - Data portal"),
    "cdec.water.ca.gov": ("CA CDEC", "California Data Exchange Center - Real-time data"),
    "water.weather.gov": ("NWS Hydro", "National Weather Service Hydrologic data"),
    "climatedata.ca": ("ClimateData", "Canadian climate data portal"),
    "ncdc.noaa.gov": ("NCDC", "National Climatic Data Center"),
}

# RESEARCH PAPER SOURCES (High Priority - score: 0.95)
# Peer-reviewed scientific publications
RESEARCH_PAPER_DOMAINS = {
    "doi.org": ("DOI", "Digital Object Identifier - Peer-reviewed publication"),
    "nature.com": ("Nature", "Nature Publishing Group - Peer-reviewed"),
    "science.org": ("Science", "AAAS Science - Peer-reviewed"),
    "agu.org": ("AGU", "American Geophysical Union - Hydrology journals"),
    "springer.com": ("Springer", "Springer Nature - Scientific journals"),
    "elsevier.com": ("Elsevier", "Elsevier - Scientific journals"),
    "wiley.com": ("Wiley", "Wiley - Scientific journals"),
    "sciencedirect.com": ("ScienceDirect", "Elsevier research articles"),
    "pubmed.ncbi.nlm.nih.gov": ("PubMed", "NIH biomedical literature"),
    "jstor.org": ("JSTOR", "Academic journal archive"),
    "researchgate.net": ("ResearchGate", "Academic papers network"),
    "arxiv.org": ("arXiv", "Preprint server - scientific papers"),
    "pnas.org": ("PNAS", "Proceedings of the National Academy of Sciences"),
    "tandfonline.com": ("Taylor & Francis", "Academic journals"),
    "mdpi.com": ("MDPI", "Open access scientific journals"),
    "frontiersin.org": ("Frontiers", "Open access research papers"),
}

# GOVERNMENT REPORTS (High Priority - score: 0.9)
# Official government and scientific organization reports
GOVERNMENT_REPORT_DOMAINS = {
    "usgs.gov": ("USGS", "US Geological Survey - Official reports"),
    "epa.gov": ("EPA", "Environmental Protection Agency"),
    "noaa.gov": ("NOAA", "National Oceanic and Atmospheric Administration"),
    "nasa.gov": ("NASA", "National Aeronautics and Space Administration"),
    "water.ca.gov": ("CA DWR", "California Department of Water Resources"),
    "ngwa.org": ("NGWA", "National Ground Water Association"),
    "unesco.org": ("UNESCO", "UN water resources reports"),
    "ipcc.ch": ("IPCC", "Climate change reports"),
    "who.int": ("WHO", "World Health Organization"),
    "worldbank.org": ("World Bank", "Water resources reports"),
}

# ACADEMIC INSTITUTIONS (Good Priority - score: 0.85)
ACADEMIC_DOMAINS = {
    ".edu": ("University", "US Academic Institution"),
    ".ac.uk": ("University", "UK Academic Institution"),
    ".edu.au": ("University", "Australian Academic Institution"),
    ".edu.cn": ("University", "Chinese Academic Institution"),
    "scholar.google.com": ("Google Scholar", "Academic search engine"),
    "groundwater.org": ("Groundwater Foundation", "Groundwater education"),
    "awwa.org": ("AWWA", "American Water Works Association"),
    "iwra.org": ("IWRA", "International Water Resources Association"),
}

# REFERENCE SOURCES (Moderate Priority - score: 0.6)
REFERENCE_DOMAINS = {
    "wikipedia.org": ("Wikipedia", "Community encyclopedia - verify citations"),
    "britannica.com": ("Britannica", "Encyclopedia Britannica"),
    "nationalgeographic.com": ("NatGeo", "National Geographic"),
}

# Official government and scientific organizations (VERIFIED)
VERIFIED_DOMAINS = {
    # US Government
    "usgs.gov": ("USGS", "US Geological Survey - Official groundwater data"),
    "epa.gov": ("EPA", "Environmental Protection Agency"),
    "noaa.gov": ("NOAA", "National Oceanic and Atmospheric Administration"),
    "nasa.gov": ("NASA", "National Aeronautics and Space Administration"),
    "water.ca.gov": ("CA DWR", "California Department of Water Resources"),
    "water.usgs.gov": ("USGS Water", "USGS Water Resources"),
    "waterdata.usgs.gov": ("USGS NWIS", "USGS National Water Information System"),
    "waterservices.usgs.gov": ("USGS API", "USGS Water Services API"),
    "ngwa.org": ("NGWA", "National Ground Water Association"),
    # International Scientific
    "unesco.org": ("UNESCO", "United Nations Educational, Scientific and Cultural Organization"),
    "ipcc.ch": ("IPCC", "Intergovernmental Panel on Climate Change"),
    "who.int": ("WHO", "World Health Organization"),
    # Academic Publishers (peer-reviewed)
    "doi.org": ("DOI", "Digital Object Identifier - Peer-reviewed publication"),
    "nature.com": ("Nature", "Nature Publishing Group"),
    "science.org": ("Science", "AAAS Science"),
    "agu.org": ("AGU", "American Geophysical Union"),
    "springer.com": ("Springer", "Springer Nature"),
    "elsevier.com": ("Elsevier", "Elsevier Scientific Publishing"),
    "wiley.com": ("Wiley", "John Wiley & Sons"),
}

# Academic and research institutions (TRUSTED)
TRUSTED_DOMAINS = {
    # Universities (general pattern)
    ".edu": ("University", "US Academic Institution"),
    ".ac.uk": ("University", "UK Academic Institution"),
    ".edu.au": ("University", "Australian Academic Institution"),
    # Research institutions
    "researchgate.net": ("ResearchGate", "Academic social network"),
    "sciencedirect.com": ("ScienceDirect", "Elsevier research platform"),
    "scholar.google.com": ("Google Scholar", "Academic search engine"),
    "pubmed.ncbi.nlm.nih.gov": ("PubMed", "NIH biomedical literature"),
    "jstor.org": ("JSTOR", "Digital library of academic journals"),
    # Professional organizations
    "groundwater.org": ("Groundwater Foundation", "Groundwater education"),
    "awwa.org": ("AWWA", "American Water Works Association"),
    "iwra.org": ("IWRA", "International Water Resources Association"),
}

# Moderate trust - general reliable sources
MODERATE_DOMAINS = {
    "wikipedia.org": ("Wikipedia", "Community encyclopedia - verify citations"),
    "britannica.com": ("Britannica", "Encyclopedia Britannica"),
    "nationalgeographic.com": ("NatGeo", "National Geographic"),
}

# Known unreliable or non-scientific sources
UNTRUSTED_PATTERNS = [
    r"blog\.",
    r"\.blogspot\.",
    r"medium\.com",
    r"quora\.com",
    r"yahoo\.answers",
    r"reddit\.com",
    r"facebook\.com",
    r"twitter\.com",
    r"tiktok\.com",
    r"youtube\.com",  # Unless official channel
]


# =============================================================================
# VERIFICATION FUNCTIONS
# =============================================================================


def verify_source(url: str) -> SourceVerification:
    """
    Verify if a source URL is trusted for groundwater research.

    Prioritizes sources in this order:
    1. Numerical data sources (USGS APIs, data portals) - priority 1.0
    2. Research papers (peer-reviewed journals) - priority 0.95
    3. Government reports (EPA, NOAA, etc.) - priority 0.9
    4. Academic institutions (.edu) - priority 0.85
    5. Reference sources (Wikipedia, etc.) - priority 0.6

    Args:
        url: The URL to verify

    Returns:
        SourceVerification with trust assessment and priority score
    """
    if not url or url == "local://knowledge_base":
        return SourceVerification(
            url=url,
            trust_level=TrustLevel.VERIFIED,
            source_type="local",
            organization="Local Knowledge Base",
            is_approved=True,
            reason="Local knowledge base with pre-verified documents",
            category=SourceCategory.RESEARCH_PAPER,
            priority_score=1.0,
        )

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]

        # Check for untrusted patterns first
        for pattern in UNTRUSTED_PATTERNS:
            if re.search(pattern, url.lower()):
                return SourceVerification(
                    url=url,
                    trust_level=TrustLevel.UNTRUSTED,
                    source_type="social/blog",
                    organization="Unknown",
                    is_approved=False,
                    reason=f"Source matches untrusted pattern: {pattern}",
                    category=SourceCategory.BLOG,
                    priority_score=0.0,
                )

        # Priority 1: Check NUMERICAL DATA sources (highest value)
        for num_domain, (org, desc) in NUMERICAL_DATA_DOMAINS.items():
            if domain.endswith(num_domain) or domain == num_domain:
                return SourceVerification(
                    url=url,
                    trust_level=TrustLevel.VERIFIED,
                    source_type="numerical_data_api",
                    organization=org,
                    is_approved=True,
                    reason=f"📊 NUMERICAL DATA: {desc}",
                    category=SourceCategory.NUMERICAL_DATA,
                    priority_score=1.0,
                )

        # Priority 2: Check RESEARCH PAPER sources
        for research_domain, (org, desc) in RESEARCH_PAPER_DOMAINS.items():
            if domain.endswith(research_domain) or domain == research_domain:
                return SourceVerification(
                    url=url,
                    trust_level=TrustLevel.VERIFIED,
                    source_type="peer_reviewed",
                    organization=org,
                    is_approved=True,
                    reason=f"📄 RESEARCH PAPER: {desc}",
                    category=SourceCategory.RESEARCH_PAPER,
                    priority_score=0.95,
                )

        # Priority 3: Check GOVERNMENT REPORT sources
        for gov_domain, (org, desc) in GOVERNMENT_REPORT_DOMAINS.items():
            if domain.endswith(gov_domain) or domain == gov_domain:
                return SourceVerification(
                    url=url,
                    trust_level=TrustLevel.VERIFIED,
                    source_type="government_report",
                    organization=org,
                    is_approved=True,
                    reason=f"🏛️ GOVERNMENT: {desc}",
                    category=SourceCategory.GOVERNMENT_REPORT,
                    priority_score=0.9,
                )

        # Priority 4: Check ACADEMIC sources
        for academic_domain, (org, desc) in ACADEMIC_DOMAINS.items():
            if domain.endswith(academic_domain) or domain == academic_domain:
                return SourceVerification(
                    url=url,
                    trust_level=TrustLevel.TRUSTED,
                    source_type="academic",
                    organization=org,
                    is_approved=True,
                    reason=f"🎓 ACADEMIC: {desc}",
                    category=SourceCategory.ACADEMIC,
                    priority_score=0.85,
                )

        # Priority 5: Check REFERENCE sources
        for ref_domain, (org, desc) in REFERENCE_DOMAINS.items():
            if domain.endswith(ref_domain) or domain == ref_domain:
                return SourceVerification(
                    url=url,
                    trust_level=TrustLevel.MODERATE,
                    source_type="reference",
                    organization=org,
                    is_approved=True,
                    reason=f"📚 REFERENCE: {desc}",
                    category=SourceCategory.REFERENCE,
                    priority_score=0.6,
                )

        # Legacy checks for backward compatibility
        # Check verified domains
        for verified_domain, (org, desc) in VERIFIED_DOMAINS.items():
            if domain.endswith(verified_domain) or domain == verified_domain:
                return SourceVerification(
                    url=url,
                    trust_level=TrustLevel.VERIFIED,
                    source_type="government/scientific",
                    organization=org,
                    is_approved=True,
                    reason=desc,
                    category=SourceCategory.GOVERNMENT_REPORT,
                    priority_score=0.9,
                )

        # Check trusted domains
        for trusted_domain, (org, desc) in TRUSTED_DOMAINS.items():
            if domain.endswith(trusted_domain) or domain == trusted_domain:
                return SourceVerification(
                    url=url,
                    trust_level=TrustLevel.TRUSTED,
                    source_type="academic/research",
                    organization=org,
                    is_approved=True,
                    reason=desc,
                    category=SourceCategory.ACADEMIC,
                    priority_score=0.85,
                )

        # Check moderate domains
        for mod_domain, (org, desc) in MODERATE_DOMAINS.items():
            if domain.endswith(mod_domain) or domain == mod_domain:
                return SourceVerification(
                    url=url,
                    trust_level=TrustLevel.MODERATE,
                    source_type="reference",
                    organization=org,
                    is_approved=True,  # Allowed but flagged
                    reason=desc,
                    category=SourceCategory.REFERENCE,
                    priority_score=0.6,
                )

        # Unknown source - NOT APPROVED by default
        return SourceVerification(
            url=url,
            trust_level=TrustLevel.UNKNOWN,
            source_type="unknown",
            organization="Unknown",
            is_approved=False,
            reason="⚠️ Source not in verified list - requires numerical data or research paper",
            category=SourceCategory.UNKNOWN,
            priority_score=0.0,
        )

    except Exception as e:
        return SourceVerification(
            url=url,
            trust_level=TrustLevel.UNKNOWN,
            source_type="error",
            organization="Unknown",
            is_approved=False,
            reason=f"Error parsing URL: {e}",
            category=SourceCategory.UNKNOWN,
            priority_score=0.0,
        )


def verify_usgs_data(site_id: str, response_data: dict) -> SourceVerification:
    """
    Verify that USGS data is authentic.

    Args:
        site_id: USGS site identifier
        response_data: Raw response from USGS API

    Returns:
        SourceVerification confirming data authenticity
    """
    # Check for required USGS response structure
    has_timeseries = "value" in response_data and "timeSeries" in response_data.get("value", {})

    if has_timeseries:
        return SourceVerification(
            url=f"https://waterservices.usgs.gov/nwis/dv/?sites={site_id}",
            trust_level=TrustLevel.VERIFIED,
            source_type="api",
            organization="USGS NWIS",
            is_approved=True,
            reason="Verified USGS National Water Information System API response",
        )
    else:
        return SourceVerification(
            url=f"usgs://{site_id}",
            trust_level=TrustLevel.UNKNOWN,
            source_type="api",
            organization="Unknown",
            is_approved=False,
            reason="Response does not match expected USGS API structure",
        )


def verify_document(
    file_path: str,
    content_sample: Optional[str] = None,
) -> SourceVerification:
    """
    Verify a document before adding to knowledge base.

    Args:
        file_path: Path to the document
        content_sample: Optional sample of content for analysis

    Returns:
        SourceVerification with approval status
    """
    import os

    filename = os.path.basename(file_path).lower()

    # Known verified documents (pre-approved hydrogeology references)
    verified_docs = [
        "a-conceptual-overview-of-surface-and-near-surface-brines",
        "a-glossary-of-hydrogeology",
        "age-dating-young-groundwater",
    ]

    for doc in verified_docs:
        if doc in filename:
            return SourceVerification(
                url=f"file://{file_path}",
                trust_level=TrustLevel.VERIFIED,
                source_type="document",
                organization="Pre-verified Reference",
                is_approved=True,
                reason="Document in pre-approved hydrogeology reference list",
            )

    # Check file extension
    if not filename.endswith(".pdf"):
        return SourceVerification(
            url=f"file://{file_path}",
            trust_level=TrustLevel.UNKNOWN,
            source_type="document",
            organization="Unknown",
            is_approved=False,
            reason="Only PDF documents are accepted for knowledge base",
        )

    # Unknown document - requires manual approval
    return SourceVerification(
        url=f"file://{file_path}",
        trust_level=TrustLevel.UNKNOWN,
        source_type="document",
        organization="Unknown",
        is_approved=False,
        reason="Document requires manual verification before adding to knowledge base",
    )


def filter_verified_sources(sources: list[str]) -> tuple[list[str], list[str]]:
    """
    Filter a list of sources into approved and rejected.

    Args:
        sources: List of URLs to verify

    Returns:
        Tuple of (approved_sources, rejected_sources)
    """
    approved = []
    rejected = []

    for source in sources:
        verification = verify_source(source)
        if verification.is_approved:
            approved.append(source)
        else:
            rejected.append(source)

    return approved, rejected


def get_minimum_trust_level() -> TrustLevel:
    """Get the minimum trust level for automatic approval."""
    return TrustLevel.MODERATE


def is_source_approved(url: str, min_trust: TrustLevel = TrustLevel.MODERATE) -> bool:
    """
    Quick check if a source meets minimum trust requirements.

    Args:
        url: Source URL to check
        min_trust: Minimum trust level required

    Returns:
        True if source is approved
    """
    verification = verify_source(url)

    trust_order = [
        TrustLevel.UNTRUSTED,
        TrustLevel.UNKNOWN,
        TrustLevel.MODERATE,
        TrustLevel.TRUSTED,
        TrustLevel.VERIFIED,
    ]

    source_level = trust_order.index(verification.trust_level)
    required_level = trust_order.index(min_trust)

    return source_level >= required_level


def prioritize_sources(sources: list[str]) -> list[tuple[str, SourceVerification]]:
    """
    Sort sources by priority, favoring numerical data and research papers.

    Priority order:
    1. Numerical data sources (USGS APIs, data portals)
    2. Research papers (peer-reviewed journals)
    3. Government reports
    4. Academic institutions
    5. Reference sources

    Args:
        sources: List of source URLs

    Returns:
        List of (url, verification) tuples sorted by priority (highest first)
    """
    verified = [(url, verify_source(url)) for url in sources]

    # Sort by priority_score descending, then by trust level
    return sorted(verified, key=lambda x: (x[1].priority_score, x[1].is_approved), reverse=True)


def filter_by_category(sources: list[str], categories: list[SourceCategory]) -> list[str]:
    """
    Filter sources to only include specific categories.

    Args:
        sources: List of source URLs
        categories: Categories to include (e.g., NUMERICAL_DATA, RESEARCH_PAPER)

    Returns:
        Filtered list of URLs matching the categories
    """
    filtered = []
    for url in sources:
        verification = verify_source(url)
        if verification.category in categories:
            filtered.append(url)
    return filtered


def get_high_value_sources(sources: list[str], min_priority: float = 0.85) -> list[str]:
    """
    Get only high-value sources (numerical data and research papers).

    Args:
        sources: List of source URLs
        min_priority: Minimum priority score (default 0.85 = academic and above)

    Returns:
        List of high-value source URLs
    """
    high_value = []
    for url in sources:
        verification = verify_source(url)
        if verification.priority_score >= min_priority and verification.is_approved:
            high_value.append(url)
    return high_value
