"""
GroundwaterGPT Agent Module

Agentic RAG system for groundwater research and analysis.
Supports multiple LLM providers (Ollama, OpenAI, Anthropic, Gemini).
"""

from .groundwater_agent import GroundwaterAgent
from .llm_factory import LLMProvider, get_llm

__all__ = ["GroundwaterAgent", "get_llm", "LLMProvider"]
