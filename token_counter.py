"""Shared tokenizer-backed token counting utilities."""
from __future__ import annotations

import logging
from threading import Lock

logger = logging.getLogger(__name__)


class TokenCounter:
    """Tokenizer-backed token counter with model-aware encoding selection."""

    def __init__(self):
        self._lock = Lock()
        self._tiktoken = None
        self._encodings = {}
        self._has_tiktoken = False
        self._init_tokenizer()

    def _init_tokenizer(self) -> None:
        try:
            import tiktoken  # type: ignore

            self._tiktoken = tiktoken
            self._has_tiktoken = True
        except Exception:
            self._tiktoken = None
            self._has_tiktoken = False
            logger.warning("tiktoken not available, falling back to rough token estimates")

    def _encoding_for_model(self, model: str | None):
        if not self._has_tiktoken:
            return None
        key = (model or "").strip() or "default"
        cached = self._encodings.get(key)
        if cached is not None:
            return cached
        with self._lock:
            cached = self._encodings.get(key)
            if cached is not None:
                return cached
            try:
                if model:
                    enc = self._tiktoken.encoding_for_model(model)
                else:
                    enc = self._tiktoken.get_encoding("cl100k_base")
            except Exception:
                enc = self._tiktoken.get_encoding("cl100k_base")
            self._encodings[key] = enc
            return enc

    def count_text(self, text: str, model: str | None = None) -> int:
        """Count tokens in plain text for the target model."""
        text = text or ""
        if not text:
            return 0
        enc = self._encoding_for_model(model)
        if enc is None:
            return max(1, len(text) // 4)
        try:
            return len(enc.encode(text))
        except Exception:
            return max(1, len(text) // 4)


_counter = TokenCounter()


def count_text_tokens(text: str, model: str | None = None) -> int:
    """Module-level convenience wrapper for tokenizer counting."""
    return _counter.count_text(text, model=model)
