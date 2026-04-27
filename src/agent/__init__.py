"""GroundwaterGPT agent module.

Live response-generation primitives. The dormant DeepResearchAgent and
its companion modules have been moved to ``legacy/`` (see HANDOFF.md).
"""

from .llm_factory import LLMProvider, get_llm
from .source_verification import (
    SourceCategory,
    TrustLevel,
    filter_by_category,
    get_high_value_sources,
    is_source_approved,
    prioritize_sources,
    verify_document,
    verify_source,
    verify_usgs_data,
)

__all__ = [
    "get_llm",
    "LLMProvider",
    "SourceCategory",
    "TrustLevel",
    "verify_source",
    "verify_usgs_data",
    "verify_document",
    "is_source_approved",
    "prioritize_sources",
    "filter_by_category",
    "get_high_value_sources",
]
