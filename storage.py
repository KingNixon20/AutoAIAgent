"""
Persistence layer for saving and loading conversations.
"""
import json
import os
from datetime import datetime
from typing import Optional

from models import Conversation, Message, MessageRole, ConversationSettings
import constants as C


def _get_config_dir() -> str:
    """Get config directory path."""
    config_dir = os.path.join(os.path.expanduser("~"), ".config", "AutoAIAgent")
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def _settings_to_dict(settings: ConversationSettings) -> dict:
    """Serialize ConversationSettings to a JSON-serializable dict."""
    return {
        "auto_tool_approval": settings.auto_tool_approval,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "top_p": settings.top_p,
        "repetition_penalty": settings.repetition_penalty,
        "presence_penalty": settings.presence_penalty,
        "frequency_penalty": settings.frequency_penalty,
        "seed": settings.seed,
        "stop_sequences": settings.stop_sequences,
        "system_prompt": settings.system_prompt,
        "context_limit": settings.context_limit,
        "token_saver": settings.token_saver,
        "project_directory": settings.project_directory,
    }

def _settings_from_dict(data: dict) -> ConversationSettings:
    """Deserialize ConversationSettings from a dict."""
    return ConversationSettings(
        auto_tool_approval=data.get("auto_tool_approval", False),
        temperature=data.get("temperature", C.DEFAULT_TEMPERATURE),
        max_tokens=data.get("max_tokens", C.DEFAULT_MAX_TOKENS),
        top_p=data.get("top_p", C.DEFAULT_TOP_P),
        repetition_penalty=data.get("repetition_penalty", C.DEFAULT_REPETITION_PENALTY),
        presence_penalty=data.get("presence_penalty", 0.0),
        frequency_penalty=data.get("frequency_penalty", 0.0),
        seed=data.get("seed"), # None if not present
        stop_sequences=data.get("stop_sequences"), # None if not present
        system_prompt=data.get("system_prompt", C.DEFAULT_SYSTEM_PROMPT),
        context_limit=data.get("context_limit", C.DEFAULT_CONTEXT_LIMIT),
        token_saver=data.get("token_saver", False),
        project_directory=data.get("project_directory", None),
    )

def _get_settings_path() -> str:
    """Get path to the global settings data file."""
    return os.path.join(_get_config_dir(), "settings.json")

def load_settings() -> ConversationSettings:
    """Load global application settings from disk.
    
    Returns:
        ConversationSettings object, or default settings if file doesn't exist or is invalid.
    """
    path = _get_settings_path()
    if not os.path.exists(path):
        return ConversationSettings() # Return default settings if file doesn't exist
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _settings_from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"Warning: Could not load settings: {e}")
        return ConversationSettings() # Return default settings on error

def save_settings(settings: ConversationSettings) -> None:
    """Save global application settings to disk.
    
    Args:
        settings: ConversationSettings object to save.
    """
    path = _get_settings_path()
    data = _settings_to_dict(settings)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"Error saving settings: {e}")


def _get_storage_path() -> str:
    """Get path to the conversations data file."""
    return os.path.join(_get_config_dir(), "conversations.json")


def load_mcp_servers() -> list[dict]:
    """Scan MCP config files and return available MCP servers and their calls.

    Searches locations (merged):
    - ~/.lmstudio/mcp.json (Linux/macOS)
    - %USERPROFILE%\\.lmstudio\\mcp.json (Windows)
    - ~/.config/AutoAIAgent/mcp.json (app-local custom servers)

    Returns:
        List of dicts with keys: `id` (integration id), `name` (display name),
        `calls` (list of call names). Example:
        [{"id": "mcp/playwright", "name": "playwright", "calls": ["run", "status"]}]
    """
    configs = load_mcp_server_configs()
    result = []
    for integration_id, item in configs.items():
        cfg = item.get("config", {}) if isinstance(item, dict) else {}
        calls = []
        if isinstance(cfg, dict):
            calls = cfg.get("calls") or cfg.get("actions") or []
        result.append(
            {
                "id": integration_id,
                "name": item.get("name") if isinstance(item, dict) else integration_id,
                "calls": list(calls) if isinstance(calls, list) else [],
            }
        )
    # Built-in local filesystem MCP-like integration (always available client-side).
    result.append(
        {
            "id": "mcp/builtin_filesystem",
            "name": "builtin_filesystem",
            "calls": ["read_file", "write_file", "edit_file", "delete_file"],
        }
    )
    return result


