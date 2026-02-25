import asyncio
import json
import os
import sys
import aiohttp
from typing import Dict, Any, List

SERP_API_KEY = os.getenv("SERPAPI_KEY", "").strip()
REQUEST_TIMEOUT = 15
MAX_RESULTS = 6


# -----------------------------
# Utility: safe stdout response
# -----------------------------
def send_response(req_id: int, result: Any = None, error: str = None):
    if error:
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"message": error}
        }
    else:
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result
        }

    print(json.dumps(payload), flush=True)


# -----------------------------
# SerpAPI Query
# -----------------------------
async def perform_search(query: str, num_results: int = MAX_RESULTS) -> Dict:
    if not SERP_API_KEY:
        raise RuntimeError("SERPAPI_KEY not configured")

    url = "https://serpapi.com/search.json"

    params = {
        "engine": "google",
        "q": query,
        "api_key": SERP_API_KEY,
        "num": min(num_results, MAX_RESULTS),
        "safe": "active"
    }

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                raise RuntimeError(f"SerpAPI error HTTP {resp.status}")

            data = await resp.json()

    # Token-optimized extraction
    results: List[Dict] = []
    for item in data.get("organic_results", [])[:num_results]:
        results.append({
            "title": item.get("title"),
            "url": item.get("link"),
            "snippet": item.get("snippet")
        })

    return {
        "query": query,
        "results": results
    }


# -----------------------------
# MCP Tool Handlers
# -----------------------------
async def handle_initialize(req_id: int):
    send_response(req_id, {})


async def handle_tools_list(req_id: int):
    send_response(req_id, {
        "tools": [
            {
                "name": "web_search",
                "description": "Search the web using SerpAPI Google search",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query"
                        },
                        "num_results": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_RESULTS,
                            "default": MAX_RESULTS
                        }
                    },
                    "required": ["query"]
                }
            }
        ]
    })


async def handle_tools_call(req_id: int, params: Dict):
    try:
        name = params.get("name")
        args = params.get("arguments", {})

        if name != "web_search":
            raise RuntimeError(f"Unknown tool: {name}")

        query = args.get("query", "").strip()
        if not query:
            raise RuntimeError("Query cannot be empty")

        num_results = int(args.get("num_results", MAX_RESULTS))

        result = await perform_search(query, num_results)
        send_response(req_id, result)

    except Exception as e:
        send_response(req_id, error=str(e))


# -----------------------------
# Main JSON-RPC Loop
# -----------------------------
async def main():
    loop = asyncio.get_event_loop()

    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break

        try:
            req = json.loads(line)
            req_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})

            if method == "initialize":
                await handle_initialize(req_id)

            elif method == "tools/list":
                await handle_tools_list(req_id)

            elif method == "tools/call":
                await handle_tools_call(req_id, params)

            else:
                send_response(req_id, error=f"Unknown method: {method}")

        except Exception as e:
            print(json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"message": str(e)}
            }), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
