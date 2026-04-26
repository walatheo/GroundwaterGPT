"""Shared model configuration helpers for local Qwen synthesis."""

from __future__ import annotations

import os


def resolve_local_qwen_model(*specific_env_vars: str, default: str = "qwen3:8b") -> str:
    """Resolve the local Qwen/Ollama model using one precedence chain.

    Specific feature env vars win first, then the project-wide override, then
    legacy names. Keeping this in one place prevents CLI ``--model`` overrides
    from being shadowed by older ``SYNTHESIS_MODEL`` settings.
    """
    env_chain = (
        *specific_env_vars,
        "GROUNDWATERGPT_LLM_MODEL",
        "SYNTHESIS_MODEL",
        "LLM_MODEL",
    )
    for name in env_chain:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return default
