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
from .groundwater_research_model import (AnomalyDetection, AquiferProperties,
                                         AquiferType, DomainQueryExpander,
                                         GroundwaterResearchModel,
                                         SeasonalPattern,
                                         expand_groundwater_query,
                                         get_groundwater_model,
                                         validate_groundwater_data)
from .llm_factory import LLMProvider, get_llm
from .priority_search_engine import (MultiSourceSearchEngine, QueryPrioritizer,
                                     SearchPipeline, SearchQuery, SearchResult,
                                     SearchSourceType)
from .research_agent import DeepResearchAgent, deep_research
from .research_workflow import (GroundwaterResearchContext,
                                GroundwaterResearchWorkflow,
                                conduct_groundwater_research, research_async)
from .source_verification import (SourceCategory, TrustLevel,
                                  filter_by_category, get_high_value_sources,
                                  is_source_approved, prioritize_sources,
                                  verify_document, verify_source,
                                  verify_usgs_data)

__all__ = [
    # Agent systems
    "GroundwaterAgent",
    "DeepResearchAgent",
    "deep_research",
    "GroundwaterResearchWorkflow",
    "GroundwaterResearchContext",
    "conduct_groundwater_research",
    "research_async",
    # Domain model
    "GroundwaterResearchModel",
    "DomainQueryExpander",
    "AquiferType",
    "AquiferProperties",
    "SeasonalPattern",
    "AnomalyDetection",
    "get_groundwater_model",
    "expand_groundwater_query",
    "validate_groundwater_data",
    # Search engine
    "SearchPipeline",
    "MultiSourceSearchEngine",
    "QueryPrioritizer",
    "SearchQuery",
    "SearchResult",
    "SearchSourceType",
    # LLM factory
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