def load_mcp_server_configs() -> dict[str, dict]:
    """Load merged MCP server configs with full metadata.

    Returns:
        Dict keyed by integration id, value:
        {
          "id": "mcp/<name>",
          "name": "<name>",
          "config": {...},
          "sources": ["lmstudio", "app"]
        }
    """
    merged: dict[str, dict] = {}
    for source, path in _iter_mcp_paths():
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            servers = data.get("mcpServers") or data.get("mcp_servers")
            # Support files that list server entries at the top-level
            if not isinstance(servers, dict) and isinstance(data, dict):
                servers = data
            if servers is None:
                servers = {}
            if not isinstance(servers, dict):
                continue
            for name, meta in servers.items():
                if not name or not isinstance(meta, dict):
                    continue
                integration_id = f"mcp/{name}"
                # Some mcp.json variants wrap actual settings under a `config` key
                # and may include a human-friendly `name`. Normalize into a flat
                # `config` dict and a display `name`.
                if isinstance(meta.get("config"), dict):
                    cfg = dict(meta.get("config"))
                else:
                    cfg = dict(meta)

                display_name = meta.get("name") if isinstance(meta.get("name"), str) else name

                existing = merged.get(integration_id)
                if not existing:
                    merged[integration_id] = {
                        "id": integration_id,
                        "name": display_name,
                        "config": cfg,
                        "sources": [source],
                    }
                else:
                    # Later sources override scalar fields, merge dict/list fields.
                    existing_cfg = existing.get("config", {})
                    _merge_mcp_dict(existing_cfg, cfg)
                    existing["config"] = existing_cfg
                    sources = existing.get("sources", [])
                    if source not in sources:
                        sources.append(source)
                        existing["sources"] = sources
        except (json.JSONDecodeError, IOError, AttributeError):
            continue
    return merged


def _iter_mcp_paths() -> list[tuple[str, str]]:
    """Yield MCP config sources in precedence order."""
    paths: list[tuple[str, str]] = [
        ("lmstudio", os.path.join(os.path.expanduser("~"), ".lmstudio", "mcp.json")),
    ]
    if os.name == "nt":
        paths.insert(0, ("lmstudio", os.path.join(os.environ.get("USERPROFILE", ""), ".lmstudio", "mcp.json")))
    paths.append(("app", os.path.join(_get_config_dir(), "mcp.json")))
    # Also include a project-local mcp_servers/mcp.json for development/testing
    try:
        repo_path = os.path.join(os.path.dirname(__file__), "mcp_servers", "mcp.json")
        paths.append(("repo", repo_path))
    except Exception:
        pass
    return paths


def _merge_mcp_dict(base: dict, incoming: dict) -> None:
    """Merge incoming MCP config into base."""
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            nested = base.get(key)
            if isinstance(nested, dict):
                _merge_mcp_dict(nested, value)
        elif isinstance(value, list) and isinstance(base.get(key), list):
            current = base.get(key) or []
            seen = set(current)
            for item in value:
                if item not in seen:
                    current.append(item)
                    seen.add(item)
            base[key] = current
        else:
            base[key] = value


