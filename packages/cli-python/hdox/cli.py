from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import generate_keypair, init, pack, sign, unpack, validate, verify


def _report(result) -> int:
    payload = {"valid": result.valid, "errors": result.errors}
    if getattr(result, "warnings", None):
        payload["warnings"] = result.warnings
    print(json.dumps(payload, indent=2))
    return 0 if result.valid else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hdox", description="Tools for the .hdox portable semantic document format")
    parser.add_argument("--version", action="version", version=f"hdox {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, help_):
        return sub.add_parser(name, help=help_)

    p = add("init", "create a new document project"); p.add_argument("dir")
    p = add("pack", "pack a project directory into .hdox"); p.add_argument("dir"); p.add_argument("-o", "--output", required=True)
    p = add("unpack", "safely extract a .hdox"); p.add_argument("file"); p.add_argument("-o", "--output", required=True)
    p = add("validate", "validate container, manifest and links"); p.add_argument("file")
    p = add("llm-read", "extract Markdown / JSON context for AI (accepts .hdox or hybrid PDF)")
    p.add_argument("file"); p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p = add("from-md", "convert Markdown to .hdox"); p.add_argument("input"); p.add_argument("-o", "--output", required=True)
    p = add("to-pdf", "export to PDF"); p.add_argument("file"); p.add_argument("-o", "--output", required=True)
    p.add_argument("--embed", action="store_true", help="attach the .hdox source inside the PDF for AI round-tripping")
    p = add("to-html", "export a single self-contained .html file"); p.add_argument("file"); p.add_argument("-o", "--output", required=True)
    p = add("build", "one-shot build: Markdown | project dir | .hdox -> .hdox | .pdf | .html")
    p.add_argument("input"); p.add_argument("-o", "--output", required=True)
    p.add_argument("--no-embed", action="store_true", help="for .pdf output: do not attach the .hdox source")
    p = add("keygen", "generate an Ed25519 signing key"); p.add_argument("--private", required=True); p.add_argument("--public")
    p = add("sign", "sign a .hdox with an Ed25519 private key"); p.add_argument("file"); p.add_argument("--key", required=True)
    p = add("verify", "verify a signature"); p.add_argument("file"); p.add_argument("--public-key", help="hex public key to pin")
    add("mcp", "start the MCP server over stdio")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        c = args.command
        if c == "init":
            init(args.dir)
        elif c == "pack":
            pack(args.dir, args.output)
        elif c == "unpack":
            unpack(args.file, args.output)
        elif c == "validate":
            return _report(validate(args.file))
        elif c == "llm-read":
            from .llm import to_llm_context, to_markdown
            sys.stdout.write(to_markdown(args.file) if args.format == "markdown" else to_llm_context(args.file) + "\n")
        elif c == "from-md":
            from .converters import from_markdown
            from_markdown(args.input, args.output)
        elif c == "to-pdf":
            from .converters import to_pdf
            to_pdf(args.file, args.output, embed=args.embed)
        elif c == "to-html":
            from .converters import to_html
            to_html(args.file, args.output)
        elif c == "build":
            from .converters import build
            build(args.input, args.output, embed=not args.no_embed)
        elif c == "keygen":
            print(generate_keypair(args.private, args.public))
        elif c == "sign":
            sign(args.file, args.key)
        elif c == "verify":
            return _report(verify(args.file, args.public_key))
        elif c == "mcp":
            from .mcp_server import serve
            serve()
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary: report, never traceback
        print(f"hdox: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
