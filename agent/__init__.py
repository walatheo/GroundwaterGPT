"""GroundwaterGPT Agent Module.

Agentic RAG system for groundwater research and analysis.
Supports multiple LLM providers (Ollama, OpenAI, Anthropic, Gemini).
Includes source verification for data quality assurance.

Source Priority:
1. Numerical data (USGS APIs, data portals) - priority 1.0
2. Research papers (peer-reviewed journals) - priority 0.95
3. Government reports - priority 0.9
4. Academic institutions - priority 0.85
5. Reference sources - priority 0.6
"""

from .groundwater_agent import GroundwaterAgent
from .llm_factory import LLMProvider, get_llm
from .research_agent import DeepResearchAgent, deep_research
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
    "GroundwaterAgent",
    "DeepResearchAgent",
    "deep_research",
    "get_llm",
    "LLMProvider",
    # Source verification
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