def save_app_mcp_server(server_name: str, server_config: dict) -> tuple[bool, str]:
    """Save/update one MCP server entry in app-local mcp.json.

    Args:
        server_name: MCP server key name.
        server_config: Dict for this server (url/command/args/env/etc).

    Returns:
        (ok, message)
    """
    name = (server_name or "").strip()
    if not name:
        return (False, "Server name is required.")

    path = os.path.join(_get_config_dir(), "mcp.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            data = {}

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers[name] = server_config
    data["mcpServers"] = servers

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return (True, f"Saved MCP server '{name}'.")
    except IOError as e:
        return (False, f"Failed to save MCP server: {e}")


def load_app_mcp_servers() -> dict:
    """Load app-local MCP servers from ~/.config/AutoAIAgent/mcp.json."""
    path = os.path.join(_get_config_dir(), "mcp.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        servers = data.get("mcpServers")
        return servers if isinstance(servers, dict) else {}
    except (json.JSONDecodeError, IOError):
        return {}


def delete_app_mcp_server(server_name: str) -> tuple[bool, str]:
    """Delete one app-local MCP server by name."""
    name = (server_name or "").strip()
    if not name:
        return (False, "Server name is required.")
    path = os.path.join(_get_config_dir(), "mcp.json")
    if not os.path.exists(path):
        return (False, "No app-local mcp.json found.")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        servers = data.get("mcpServers")
        if not isinstance(servers, dict) or name not in servers:
            return (False, f"Server '{name}' not found.")
        del servers[name]
        data["mcpServers"] = servers
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return (True, f"Deleted MCP server '{name}'.")
    except (json.JSONDecodeError, IOError) as e:
        return (False, f"Failed to delete MCP server: {e}")


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
    data = {
        "id": msg.id,
        "role": msg.role.value,
        "content": msg.content,
        "timestamp": msg.timestamp.isoformat(),
        "tokens": msg.tokens,
    }
    if msg.meta is not None:
        data["meta"] = msg.meta
    return data


def _message_from_dict(data: dict) -> Message:
    """Deserialize a Message from a dict."""
    return Message(
        id=data["id"],
        role=MessageRole(data["role"]),
        content=data["content"],
        timestamp=datetime.fromisoformat(data["timestamp"]),
        tokens=data.get("tokens", 0),
        meta=data.get("meta"),
    )


def _conversation_to_dict(conv: Conversation) -> dict:
    """Serialize a Conversation to a JSON-serializable dict."""
    data = {
        "id": conv.id,
        "title": conv.title,
        "model": conv.model,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "total_tokens": conv.total_tokens,
        "messages": [_message_to_dict(m) for m in conv.messages],
        "ai_tasks": conv.ai_tasks if isinstance(conv.ai_tasks, list) else [],
        "chat_mode": conv.chat_mode if str(getattr(conv, "chat_mode", "ask")) in ("ask", "plan", "agent") else "ask",
        "active_context_files": conv.active_context_files if isinstance(conv.active_context_files, dict) else {},
    }
    if conv.chat_settings is not None:
        data["chat_settings"] = conv.chat_settings
    if isinstance(conv.agent_config, dict):
        data["agent_config"] = conv.agent_config
    return data


def _conversation_from_dict(data: dict) -> Conversation:
    """Deserialize a Conversation from a dict."""
    conv = Conversation(
        id=data["id"],
        title=data["title"],
        model=data.get("model", "llama2-7b"),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
        total_tokens=data.get("total_tokens", 0),
        chat_settings=data.get("chat_settings"),
        ai_tasks=data.get("ai_tasks") if isinstance(data.get("ai_tasks"), list) else [],
        chat_mode=data.get("chat_mode") if str(data.get("chat_mode")) in ("ask", "plan", "agent") else "ask",
        agent_config=data.get("agent_config") if isinstance(data.get("agent_config"), dict) else None,
        active_context_files=data.get("active_context_files") if isinstance(data.get("active_context_files"), dict) else {},
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


def append_file(file_path: str, content: str) -> None:
    """Append content to a file."""
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"Error appending to file {file_path}: {e}")
        raise

def write_file(file_path: str, content: str) -> None:
    """Write content to a file."""
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)