from __future__ import annotations

import argparse
import json
import sys

from .core import init, pack, unpack, validate, sign, verify
from .llm import to_markdown, to_llm_context
from .converters import from_markdown
from .converters import to_pdf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hdox")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init"); p.add_argument("dir")
    p = sub.add_parser("pack"); p.add_argument("dir"); p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("unpack"); p.add_argument("file"); p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("validate"); p.add_argument("file")
    p = sub.add_parser("llm-read"); p.add_argument("file"); p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p = sub.add_parser("from-md"); p.add_argument("input"); p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("to-pdf"); p.add_argument("file"); p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("sign"); p.add_argument("file"); p.add_argument("--key", required=True)
    p = sub.add_parser("verify"); p.add_argument("file")
    p = sub.add_parser("mcp")

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init(args.dir)
        elif args.command == "pack":
            pack(args.dir, args.output)
        elif args.command == "unpack":
            unpack(args.file, args.output)
        elif args.command == "validate":
            result = validate(args.file)
            print(json.dumps({"valid": result.valid, "errors": result.errors}))
            return 0 if result.valid else 1
        elif args.command == "llm-read":
            sys.stdout.write(to_markdown(args.file) if args.format == "markdown" else to_llm_context(args.file))
        elif args.command == "from-md":
            from_markdown(args.input, args.output)
        elif args.command == "to-pdf":
            to_pdf(args.file, args.output)
        elif args.command == "sign":
            sign(args.file, args.key)
        elif args.command == "verify":
            result = verify(args.file)
            print(json.dumps({"valid": result.valid, "errors": result.errors}))
            return 0 if result.valid else 1
        elif args.command == "mcp":
            from .mcp_server import serve
            serve()
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
