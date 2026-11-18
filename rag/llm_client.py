
"""Groq LLM client for SahayAI."""

import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from groq import Groq, RateLimitError


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load environment variables from project root.
load_dotenv(PROJECT_ROOT / ".env")


class GroqLLMClient:
    """Reusable client for generating responses through Groq."""

    def __init__(self, model: Optional[str] = None):
        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            raise ValueError(
                "GROQ_API_KEY is missing. Add it to the project .env file."
            )

        self.model = model or os.getenv(
            "GROQ_MODEL",
            "qwen/qwen3.8-27b"
        )

        self.client = Groq(
            api_key=api_key,
            timeout=30.0,
            max_retries=2
        )

    def generate(
        self,
        messages: list,
        max_tokens: int = 1024
    ) -> str:
        """Generate a response from a list of chat messages with automatic rate limit backoff."""

        if not messages:
            raise ValueError("Messages cannot be empty.")

        last_err = None
        for attempt in range(4):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_completion_tokens=max_tokens
                )
                content = response.choices[0].message.content
                if not content:
                    raise RuntimeError("Groq returned an empty response.")
                return content.strip()
            except RateLimitError as exc:
                last_err = exc
                if attempt < 3:
                    time.sleep(3.0 * (attempt + 1))
                else:
                    raise last_err
