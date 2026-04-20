"""GroundwaterGPT Agent Module.

Agentic RAG system for groundwater research and analysis.
Supports the Qwen backends only: Ollama (local Qwen) and DashScope (hosted Qwen).
Includes source verification for data quality assurance.

Source Priority:
1. Numerical data (USGS APIs, data portals) - priority 1.0
2. Research papers (peer-reviewed journals) - priority 0.95
3. Government reports - priority 0.9
4. Academic institutions - priority 0.85
5. Reference sources - priority 0.6
"""

# LLM factory and source verification have no heavy optional deps — always safe.
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

# DeepResearchAgent requires chromadb / sentence-transformers / onnxruntime.
# Wrap so the package can still be imported when those deps are missing
# (e.g. Python 3.13 where onnxruntime has no wheel yet). Callers that need
# the agent should check for None first.
try:
    from .research_agent import DeepResearchAgent, deep_research
except ImportError:
    DeepResearchAgent = None  # type: ignore[assignment,misc]
    deep_research = None  # type: ignore[assignment]

__all__ = [
    # Agent systems
    "DeepResearchAgent",
    "deep_research",
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
