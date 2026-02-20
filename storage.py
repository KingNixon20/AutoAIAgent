"""
Persistence layer for saving and loading conversations.
"""
import json
import os
from datetime import datetime
from typing import Optional

from models import Conversation, Message, MessageRole


def _get_config_dir() -> str:
    """Get config directory path."""
    config_dir = os.path.join(os.path.expanduser("~"), ".config", "AutoAIAgent")
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def _get_storage_path() -> str:
    """Get path to the conversations data file."""
    return os.path.join(_get_config_dir(), "conversations.json")


def load_mcp_servers() -> list[dict]:
    """Scan for LM Studio mcp.json and return available MCP servers and their calls.

    Searches common locations:
    - ~/.lmstudio/mcp.json (Linux/macOS)
    - %USERPROFILE%\\.lmstudio\\mcp.json (Windows)

    Returns:
        List of dicts with keys: `id` (integration id), `name` (display name),
        `calls` (list of call names). Example:
        [{"id": "mcp/playwright", "name": "playwright", "calls": ["run", "status"]}]
    """
    paths = [
        os.path.join(os.path.expanduser("~"), ".lmstudio", "mcp.json"),
    ]
    if os.name == "nt":
        paths.insert(0, os.path.join(os.environ.get("USERPROFILE", ""), ".lmstudio", "mcp.json"))
    
    for path in paths:
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            servers = data.get("mcpServers") or data.get("mcp_servers") or {}
            result = []
            for name, meta in servers.items():
                if not name:
                    continue
                integration_id = f"mcp/{name}"
                # Some MCP schemas may include a list of available calls/actions
                calls = []
                try:
                    # server entry can be dict with metadata; look for 'calls' or 'actions'
                    if isinstance(meta, dict):
                        calls = meta.get("calls") or meta.get("actions") or []
                    # otherwise ignore
                except Exception:
                    calls = []
                result.append({"id": integration_id, "name": name, "calls": calls})
            return result
        except (json.JSONDecodeError, IOError, AttributeError):
            continue
    return []


def load_tools() -> tuple[Optional[list], Optional[object]]:
    """Load tool definitions from tools.json if present.
    
    MCP/tool config lives in LM Studio; schemas must be sent in each request.
    Place tools.json in ~/.config/AutoAIAgent/ with format:
    {"tools": [...], "tool_choice": "auto"}
    
    Returns:
        (tools, tool_choice) or (None, None) if file missing/invalid.
    """
    path = os.path.join(_get_config_dir(), "tools.json")
    if not os.path.exists(path):
        return (None, None)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        tools = data.get("tools")
        tool_choice = data.get("tool_choice")
        return (tools if tools else None, tool_choice)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load tools: {e}")
        return (None, None)


def _message_to_dict(msg: Message) -> dict:
    """Serialize a Message to a JSON-serializable dict."""
    return {
        "id": msg.id,
        "role": msg.role.value,
        "content": msg.content,
        "timestamp": msg.timestamp.isoformat(),
        "tokens": msg.tokens,
    }


def _message_from_dict(data: dict) -> Message:
    """Deserialize a Message from a dict."""
    return Message(
        id=data["id"],
        role=MessageRole(data["role"]),
        content=data["content"],
        timestamp=datetime.fromisoformat(data["timestamp"]),
        tokens=data.get("tokens", 0),
    )


def _conversation_to_dict(conv: Conversation) -> dict:
    """Serialize a Conversation to a JSON-serializable dict."""
    return {
        "id": conv.id,
        "title": conv.title,
        "model": conv.model,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "total_tokens": conv.total_tokens,
        "messages": [_message_to_dict(m) for m in conv.messages],
    }


def _conversation_from_dict(data: dict) -> Conversation:
    """Deserialize a Conversation from a dict."""
    conv = Conversation(
        id=data["id"],
        title=data["title"],
        model=data.get("model", "llama2-7b"),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
        total_tokens=data.get("total_tokens", 0),
    )
    for m_data in data.get("messages", []):
        conv.messages.append(_message_from_dict(m_data))
    return conv


def load_conversations() -> list[Conversation]:
    """Load all saved conversations from disk.
    
    Returns:
        List of Conversation objects, or empty list if file doesn't exist or is invalid.
    """
    path = _get_storage_path()
    if not os.path.exists(path):
        return []
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [_conversation_from_dict(c) for c in data.get("conversations", [])]
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"Warning: Could not load conversations: {e}")
        return []


def save_conversations(conversations: list[Conversation]) -> None:
    """Save all conversations to disk.
    
    Args:
        conversations: List of Conversation objects to save.
    """
    path = _get_storage_path()
    data = {
        "conversations": [_conversation_to_dict(c) for c in conversations],
        "version": 1,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
