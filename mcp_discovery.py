"""MCP endpoint tool discovery and normalization."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class MCPToolDiscovery:
    """Discover tool definitions from configured MCP servers."""

    def __init__(self, timeout_sec: int = 12):
        self.timeout_sec = timeout_sec

    async def discover_tools(
        self,
        server_configs: dict[str, dict],
        enabled_integrations: Optional[list[str]] = None,
    ) -> list[dict]:
        """Discover and normalize tools from all enabled integrations."""
        if not isinstance(server_configs, dict) or not server_configs:
            return []

        selected_ids = set(enabled_integrations or [])
        if not selected_ids:
            return []

        tasks = []
        for integration_id, payload in server_configs.items():
            if integration_id not in selected_ids:
                continue
            cfg = payload.get("config") if isinstance(payload, dict) else None
            name = payload.get("name") if isinstance(payload, dict) else integration_id
            if not isinstance(cfg, dict):
                continue
            tasks.append(self._discover_single(integration_id, str(name), cfg))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_tools: list[dict] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("MCP discovery task failed: %s", result)
                continue
            all_tools.extend(result)

        return self._dedupe_by_function_name(all_tools)

    async def _discover_single(self, integration_id: str, name: str, cfg: dict) -> list[dict]:
        """Discover tools for one MCP server config."""
        raw_tools: list[dict] = []
        url = cfg.get("url")
        command = cfg.get("command")

        try:
            if isinstance(url, str) and url.strip():
                logger.info("Discovering tools from HTTP endpoint: %s", url)
                raw_tools = await self._discover_http(url.strip(), cfg)
            elif isinstance(command, str) and command.strip():
                logger.info("Discovering tools from stdio command: %s", command)
                raw_tools = await self._discover_stdio(command.strip(), cfg)
        except Exception as e:
            logger.debug(
                "Discovery failed for %s (%s), falling back to config-declared calls: %s",
                integration_id,
                name,
                e,
            )
            raw_tools = []

        if raw_tools:
            logger.info("Extracted %d tools from %s endpoint", len(raw_tools), integration_id)
            for tool in raw_tools:
                if isinstance(tool, dict):
                    logger.debug("  Raw tool: %s - %s", tool.get("name", "?"), tool.get("description", ""))

        if not raw_tools:
            # fallback to config-declared calls/actions with empty schema
            calls = cfg.get("calls") or cfg.get("actions") or []
            if isinstance(calls, list):
                logger.info(
                    "Using %d config-declared calls for %s: %s",
                    len(calls),
                    integration_id,
                    ", ".join(str(c) for c in calls),
                )
                raw_tools = [
                    {
                        "name": str(call),
                        "description": f"MCP action '{call}' from {name}",
                        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
                    }
                    for call in calls
                    if str(call).strip()
                ]

        normalized = [self._normalize_tool(integration_id, name, tool) for tool in raw_tools if isinstance(tool, dict)]
        if normalized:
            logger.info(
                "Normalized %d tools for %s: %s",
                len(normalized),
                integration_id,
                ", ".join(t.get("function", {}).get("name", "?") for t in normalized),
            )
        return normalized

    async def call_tool(self, integration_id: str, tool_name: str, arguments: dict, cfg: dict) -> dict:
        """Call an MCP tool on one server config and return result payload."""
        url = cfg.get("url")
        command = cfg.get("command")
        if isinstance(url, str) and url.strip():
            return await self._call_tool_http(url.strip(), cfg, tool_name, arguments)
        if isinstance(command, str) and command.strip():
            return await self._call_tool_stdio(command.strip(), cfg, tool_name, arguments)
        return {"ok": False, "error": f"No supported transport for {integration_id}"}

    async def _discover_http(self, url: str, cfg: dict) -> list[dict]:
        """Discover tools from HTTP MCP server using JSON-RPC."""
        headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
        timeout = aiohttp.ClientTimeout(total=self.timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Some servers require initialize first; if it fails, continue with tools/list.
            await self._post_jsonrpc(
                session,
                url,
                method="initialize",
                params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "AutoAIAgent", "version": "1.0"},
                },
                headers=headers,
                allow_fail=True,
            )
            resp = await self._post_jsonrpc(
                session,
                url,
                method="tools/list",
                params={},
                headers=headers,
                allow_fail=False,
            )
            return self._extract_tools_from_result(resp)

    async def _call_tool_http(self, url: str, cfg: dict, tool_name: str, arguments: dict) -> dict:
        headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
        timeout = aiohttp.ClientTimeout(total=self.timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            await self._post_jsonrpc(
                session,
                url,
                method="initialize",
                params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "AutoAIAgent", "version": "1.0"},
                },
                headers=headers,
                allow_fail=True,
            )
            resp = await self._post_jsonrpc(
                session,
                url,
                method="tools/call",
                params={"name": tool_name, "arguments": arguments or {}},
                headers=headers,
                allow_fail=False,
            )
            if isinstance(resp, dict) and isinstance(resp.get("result"), dict):
                return {"ok": True, "result": resp.get("result")}
            return {"ok": False, "error": f"Invalid tools/call response: {resp}"}

    async def _discover_stdio(self, command: str, cfg: dict) -> list[dict]:
        """Discover tools from stdio MCP server (best-effort JSON-RPC over lines)."""
        args = cfg.get("args") if isinstance(cfg.get("args"), list) else []
        env = cfg.get("env") if isinstance(cfg.get("env"), dict) else None

        proc = await asyncio.create_subprocess_exec(
            command,
            *[str(a) for a in args],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            await self._stdio_jsonrpc(proc, 1, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "AutoAIAgent", "version": "1.0"},
            }, allow_fail=True)
            resp = await self._stdio_jsonrpc(proc, 2, "tools/list", {}, allow_fail=False)
            return self._extract_tools_from_result(resp)
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    proc.kill()

    async def _call_tool_stdio(self, command: str, cfg: dict, tool_name: str, arguments: dict) -> dict:
        args = cfg.get("args") if isinstance(cfg.get("args"), list) else []
        env = cfg.get("env") if isinstance(cfg.get("env"), dict) else None
        proc = await asyncio.create_subprocess_exec(
            command,
            *[str(a) for a in args],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            await self._stdio_jsonrpc(
                proc,
                1,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "AutoAIAgent", "version": "1.0"},
                },
                allow_fail=True,
            )
            resp = await self._stdio_jsonrpc(
                proc,
                2,
                "tools/call",
                {"name": tool_name, "arguments": arguments or {}},
                allow_fail=False,
            )
            if isinstance(resp, dict) and isinstance(resp.get("result"), dict):
                return {"ok": True, "result": resp.get("result")}
            return {"ok": False, "error": f"Invalid tools/call response: {resp}"}
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    proc.kill()

    async def _post_jsonrpc(
        self,
        session: aiohttp.ClientSession,
        url: str,
        method: str,
        params: dict,
        headers: dict,
        allow_fail: bool,
    ) -> dict:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            async with session.post(url, json=payload, headers=headers) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400 and not allow_fail:
                    raise RuntimeError(f"HTTP {resp.status}: {data}")
                return data if isinstance(data, dict) else {}
        except Exception as e:
            if allow_fail:
                logger.debug("MCP initialize failed for %s: %s", url, e)
                return {}
            raise

    async def _stdio_jsonrpc(
        self,
        proc: asyncio.subprocess.Process,
        req_id: int,
        method: str,
        params: dict,
        allow_fail: bool,
    ) -> dict:
        if proc.stdin is None or proc.stdout is None:
            if allow_fail:
                return {}
            raise RuntimeError("stdio pipes unavailable")

        request = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        await proc.stdin.drain()

        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=self.timeout_sec)
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and data.get("id") == req_id:
                    return data
        except Exception as e:
            if allow_fail:
                logger.debug("MCP stdio call failed (%s): %s", method, e)
                return {}
            raise

        if allow_fail:
            return {}
        raise RuntimeError(f"No response for MCP method {method}")

    def _extract_tools_from_result(self, response: dict) -> list[dict]:
        """Extract tool list from JSON-RPC result payload."""
        if not isinstance(response, dict):
            return []
        result = response.get("result")
        if isinstance(result, dict):
            tools = result.get("tools")
            if isinstance(tools, list):
                return [t for t in tools if isinstance(t, dict)]
        return []

    def _normalize_tool(self, integration_id: str, server_name: str, tool: dict) -> dict:
        """Normalize MCP tool to OpenAI-compatible function tool definition."""
        raw_name = str(tool.get("name") or "tool").strip()
        fn_name = self._sanitize_tool_name(f"{integration_id.replace('/', '_')}_{raw_name}")
        description = str(tool.get("description") or f"MCP tool '{raw_name}' from {server_name}").strip()

        params = tool.get("inputSchema")
        if not isinstance(params, dict):
            params = tool.get("input_schema")
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}, "additionalProperties": True}
        if params.get("type") != "object":
            params = {
                "type": "object",
                "properties": {"input": params},
                "required": ["input"],
                "additionalProperties": False,
            }

        return {
            "type": "function",
            "integration_id": integration_id,
            "x-integration-id": integration_id,
            "x-mcp-tool-name": raw_name,
            "x-mcp-server-name": server_name,
            "function": {
                "name": fn_name,
                "description": description,
                "parameters": params,
            },
        }

    def _sanitize_tool_name(self, name: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        return cleaned[:64] if cleaned else "tool"

    def _dedupe_by_function_name(self, tools: list[dict]) -> list[dict]:
        seen = set()
        out = []
        for tool in tools:
            fn = tool.get("function") if isinstance(tool, dict) else None
            if not isinstance(fn, dict):
                continue
            name = str(fn.get("name", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(tool)
        return out
