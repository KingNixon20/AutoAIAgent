"""
LM Studio API client for chat completions.

Tool support: Include tools and tool_choice in each request for the model
to call tools. MCP/config lives in LM Studio; tool schemas must be sent
with every request if you want them usable.
"""
import asyncio
import json
import logging
import re
from typing import Optional, AsyncIterator, Callable, Awaitable
import aiohttp
from models import Conversation, ConversationSettings
import constants as C
from token_counter import count_text_tokens

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

    async def get_loaded_model_id(self) -> Optional[str]:
        """Get the currently loaded model id from /v1/models data[0].id."""
        try:
            async with self.session.get(
                f"{self.endpoint}{C.API_MODELS}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                items = data.get("data") or []
                if not items:
                    return None
                model_id = items[0].get("id")
                if isinstance(model_id, str) and model_id.strip():
                    return model_id.strip()
        except Exception as e:
            logger.error(f"Failed to read loaded model id: {e}")
        return None

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
        final_text = await self.chat_completion_with_tools(
            conversation=conversation,
            settings=settings,
            tool_executor=None,
        )
        if final_text:
            yield final_text

    async def chat_completion_with_tools(
        self,
        conversation: Conversation,
        settings: ConversationSettings,
        tool_executor: Optional[Callable[[str, dict], Awaitable[str]]] = None,
        on_tool_event: Optional[Callable[[dict], None]] = None,
        max_tool_rounds: int = 8,
    ) -> str:
        """Run completion loop with tool-call detection/execution.

        The model may return tool calls instead of final content. In that case,
        this method executes each call via `tool_executor`, appends tool results,
        and continues until a final assistant message is returned.
        """
        # Use the session managed by the LMStudioClient instance
        if not self.session:
            # This should ideally not happen if initialize() was awaited, but for safety
            await self.initialize() # Ensure session is created

        # Check connection with this session
        try:
            async with self.session.get( # Use self.session
                f"{self.endpoint}{C.API_MODELS}",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    # No need to close self.session here, it's managed by the client
                    raise ConnectionError(f"Cannot reach LM Studio at {self.endpoint}")
        except Exception as e:
            # No need to close self.session here
            raise ConnectionError(f"Cannot reach LM Studio: {e}") from e

        # Full conversation context for AI memory - all prior messages + current
        if settings.token_saver:
            full_history = conversation.get_context_window(max_tokens=None)
            fallback_history = conversation.get_context_window(max_tokens=settings.context_limit)
            messages = await self._build_token_saver_messages(
                session=session,
                conversation=conversation,
                settings=settings,
                full_history=full_history,
                fallback_history=fallback_history,
            )
        else:
            raw_messages = conversation.get_context_window(max_tokens=settings.context_limit)
            messages = self._normalize_messages(raw_messages)
        # Add system prompt if configured.
        if settings.system_prompt:
            if (
                not messages
                or messages[0].get("role") != "system"
                or str(messages[0].get("content", "")) != str(settings.system_prompt)
            ):
                messages.insert(0, {"role": "system", "content": settings.system_prompt})

        logger.info("Sending %d messages (context + current) to API", len(messages))

        settings_payload = settings.to_dict()
        normalized_tools = self._normalize_tools(settings_payload.get("tools"))
        if normalized_tools:
            settings_payload["tools"] = normalized_tools
            if settings_payload.get("tool_choice") is None:
                settings_payload["tool_choice"] = "auto"
            logger.info(
                "Normalized %d tools for API request with tool_choice='%s'",
                len(normalized_tools),
                settings_payload.get("tool_choice"),
            )
            for tool in normalized_tools:
                if isinstance(tool, dict):
                    fn = tool.get("function") or {}
                    name = fn.get("name", "?")
                    desc = fn.get("description", "")
                    logger.debug("  • %s: %s", name, desc)
        else:
            settings_payload.pop("tools", None)
            settings_payload.pop("tool_choice", None)

        logger.info("Payload base ready: model=%s messages=%d", conversation.model, len(messages))

        accumulated_text_parts: list[str] = []
        auto_continue_budget = 2
        try:
            for round_idx in range(max_tool_rounds):
                response = await self._chat_completion_once(
                    session=session,
                    model=conversation.model,
                    messages=messages,
                    settings_payload=settings_payload,
                )
                choice = (response.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                finish_reason = str(choice.get("finish_reason") or "")
                content = self._extract_assistant_content(choice, message)
                tool_calls = self._extract_tool_calls(choice, message)
                if content:
                    accumulated_text_parts.append(content)

                # No tool calls: return final assistant text
                if not tool_calls:
                    # If model hit max_tokens, ask it to continue once/twice and merge output.
                    if finish_reason == "length" and auto_continue_budget > 0:
                        messages.append(
                            {
                                "role": "assistant",
                                "content": str(content),
                            }
                        )
                        messages.append(
                            {
                                "role": "user",
                                "content": "Continue from where you left off. Do not repeat previous text.",
                            }
                        )
                        auto_continue_budget -= 1
                        continue
                    merged = "".join(part for part in accumulated_text_parts if part)
                    return merged if merged else str(content)

                # Model asked for tools, but runtime has no executor
                if tool_executor is None:
                    logger.warning("Model requested tools, but no tool executor is configured")
                    merged = "".join(part for part in accumulated_text_parts if part)
                    return merged if merged else str(content)

                # Append assistant tool-call message first
                messages.append(
                    {
                        "role": "assistant",
                        "content": str(content) if content is not None else "",
                        "tool_calls": tool_calls,
                    }
                )

                # Execute each requested tool and append tool result messages
                for tool_call in tool_calls:
                    tool_id = tool_call.get("id") or ""
                    fn = tool_call.get("function") or {}
                    tool_name = str(fn.get("name", "")).strip()
                    raw_args = fn.get("arguments") or "{}"
                    args = self._parse_tool_args(raw_args)
                    result_text = await self._execute_tool_safe(tool_executor, tool_name, args)
                    if on_tool_event is not None:
                        try:
                            on_tool_event(
                                {
                                    "tool_call_id": tool_id,
                                    "name": tool_name,
                                    "args": args,
                                    "result": self._safe_json_parse(result_text),
                                }
                            )
                        except Exception as callback_error:
                            logger.warning("tool event callback failed: %s", callback_error)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "name": tool_name,
                            "content": result_text,
                        }
                    )

                logger.info(
                    "Completed tool round %d with %d call(s)",
                    round_idx + 1,
                    len(tool_calls),
                )

            raise LMStudioError("Exceeded tool-call round limit without final response")
        except asyncio.TimeoutError as e:
            await session.close()
            raise LMStudioError(f"API request timed out (exceeded {C.API_TIMEOUT}s)")
        except aiohttp.ClientConnectorError as e:
            await session.close()
            raise LMStudioError(f"Failed to connect to LM Studio: {e}")
        except aiohttp.ClientSSLError as e:
            await session.close()
            raise LMStudioError(f"SSL error connecting to LM Studio: {e}")
        except aiohttp.ClientError as e:
            await session.close()
            raise LMStudioError(f"Client error: {e}")
        except Exception as e:
            await session.close()
            logger.error(f"Chat completion error: {e}")
            raise LMStudioError(f"Unexpected error: {e}")
        finally:
            if not session.closed:
                await session.close()

    async def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        """Count tokens using the configured tokenizer.

        Args:
            text: Text to count tokens for.
            model: Optional model id for tokenizer selection.

        Returns:
            Token count.
        """
        return count_text_tokens(text, model=model)

    async def _build_token_saver_messages(
        self,
        session: aiohttp.ClientSession,
        conversation: Conversation,
        settings: ConversationSettings,
        full_history: list[dict],
        fallback_history: list[dict],
    ) -> list[dict]:
        """Compress prior history into a summary + latest user message."""
        fallback = self._normalize_messages(fallback_history)
        messages = self._normalize_messages(full_history)
        if len(messages) < 2:
            return fallback if fallback else messages

        latest = messages[-1]
        if str(latest.get("role", "")) != "user":
            return fallback if fallback else messages

        history = messages[:-1]
        history_text = self._render_history_for_summary(history, settings.context_limit)
        if not history_text:
            return fallback if fallback else messages

        summary_text = await self._summarize_history(
            session=session,
            model=conversation.model,
            history_text=history_text,
            context_limit=settings.context_limit,
        )
        if not summary_text:
            return fallback if fallback else messages

        logger.info("Token saver active: compressed %d history messages into summary", len(history))
        return [
            {
                "role": "system",
                "content": (
                    "Conversation summary so far. Treat this as trusted context from earlier turns:\n\n"
                    f"{summary_text}"
                ),
            },
            {"role": "user", "content": str(latest.get("content", ""))},
        ]

    async def _summarize_history(
        self,
        session: aiohttp.ClientSession,
        model: str,
        history_text: str,
        context_limit: int,
    ) -> Optional[str]:
        """Create a concise summary of prior chat history."""
        summary_messages = [
            {
                "role": "system",
                "content": (
                    "You compress chat history for context retention. Return a concise factual summary only. "
                    "Preserve requirements, constraints, decisions, unresolved questions, and concrete values. "
                    "Do not add commentary or markdown headings."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Summarize this conversation history so the assistant can continue accurately.\n\n"
                    f"{history_text}"
                ),
            },
        ]
        summary_max_tokens = max(192, min(1024, int(max(context_limit, 512) * 0.25)))
        summary_settings = {
            "temperature": 0.1,
            "top_p": 0.9,
            "max_tokens": summary_max_tokens,
        }
        try:
            response = await self._chat_completion_once(
                session=session,
                model=model,
                messages=summary_messages,
                settings_payload=summary_settings,
            )
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            summary_text = self._extract_assistant_content(choice, message).strip()
            return summary_text or None
        except Exception as e:
            logger.warning("Token saver summary failed: %s", e)
            return None

    def _render_history_for_summary(self, history: list[dict], context_limit: int) -> str:
        """Render message history into bounded text for the summarizer model."""
        if not history:
            return ""
        char_budget = max(
            8000,
            min(
                50000,
                int(max(context_limit, 512) * max(int(getattr(C, "CHARS_PER_TOKEN_EST", 4)), 2) * 2.5),
            ),
        )
        per_message_cap = 2200
        chunks: list[str] = []
        for item in history:
            role = str(item.get("role", "message")).strip().lower() or "message"
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            if len(content) > per_message_cap:
                omitted = len(content) - per_message_cap
                content = f"{content[:per_message_cap]}\n...[{omitted} chars omitted]"
            if role == "tool":
                name = str(item.get("name", "")).strip()
                role = f"tool:{name}" if name else "tool"
            chunks.append(f"{role}: {content}")
        rendered = "\n\n".join(chunks)
        if len(rendered) > char_budget:
            rendered = "[Older history truncated]\n\n" + rendered[-char_budget:]
        return rendered

    def _normalize_messages(self, messages: list[dict]) -> list[dict]:
        """Normalize messages to valid role/content dicts."""
        normalized = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip().lower()
            content = item.get("content", "")
            if role not in {"system", "user", "assistant", "tool"}:
                continue
            if content is None:
                content = ""
            msg = {"role": role, "content": str(content)}
            if role == "tool":
                if item.get("tool_call_id"):
                    msg["tool_call_id"] = str(item.get("tool_call_id"))
                if item.get("name"):
                    msg["name"] = str(item.get("name"))
            if role == "assistant" and isinstance(item.get("tool_calls"), list):
                msg["tool_calls"] = item.get("tool_calls")
            normalized.append(msg)
        return normalized

    def _normalize_tools(self, tools: object) -> Optional[list[dict]]:
        """Normalize tool definitions to OpenAI-compatible function tools."""
        if not isinstance(tools, list):
            return None
        logger.debug("Normalizing %d tools from settings", len(tools))
        normalized = []
        for tool in tools:
            entry = self._normalize_single_tool(tool)
            if entry:
                fn_name = entry.get("function", {}).get("name", "?")
                desc = entry.get("function", {}).get("description", "")
                logger.debug("  Normalized: %s - %s", fn_name, desc)
                normalized.append(entry)
            else:
                logger.debug("  Skipped invalid tool: %s", tool)
        return normalized or None

    def _normalize_single_tool(self, tool: object) -> Optional[dict]:
        """Normalize one tool definition."""
        if not isinstance(tool, dict):
            return None

        # Already in expected shape: {"type":"function","function":{...}}
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            fn = tool["function"]
            name = self._sanitize_tool_name(fn.get("name"))
            if not name:
                return None
            params = fn.get("parameters")
            if not isinstance(params, dict):
                params = {"type": "object", "properties": {}}
            return {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(fn.get("description", "")).strip(),
                    "parameters": params,
                },
            }

        # Alternate shorthand: {"name":"...", "description":"...", "parameters":{...}}
        name = self._sanitize_tool_name(tool.get("name"))
        if not name:
            return None
        params = tool.get("parameters")
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": str(tool.get("description", "")).strip(),
                "parameters": params,
            },
        }

    def _sanitize_tool_name(self, name: object) -> Optional[str]:
        """Tool names must be simple identifiers for LM Studio/OpenAI APIs."""
        if name is None:
            return None
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", str(name).strip())
        if not cleaned:
            return None
        return cleaned[:64]

    def _extract_assistant_content(self, choice: dict, message: dict) -> str:
        """Extract assistant text from varied response shapes."""
        # Primary chat shape
        content = message.get("content")
        parsed = self._content_to_text(content)
        if parsed:
            return parsed
        # Some providers include legacy text field
        text_choice = choice.get("text")
        parsed = self._content_to_text(text_choice)
        if parsed:
            return parsed
        # Some providers expose output text at the choice level
        parsed = self._content_to_text(choice.get("output_text"))
        if parsed:
            return parsed
        return ""

    def _content_to_text(self, content: object) -> str:
        """Convert string/parts content to text."""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            if isinstance(content.get("text"), str):
                return str(content.get("text"))
            if isinstance(content.get("content"), str):
                return str(content.get("content"))
            return ""
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    item_type = str(item.get("type") or "").lower()
                    if item_type in {"text", "output_text"} and isinstance(item.get("text"), str):
                        parts.append(item.get("text"))
                    elif isinstance(item.get("text"), str):
                        parts.append(item.get("text"))
                    elif isinstance(item.get("content"), str):
                        parts.append(item.get("content"))
            return "".join(parts)
        return str(content)

    def _extract_tool_calls(self, choice: dict, message: dict) -> list[dict]:
        """Extract tool calls across provider response variants."""
        raw = message.get("tool_calls")
        if isinstance(raw, list):
            return [tc for tc in raw if isinstance(tc, dict)]
        if isinstance(raw, dict):
            return [raw]

        # Legacy OpenAI-compatible single function_call format
        function_call = message.get("function_call") or choice.get("function_call")
        if isinstance(function_call, dict):
            return [
                {
                    "id": f"legacy_fc_{abs(hash(str(function_call))) % 10000000}",
                    "type": "function",
                    "function": {
                        "name": function_call.get("name"),
                        "arguments": function_call.get("arguments", "{}"),
                    },
                }
            ]
        return []

    async def _chat_completion_once(
        self,
        session: aiohttp.ClientSession,
        model: str,
        messages: list[dict],
        settings_payload: dict,
    ) -> dict:
        """Issue one non-stream completion request and return parsed JSON."""
        payload = {
            "model": model,
            "messages": self._normalize_messages(messages),
            "stream": False,
            **settings_payload,
        }
        settings_snapshot = {
            "temperature": payload.get("temperature"),
            "top_p": payload.get("top_p"),
            "repetition_penalty": payload.get("repetition_penalty"),
            "presence_penalty": payload.get("presence_penalty"),
            "frequency_penalty": payload.get("frequency_penalty"),
            "max_tokens": payload.get("max_tokens"),
            "seed": payload.get("seed"),
            "stop": payload.get("stop"),
            "tool_choice": payload.get("tool_choice"),
        }
        logger.info(
            "Payload ready: model=%s messages=%d tools=%d integrations=%d settings=%s",
            payload.get("model"),
            len(payload.get("messages", [])),
            len(payload.get("tools", []) if isinstance(payload.get("tools"), list) else []),
            len(payload.get("integrations", []) if isinstance(payload.get("integrations"), list) else []),
            settings_snapshot,
        )
        async with session.post(
            f"{self.endpoint}{C.API_CHAT_COMPLETIONS}",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=C.API_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise LMStudioError(f"API error {resp.status}: {error_text}")
            return await resp.json()

    def _parse_tool_args(self, raw_args: object) -> dict:
        """Parse tool arguments JSON safely."""
        if isinstance(raw_args, dict):
            return raw_args
        text = str(raw_args or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
            return {"_args": parsed}
        except json.JSONDecodeError:
            return {"_raw": text}

    async def _execute_tool_safe(
        self,
        tool_executor: Callable[[str, dict], Awaitable[str]],
        tool_name: str,
        args: dict,
    ) -> str:
        """Execute a tool and return safe string output for model context."""
        try:
            result = await tool_executor(tool_name, args)
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            logger.warning("Tool execution failed for %s: %s", tool_name, e)
            return f"Tool execution failed: {e}"

    def _safe_json_parse(self, value: str) -> object:
        """Parse JSON values when possible; otherwise return raw text."""
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except Exception:
            return value
