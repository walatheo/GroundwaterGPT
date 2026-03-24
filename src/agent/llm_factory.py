"""
LLM Factory - Swappable LLM Provider

Change the provider in config to switch between:
- ollama (local, free)
- openai (GPT-4o, GPT-4.1)
- anthropic (Claude)
- gemini (Google)
"""

import os
from enum import Enum
from typing import Optional


class LLMProvider(Enum):
    """Supported LLM providers."""

    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


# Default configuration — switch provider here or via LLM_PROVIDER / LLM_MODEL env vars.
# Reads env vars at import time so the running server picks up changes without
# code edits: LLM_PROVIDER=anthropic LLM_MODEL=claude-3-5-sonnet-20241022
import os as _os

LLM_CONFIG = {
    "provider": LLMProvider(_os.getenv("LLM_PROVIDER", "anthropic")),
    "model": _os.getenv("LLM_MODEL", "claude-3-5-sonnet-20241022"),
    "temperature": 0.7,
    "max_tokens": 2048,
}


def get_llm(
    provider: Optional[LLMProvider] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    **kwargs,
):
    """
    Factory function to get the appropriate LLM based on provider.

    Args:
        provider: LLM provider (defaults to config)
        model: Model name (defaults to config)
        temperature: Temperature setting (defaults to config)
        **kwargs: Additional provider-specific arguments

    Returns:
        LangChain chat model instance

    Example:
        # Use default (Ollama/Llama)
        llm = get_llm()

        # Override provider
        llm = get_llm(provider=LLMProvider.OPENAI, model="gpt-4o")
    """
    provider = provider or LLM_CONFIG["provider"]
    model = model or LLM_CONFIG["model"]
    temperature = temperature if temperature is not None else LLM_CONFIG["temperature"]

    if provider == LLMProvider.OLLAMA:
        from langchain_ollama import ChatOllama

        return ChatOllama(model=model, temperature=temperature, **kwargs)

    elif provider == LLMProvider.OPENAI:
        from langchain_openai import ChatOpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        return ChatOpenAI(
            model=model or "gpt-4o", temperature=temperature, api_key=api_key, **kwargs
        )

    elif provider == LLMProvider.ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        return ChatAnthropic(
            model=model or "claude-3-sonnet-20240229",
            temperature=temperature,
            api_key=api_key,
            **kwargs,
        )

    elif provider == LLMProvider.GEMINI:
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set")
        return ChatGoogleGenerativeAI(
            model=model or "gemini-2.0-flash",
            temperature=temperature,
            google_api_key=api_key,
            **kwargs,
        )

    else:
        raise ValueError(f"Unsupported provider: {provider}")


def get_embeddings(provider: Optional[LLMProvider] = None):
    """
    Get embeddings model for the specified provider.

    For Ollama, uses nomic-embed-text.
    For others, uses their native embedding models.
    """
    provider = provider or LLM_CONFIG["provider"]

    if provider == LLMProvider.OLLAMA:
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(model="nomic-embed-text")

    elif provider == LLMProvider.OPENAI:
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model="text-embedding-3-small")

    elif provider == LLMProvider.GEMINI:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(model="models/embedding-001")

    else:
        # Fallback to HuggingFace embeddings
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")


def set_provider(provider: LLMProvider, model: Optional[str] = None):
    """Update the default provider configuration."""
    LLM_CONFIG["provider"] = provider
    if model:
        LLM_CONFIG["model"] = model


# Provider-specific model recommendations
RECOMMENDED_MODELS = {
    LLMProvider.OLLAMA: ["llama3.2", "qwen2.5:7b", "mistral", "deepseek-r1:7b"],
    LLMProvider.OPENAI: ["gpt-4o", "gpt-4.1", "gpt-4o-mini"],
    LLMProvider.ANTHROPIC: ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229"],
    LLMProvider.GEMINI: ["gemini-2.0-flash", "gemini-1.5-pro"],
}
