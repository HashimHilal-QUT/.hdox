from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from zipfile import ZipFile

from .core import HDOXError


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.in_script = False
        self.ldjson: list[dict] = []
        self._json_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("main", "article", "section", "header", "nav", "table", "figure"):
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("\n" + "#" * int(tag[1]) + " ")
        if tag in ("p", "li", "figcaption"):
            self.parts.append("\n")
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self.in_script = True
            self._json_parts = []
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("main", "article", "section", "header", "nav", "table", "figure", "p", "li"):
            self.parts.append("\n")
        if tag == "script" and self.in_script:
            self.in_script = False
            try:
                value = json.loads("".join(self._json_parts))
                if isinstance(value, dict):
                    self.ldjson.append(value)
                elif isinstance(value, list):
                    self.ldjson.extend(v for v in value if isinstance(v, dict))
            except json.JSONDecodeError:
                pass

    def handle_data(self, data):
        if self.in_script:
            self._json_parts.append(data)
        else:
            self.parts.append(data)


def extract(source: str | Path) -> tuple[dict, str, list[dict]]:
    with ZipFile(source, "r") as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        html = zf.read(manifest.get("entrypoint", "index.html")).decode("utf-8")
    parser = _TextParser()
    parser.feed(html)
    text = re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()
    return manifest, text, parser.ldjson


def to_markdown(source: str | Path) -> str:
    manifest, text, ldjson = extract(source)
    lines = [
        "---",
        f"title: {json.dumps(manifest.get('title', ''))}",
        f"authors: {json.dumps(manifest.get('authors', []))}",
        f"language: {json.dumps(manifest.get('language', 'en'))}",
        "---",
        "",
        text,
    ]
    return "\n".join(lines).strip() + "\n"


def to_llm_context(source: str | Path) -> str:
    manifest, text, ldjson = extract(source)
    return json.dumps({
        "manifest": manifest,
        "markdown": text,
        "json_ld": ldjson,
    }, ensure_ascii=False, indent=2)


def chunk_markdown(source: str | Path, max_chars: int = 4000) -> list[str]:
    markdown = to_markdown(source)
    return [markdown[i:i + max_chars] for i in range(0, len(markdown), max_chars)]
