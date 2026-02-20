"""
LM Studio API client for chat completions.

Tool support: Include tools and tool_choice in each request for the model
to call tools. MCP/config lives in LM Studio; tool schemas must be sent
with every request if you want them usable.
"""
import asyncio
import json
import logging
from typing import Optional, AsyncIterator
import aiohttp
from models import Message, MessageRole, Conversation, ConversationSettings
import constants as C

logger = logging.getLogger(__name__)


class LMStudioError(Exception):
    """Base exception for LM Studio client errors."""
    pass


class ConnectionError(LMStudioError):
    """Raised when unable to connect to LM Studio."""
    pass


class LMStudioClient:
    """Client for communicating with LM Studio API."""

    def __init__(self, endpoint: str = C.API_ENDPOINT_DEFAULT):
        """Initialize the LM Studio client.
        
        Args:
            endpoint: Base URL of the LM Studio API (e.g., http://localhost:1234/v1)
        """
        self.endpoint = endpoint
        self.session: Optional[aiohttp.ClientSession] = None
        self._is_connected = False

    async def initialize(self) -> None:
        """Asynchronously initialize the HTTP session."""
        self.session = aiohttp.ClientSession()

    async def close(self) -> None:
        """Close the HTTP session."""
        if self.session:
            await self.session.close()

    async def check_connection(self) -> bool:
        """Check if LM Studio is available.
        
        Returns:
            True if connected, False otherwise.
        """
        try:
            async with self.session.get(
                f"{self.endpoint}{C.API_MODELS}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                self._is_connected = resp.status == 200
                return self._is_connected
        except Exception as e:
            logger.error(f"Connection check failed: {e}")
            self._is_connected = False
            return False

    @property
    def is_connected(self) -> bool:
        """Get connection status."""
        return self._is_connected

    async def get_available_models(self) -> list[str]:
        """Get list of available models from LM Studio.
        
        Returns:
            List of model names.
        """
        try:
            async with self.session.get(
                f"{self.endpoint}{C.API_MODELS}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [m["id"] for m in data.get("data", [])]
        except Exception as e:
            logger.error(f"Failed to fetch models: {e}")
        return []

    async def chat_completion(
        self,
        conversation: Conversation,
        settings: ConversationSettings,
    ) -> AsyncIterator[str]:
        """Stream chat completion from LM Studio.
        
        Args:
            conversation: The conversation context.
            settings: The completion settings.
            
        Yields:
            Text chunks as they arrive from the API.
            
        Raises:
            ConnectionError: If unable to connect to LM Studio.
        """
        # Use fresh session - safe when called from different event loop (e.g. background thread)
        session = aiohttp.ClientSession()

        # Check connection with this session
        try:
            async with session.get(
                f"{self.endpoint}{C.API_MODELS}",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    await session.close()
                    raise ConnectionError(f"Cannot reach LM Studio at {self.endpoint}")
        except Exception as e:
            await session.close()
            raise ConnectionError(f"Cannot reach LM Studio: {e}") from e

        # Full conversation context for AI memory - all prior messages + current
        messages = conversation.get_context_window()
        # Add system prompt if not already present
        if messages and messages[0]["role"] != "system":
            messages.insert(0, {"role": "system", "content": settings.system_prompt})

        logger.info("Sending %d messages (context + current) to API", len(messages))

        payload = {
            "model": conversation.model,
            "messages": messages,
            "stream": True,
            **settings.to_dict(),
        }

        try:
            async with session.post(
                f"{self.endpoint}{C.API_CHAT_COMPLETIONS}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=C.API_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise LMStudioError(f"API error {resp.status}: {error_text}")

                async for line in resp.content:
                    if not line:
                        continue

                    line_str = line.decode("utf-8").strip()
                    if line_str.startswith("data: "):
                        data_str = line_str[6:]  # Remove "data: " prefix
                        if data_str == "[DONE]":
                            break

                        try:
                            data = json.loads(data_str)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to decode JSON: {data_str}")
                            continue
        except asyncio.TimeoutError:
            raise LMStudioError("API request timed out")
        except Exception as e:
            logger.error(f"Chat completion error: {e}")
            raise
        finally:
            await session.close()

    async def count_tokens(self, text: str) -> int:
        """Estimate token count (rough estimation based on text length).
        
        LM Studio doesn't have a tokenize endpoint, so we estimate.
        This is a very rough approximation: ~4 chars per token.
        
        Args:
            text: Text to count tokens for.
            
        Returns:
            Estimated token count.
        """
        return max(1, len(text) // 4)

