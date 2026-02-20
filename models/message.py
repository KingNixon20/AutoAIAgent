"""
Data models for conversations and messages.

LM Studio is stateless: every request must include the full message history.
Memory is entirely managed by the client. Each conversation has its own
message list - never shared between chats.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum

from token_counter import count_text_tokens


class MessageRole(Enum):
    """Role of the message sender."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class Message:
    """Represents a single message in a conversation."""
    id: str
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    tokens: int = 0  # Approximate token count
    meta: Optional[dict] = None

    def __str__(self) -> str:
        return f"{self.role.value}: {self.content[:50]}..."


@dataclass
class Conversation:
    """Represents a conversation with multiple messages."""
    id: str
    title: str
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    model: str = "llama2-7b"
    total_tokens: int = 0
    chat_settings: Optional[dict] = None  # Per-chat override settings
    ai_tasks: list[dict] = field(default_factory=list)  # Planning tasks for this conversation
    chat_mode: str = "ask"  # ask | plan | agent
    agent_config: Optional[dict] = None  # {"project_name": str, "project_dir": str}

    def add_message(self, message: Message) -> None:
        """Add a message to the conversation."""
        if message.tokens <= 0:
            message.tokens = self._estimate_tokens(message.content, self.model)
        self.messages.append(message)
        self.updated_at = datetime.now()
        self.total_tokens += message.tokens

    def get_last_message(self) -> Optional[Message]:
        """Get the last message in the conversation."""
        return self.messages[-1] if self.messages else None

    def _estimate_tokens(self, text: str, model: Optional[str] = None) -> int:
        """Tokenizer-based token count for a single message text."""
        return count_text_tokens(text, model=model or self.model)

    def estimate_context_tokens(self, model: Optional[str] = None) -> int:
        """Estimate total tokens for all messages in this conversation."""
        target_model = model or self.model
        total = 0
        for msg in self.messages:
            if msg.tokens <= 0:
                msg.tokens = self._estimate_tokens(msg.content, target_model)
            total += msg.tokens
        self.total_tokens = total
        return total

    def get_context_window(self, max_tokens: Optional[int] = None) -> list[dict]:
        """Convert message history to OpenAI/LM Studio API format.
        
        LM Studio is stateless: the full messages array is sent with every request.
        System prompt is added separately by the API client.
        
        If max_tokens is set and history exceeds it, applies sliding window:
        keeps the most recent exchanges. Never removes the system prompt
        (that is added by the caller).
        """
        messages = [
            {"role": msg.role.value, "content": msg.content}
            for msg in self.messages
        ]
        if max_tokens is None:
            return messages

        estimated = self.estimate_context_tokens(model=self.model)
        if estimated <= max_tokens:
            return messages

        # Sliding window: keep most recent exchanges, drop oldest
        total = 0
        keep_from = len(self.messages)
        for i in range(len(self.messages) - 1, -1, -1):
            msg = self.messages[i]
            tokens = msg.tokens if msg.tokens > 0 else self._estimate_tokens(msg.content, self.model)
            if total + tokens > max_tokens and total > 0:
                keep_from = i + 1
                break
            total += tokens
            keep_from = i

        return [
            {"role": msg.role.value, "content": msg.content}
            for msg in self.messages[keep_from:]
        ]


@dataclass
class ConversationSettings:
    """User settings for a conversation."""
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 0.95
    repetition_penalty: float = 1.0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    seed: Optional[int] = None
    stop_sequences: Optional[list[str]] = None
    system_prompt: str = "You are a helpful AI assistant."
    context_limit: int = 4096  # Max tokens allowed in conversation context
    token_saver: bool = False  # Summarize history before each reply
    auto_tool_approval: bool = False  # Skip manual tool permission prompts
    tools: Optional[list] = None
    tool_choice: Optional[object] = None
    integrations: Optional[list[str]] = None  # MCP server ids e.g. ["mcp/playwright"]

    def to_dict(self) -> dict:
        """Convert to API request parameters."""
        d = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "repetition_penalty": self.repetition_penalty,
            "presence_penalty": self.presence_penalty,
            "frequency_penalty": self.frequency_penalty,
        }
        if self.seed is not None:
            d["seed"] = self.seed
        if self.stop_sequences:
            d["stop"] = self.stop_sequences
        if self.tools:
            d["tools"] = self.tools
        if self.tool_choice is not None:
            d["tool_choice"] = self.tool_choice
        if self.integrations:
            d["integrations"] = self.integrations
        return d
