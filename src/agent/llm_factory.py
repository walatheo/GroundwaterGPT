"""LLM factory — Qwen only.

Two backends are supported, both serving Qwen models:

- ``ollama`` — local Qwen via the Ollama runtime (default; no API key).
- ``qwen``  — hosted Qwen via Alibaba DashScope (requires ``DASHSCOPE_API_KEY``).

Anthropic / OpenAI / Gemini are intentionally not part of this factory. The
project's policy is Qwen-only synthesis; legacy support for other vendors was
removed because silent fallback to a non-Qwen model is a bug, not a feature.
"""

import os
from enum import Enum
from typing import Optional

from src.agent.model_config import resolve_local_qwen_model


class LLMProvider(Enum):
    """Supported LLM backends — both serve Qwen."""

    OLLAMA = "ollama"
    QWEN = "qwen"


# Default configuration. Reads env vars at import time so the running server
# picks up changes without code edits.
LLM_CONFIG = {
    "provider": LLMProvider(os.getenv("LLM_PROVIDER", "ollama")),
    "model": resolve_local_qwen_model(),
    "temperature": 0.7,
    "max_tokens": 2048,
}


def get_llm(
    provider: Optional[LLMProvider] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    **kwargs,
):
    """Return a LangChain chat model bound to one of the Qwen backends.

    Args:
        provider: Backend choice (defaults to config — Ollama).
        model: Model name (defaults to config — ``qwen3:8b`` for Ollama).
        temperature: Sampling temperature.
        **kwargs: Additional provider-specific arguments forwarded to the
            underlying client.
    """
    provider = provider or LLM_CONFIG["provider"]
    model = model or LLM_CONFIG["model"]
    temperature = temperature if temperature is not None else LLM_CONFIG["temperature"]

    if provider == LLMProvider.OLLAMA:
        from langchain_ollama import ChatOllama

        return ChatOllama(model=model, temperature=temperature, **kwargs)

    if provider == LLMProvider.QWEN:
        from langchain_openai import ChatOpenAI

        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError("DASHSCOPE_API_KEY environment variable not set")
        return ChatOpenAI(
            model=model or "qwen-plus",
            temperature=temperature,
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            **kwargs,
        )

    raise ValueError(f"Unsupported provider: {provider}")


def get_embeddings(provider: Optional[LLMProvider] = None):
    """Return an embeddings model for the requested backend.

    Ollama uses ``nomic-embed-text`` locally; Qwen via DashScope uses
    ``text-embedding-v3``. Both produce dense vectors compatible with the
    knowledge-base store.
    """
    provider = provider or LLM_CONFIG["provider"]

    if provider == LLMProvider.OLLAMA:
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(model="nomic-embed-text")

    if provider == LLMProvider.QWEN:
        from langchain_openai import OpenAIEmbeddings

        api_key = os.getenv("DASHSCOPE_API_KEY", "")
        return OpenAIEmbeddings(
            model="text-embedding-v3",
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    # Local fallback: HuggingFace BGE — used when Ollama embeddings aren't
    # available (e.g., in CI without the local Ollama daemon).
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")


def set_provider(provider: LLMProvider, model: Optional[str] = None):
    """Update the default provider configuration."""
    LLM_CONFIG["provider"] = provider
    if model:
        LLM_CONFIG["model"] = model


# Recommended Qwen models per backend. Ordered fastest → most capable.
RECOMMENDED_MODELS = {
    LLMProvider.OLLAMA: ["qwen3:8b", "qwen3:32b", "qwen2.5:7b", "qwen2.5:14b"],
    # Qwen via DashScope (https://dashscope.aliyuncs.com).
    LLMProvider.QWEN: ["qwen-plus", "qwen-turbo", "qwen-max", "qwen2.5-72b-instruct"],
}
