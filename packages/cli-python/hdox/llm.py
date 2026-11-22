from __future__ import annotations

import io
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .core import HDOXError

EMBEDDED_NAME = "source.hdox"  # attachment name used when a PDF carries its HDOX source


def open_archive(source: str | Path) -> ZipFile:
    """Open a .hdox file, or a PDF that carries an embedded .hdox source attachment."""
    path = Path(source)
    try:
        head = path.read_bytes()[:5]
    except OSError as exc:
        raise HDOXError(f"cannot read {path}: {exc}") from exc
    if head == b"%PDF-":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise HDOXError("reading PDFs requires pypdf: pip install 'hdox[pdf]'") from exc
        reader = PdfReader(str(path))
        for name, blobs in reader.attachments.items():
            if name.lower().endswith(".hdox") and blobs:
                return ZipFile(io.BytesIO(blobs[0]))
        raise HDOXError("PDF has no embedded .hdox source (create it with `hdox to-pdf --embed`)")
    try:
        return ZipFile(path, "r")
    except BadZipFile as exc:
        raise HDOXError(f"not a valid .hdox archive: {exc}") from exc


class _MarkdownParser(HTMLParser):
    """Convert semantic HTML into compact Markdown suitable for LLM ingestion."""

    _SKIP = {"script", "style", "head", "template", "noscript", "svg"}
    _BLOCK = {"p", "div", "section", "article", "main", "header", "footer", "nav",
              "aside", "figure", "figcaption", "address", "details", "summary", "dl", "dt", "dd"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.ldjson: list[dict] = []
        self._skip = 0
        self._ld: list[str] | None = None
        self._lists: list[list] = []  # [ordered?, counter]
        self._href: list[str | None] = []
        self._pre = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._table: list[list[str]] = []
        self._quote = 0

    # -- output helpers
    def _w(self, text: str) -> None:
        if self._cell is not None:
            self._cell.append(text)
        else:
            self.out.append(text)

    def _block(self) -> None:
        if self._cell is None:
            self.out.append("\n\n")

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "script":
            if a.get("type", "").lower() == "application/ld+json":
                self._ld = []
            else:
                self._skip += 1
            return
        if tag in self._SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._block(); self._w("#" * int(tag[1]) + " ")
        elif tag in self._BLOCK:
            self._block()
        elif tag in ("ul", "ol"):
            self._block() if not self._lists else self._w("\n")
            self._lists.append([tag == "ol", int(a.get("start", "1") or 1) if tag == "ol" else 0])
        elif tag == "li":
            indent = "  " * max(0, len(self._lists) - 1)
            if self._lists and self._lists[-1][0]:
                marker = f"{self._lists[-1][1]}. "
                self._lists[-1][1] += 1
            else:
                marker = "- "
            self._w(f"\n{indent}{marker}")
        elif tag == "br":
            self._w("\n")
        elif tag == "hr":
            self._block(); self._w("---"); self._block()
        elif tag == "blockquote":
            self._block(); self._quote += 1; self._w("> ")
        elif tag == "pre":
            self._block(); self._pre += 1; self._w("```\n")
        elif tag == "code" and not self._pre:
            self._w("`")
        elif tag in ("strong", "b"):
            self._w("**")
        elif tag in ("em", "i"):
            self._w("*")
        elif tag == "a":
            self._href.append(a.get("href") or None)
            self._w("[")
        elif tag == "img":
            alt = a.get("alt", "").strip()
            src = a.get("src", "")
            if src and not src.startswith("data:"):
                self._w(f"![{alt}]({src})")
            elif alt:
                self._w(f"[image: {alt}]")
        elif tag == "table":
            self._block(); self._table = []
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "script" and self._ld is not None:
            try:
                value = json.loads("".join(self._ld))
                self.ldjson.extend([value] if isinstance(value, dict) else [v for v in value if isinstance(v, dict)])
            except (json.JSONDecodeError, TypeError):
                pass
            self._ld = None
            return
        if tag in self._SKIP or tag == "script":
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") or tag in self._BLOCK:
            self._block()
        elif tag in ("ul", "ol"):
            if self._lists:
                self._lists.pop()
            self._block()
        elif tag == "blockquote":
            self._quote = max(0, self._quote - 1); self._block()
        elif tag == "pre":
            self._pre = max(0, self._pre - 1)
            if self.out and not self.out[-1].endswith("\n"):
                self._w("\n")
            self._w("```"); self._block()
        elif tag == "code" and not self._pre:
            self._w("`")
        elif tag in ("strong", "b"):
            self._w("**")
        elif tag in ("em", "i"):
            self._w("*")
        elif tag == "a":
            href = self._href.pop() if self._href else None
            self._w(f"]({href})" if href else "]")
        elif tag in ("td", "th"):
            if self._cell is not None and self._row is not None:
                self._row.append(" ".join("".join(self._cell).split()).replace("|", "\\|"))
            self._cell = None
        elif tag == "tr":
            if self._row is not None:
                self._table.append(self._row)
            self._row = None
        elif tag == "table":
            self._flush_table()

    def _flush_table(self) -> None:
        rows = [r for r in self._table if r]
        self._table = []
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        self.out.append("\n".join(lines))
        self._block()

    def handle_data(self, data):
        if self._ld is not None:
            self._ld.append(data)
            return
        if self._skip:
            return
        if self._pre:
            self._w(data)
        else:
            text = re.sub(r"\s+", " ", data)
            if text.strip() or (self.out and not self.out[-1].endswith(("\n", " "))):
                self._w(text)

    def markdown(self) -> str:
        text = "".join(self.out)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def extract(source: str | Path) -> tuple[dict, str, list[dict]]:
    """Return (manifest, markdown body, JSON-LD objects) for a .hdox (or hybrid PDF)."""
    with open_archive(source) as zf:
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except KeyError as exc:
            raise HDOXError("archive has no manifest.json") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HDOXError(f"invalid manifest.json: {exc}") from exc
        entry = manifest.get("entrypoint", "index.html")
        try:
            html = zf.read(entry).decode("utf-8", errors="replace")
        except KeyError as exc:
            raise HDOXError(f"entrypoint not found: {entry}") from exc
    parser = _MarkdownParser()
    parser.feed(html)
    parser.close()
    return manifest, parser.markdown(), parser.ldjson


def to_markdown(source: str | Path) -> str:
    manifest, text, _ = extract(source)
    meta = {}
    reserved = {
        "$schema", "hdox_version", "id", "created_at", "modified_at", "entrypoint",
        "page_setup", "security", "ai_metadata",
    }
    for key, value in manifest.items():
        if key not in reserved:
            meta[key] = value

    meta.setdefault("title", manifest.get("title", ""))
    meta.setdefault("authors", manifest.get("authors", []))
    meta.setdefault("language", manifest.get("language", "en"))
    ai_metadata = manifest.get("ai_metadata") or {}
    if ai_metadata.get("keywords"):
        meta.setdefault("keywords", ai_metadata["keywords"])
    if ai_metadata.get("summary"):
        meta.setdefault("summary", ai_metadata["summary"])

    front = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items())
    return f"---\n{front}\n---\n\n{text}\n"


def to_llm_context(source: str | Path) -> str:
    manifest, text, ldjson = extract(source)
    return json.dumps({"manifest": manifest, "markdown": text, "json_ld": ldjson},
                      ensure_ascii=False, indent=2)


def chunk_markdown(source: str | Path, max_chars: int = 4000) -> list[str]:
    """Split on paragraph boundaries so chunks never cut a sentence block in half."""
    _, text, _ = extract(source)
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        while len(para) > max_chars:  # a single oversized block: hard split
            if current:
                chunks.append(current); current = ""
            chunks.append(para[:max_chars]); para = para[max_chars:]
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current); current = ""
        current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks
