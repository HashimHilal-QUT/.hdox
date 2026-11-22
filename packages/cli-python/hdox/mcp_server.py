from __future__ import annotations

import json
import sys

from .core import pack, validate
from .llm import to_llm_context


def serve() -> None:
    tools = {
        "read_hdox": "Read an HDOX archive as Markdown and JSON-LD context",
        "create_hdox": "Create an HDOX archive from a project directory",
        "edit_hdox_section": "Reserved section-editing operation",
        "validate_hdox": "Validate an HDOX archive",
    }
    for line in sys.stdin:
        request = json.loads(line)
        method = request.get("method")
        result = {}
        if method == "tools/list":
            result = {"tools": [{"name": name, "description": description} for name, description in tools.items()]}
        elif method == "tools/call":
            params = request.get("params", {})
            name = params.get("name")
            arguments = params.get("arguments", {})
            try:
                if name == "read_hdox":
                    output = to_llm_context(arguments["file"])
                elif name == "create_hdox":
                    output = str(pack(arguments["dir"], arguments["output"]))
                elif name == "validate_hdox":
                    vr = validate(arguments["file"])
                    output = {"valid": vr.valid, "errors": vr.errors}
                else:
                    output = {"error": "unsupported operation"}
                result = {"content": [{"type": "text", "text": json.dumps(output) if not isinstance(output, str) else output}]}
            except Exception as exc:
                result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        response = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
