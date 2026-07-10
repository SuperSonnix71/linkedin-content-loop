"""
Shared OpenAI client — reads config from environment variables.
All pipeline nodes use the same client instance.
"""

from __future__ import annotations

import os
from functools import cache

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


@cache
def get_client() -> OpenAI:
    """Return a cached OpenAI client configured from env vars."""
    base_url = os.getenv("AI_BASE_URL", "http://localhost:11434/v1")
    api_key = os.getenv("AI_API_KEY", "ollama")
    return OpenAI(base_url=base_url, api_key=api_key)


@cache
def get_model() -> str:
    """Return the model name from env."""
    return os.getenv("AI_MODEL", "qwen3.6:35b")
