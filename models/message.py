"""
Data models for conversations and messages.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


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

    def add_message(self, message: Message) -> None:
        """Add a message to the conversation."""
        self.messages.append(message)
        self.updated_at = datetime.now()
        self.total_tokens += message.tokens

    def get_last_message(self) -> Optional[Message]:
        """Get the last message in the conversation."""
        return self.messages[-1] if self.messages else None

    def get_context_window(self) -> list[dict]:
        """Convert messages to OpenAI API format."""
        return [
            {"role": msg.role.value, "content": msg.content}
            for msg in self.messages
        ]


@dataclass
class ConversationSettings:
    """User settings for a conversation."""
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 0.95
    repetition_penalty: float = 1.0
    system_prompt: str = "You are a helpful AI assistant."

    def to_dict(self) -> dict:
        """Convert to API request parameters."""
        return {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "repetition_penalty": self.repetition_penalty,
        }
