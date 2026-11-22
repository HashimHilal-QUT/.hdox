from __future__ import annotations

import json
import sys

from .core import pack, validate
from .llm import to_llm_context, to_markdown

PROTOCOL_VERSION = "2024-11-05"

_FILE = {"type": "object", "properties": {"file": {"type": "string", "description": "Path to a .hdox file"}},
         "required": ["file"]}
TOOLS = {
    "read_hdox": ("Read an HDOX archive as Markdown plus JSON-LD and manifest context", _FILE),
    "read_hdox_markdown": ("Read an HDOX archive as Markdown only", _FILE),
    "validate_hdox": ("Validate an HDOX archive", _FILE),
    "create_hdox": ("Pack a project directory into an HDOX archive", {
        "type": "object",
        "properties": {"dir": {"type": "string"}, "output": {"type": "string"}},
        "required": ["dir", "output"]}),
}


def _call(name: str, args: dict) -> str:
    if name == "read_hdox":
        return to_llm_context(args["file"])
    if name == "read_hdox_markdown":
        return to_markdown(args["file"])
    if name == "create_hdox":
        return str(pack(args["dir"], args["output"]))
    if name == "validate_hdox":
        r = validate(args["file"])
        return json.dumps({"valid": r.valid, "errors": r.errors, "warnings": r.warnings})
    raise ValueError(f"unknown tool: {name}")


def handle(request: dict) -> dict | None:
    """Handle one JSON-RPC message. Returns None for notifications."""
    method = request.get("method")
    rid = request.get("id")
    if rid is None:  # notification: never respond
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "hdox", "version": "0.1.0"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": n, "description": d, "inputSchema": s} for n, (d, s) in TOOLS.items()]})
    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        if name not in TOOLS:
            return err(-32602, f"unknown tool: {name}")
        try:
            text = _call(name, params.get("arguments") or {})
            return ok({"content": [{"type": "text", "text": text}]})
        except KeyError as exc:
            return ok({"content": [{"type": "text", "text": f"missing argument: {exc}"}], "isError": True})
        except Exception as exc:  # noqa: BLE001 - tool errors are reported in-band per MCP
            return ok({"content": [{"type": "text", "text": str(exc)}], "isError": True})
    return err(-32601, f"method not found: {method}")


def serve() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
        except ValueError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            response = handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
