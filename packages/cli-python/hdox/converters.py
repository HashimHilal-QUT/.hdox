from __future__ import annotations

import base64
import html as htmllib
import io
import mimetypes
import posixpath
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote
from zipfile import ZipFile

from .core import FORMAT_VERSION, HDOXError, _default_manifest, _html_text, pack, unpack
from .llm import EMBEDDED_NAME

_DEFAULT_CSS = """@page { size: A4; margin: 20mm; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; line-height: 1.5; max-width: 48rem; margin: 0 auto; padding: 1rem; }
h1, h2, h3 { break-after: avoid; }
table { border-collapse: collapse; }
th, td { border: 1px solid #bbb; padding: .3rem .6rem; }
table, figure, pre { break-inside: avoid; }
pre { background: #f5f5f5; padding: .75rem; overflow: auto; }
img { max-width: 100%; }
@media print { body { max-width: none; padding: 0; } }
"""


# --------------------------------------------------------------------------- Markdown -> HDOX

def _split_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"\A---[ \t]*\r?\n(.*?\r?\n)?---[ \t]*(?:\r?\n|\Z)", text, flags=re.S)
    if not m:
        return {}, text
    import yaml
    try:
        meta = yaml.safe_load(m.group(1) or "") or {}
    except yaml.YAMLError as exc:
        raise HDOXError(f"invalid YAML front matter: {exc}") from exc
    if not isinstance(meta, dict):
        raise HDOXError("front matter must be a YAML mapping")
    return meta, text[m.end():]


def _as_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        return [str(value)]
    return [str(v) for v in value]


def from_markdown(input_md: str | Path, output: str | Path) -> Path:
    import markdown

    source = Path(input_md)
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise HDOXError(f"cannot read {source}: {exc}") from exc
    meta, body = _split_frontmatter(text)

    title = str(meta.get("title") or "").strip()
    if not title:
        h1 = re.search(r"^#\s+(.+?)\s*#*\s*$", body, flags=re.M)
        title = h1.group(1) if h1 else source.stem
    language = str(meta.get("language") or meta.get("lang") or "en")
    body_html = markdown.markdown(
        body, extensions=["tables", "fenced_code", "footnotes", "toc", "sane_lists", "attr_list"])
    has_h1 = re.search(r"<h1[\s>]", body_html) is not None
    header = "" if has_h1 else f"<header><h1>{htmllib.escape(title)}</h1></header>\n"
    page = (
        f'<!doctype html>\n<html lang="{htmllib.escape(language, quote=True)}">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{htmllib.escape(title)}</title>\n"
        '<link rel="stylesheet" href="styles/paged.css">\n</head>\n'
        f"<body>\n<main>\n<article>\n{header}{body_html}\n</article>\n</main>\n</body>\n</html>\n"
    )

    manifest = _default_manifest(title, _html_text(page.split("</head>", 1)[1]), language)
    manifest["authors"] = _as_str_list(meta.get("authors") or meta.get("author"))
    manifest["ai_metadata"]["keywords"] = _as_str_list(meta.get("keywords"))
    if meta.get("summary") or meta.get("description"):
        manifest["ai_metadata"]["summary"] = str(meta.get("summary") or meta.get("description"))
    reserved = {
        "$schema", "hdox_version", "id", "title", "authors", "author", "created_at",
        "modified_at", "language", "lang", "entrypoint", "page_setup", "security",
        "ai_metadata", "keywords", "summary", "description",
    }
    for key, value in meta.items():
        if key not in reserved:
            manifest[key] = value

    import json
    with TemporaryDirectory() as tmp:
        project = Path(tmp)
        (project / "styles").mkdir()
        (project / "styles" / "paged.css").write_text(_DEFAULT_CSS, encoding="utf-8")
        (project / "index.html").write_text(page, encoding="utf-8")
        (project / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
        # bundle relative images referenced by the Markdown
        for ref in set(re.findall(r'<img[^>]+src="([^"]+)"', body_html)):
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^/|^\.\.", ref):
                continue
            asset = (source.parent / unquote(ref)).resolve()
            if asset.is_file() and source.parent.resolve() in asset.parents:
                dest = project / unquote(ref)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(asset, dest)
        return pack(project, output)


# --------------------------------------------------------------------------- HDOX -> single HTML

def to_html(source: str | Path, output: str | Path) -> Path:
    """Export a single self-contained .html file (CSS and images inlined).

    The result opens in any browser on any OS with no HDOX tooling at all.
    """
    with ZipFile(source, "r") as zf:
        import json
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        entry = manifest.get("entrypoint", "index.html")
        files = {n: zf.read(n) for n in zf.namelist() if not n.endswith("/")}
    if entry not in files:
        raise HDOXError(f"entrypoint not found: {entry}")

    def data_uri(name: str) -> str | None:
        blob = files.get(name)
        if blob is None:
            return None
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"

    def resolve(ref: str, base: str) -> str:
        return posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(ref.split("#")[0].split("?")[0])))

    def inline_css(css: str, base: str) -> str:
        def repl(m):
            ref = m.group(2)
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^//|^#", ref):
                return m.group(0)
            uri = data_uri(resolve(ref, base))
            return f"url({uri})" if uri else m.group(0)
        return re.sub(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", repl, css)

    html = files[entry].decode("utf-8", errors="replace")

    def link_repl(m):
        tag = m.group(0)
        href = re.search(r'href\s*=\s*"([^"]+)"', tag)
        if href and re.search(r'rel\s*=\s*"?stylesheet', tag, re.I):
            target = resolve(href.group(1), entry)
            if target in files:
                css = inline_css(files[target].decode("utf-8", errors="replace"), target)
                return f"<style>\n{css.replace('</style', '<\\/style')}\n</style>"
        return tag

    html = re.sub(r"<link\b[^>]*>", link_repl, html, flags=re.I)

    def src_repl(m):
        ref = m.group(2)
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^//|^#", ref):
            return m.group(0)
        uri = data_uri(resolve(ref, entry))
        return f'{m.group(1)}"{uri}"' if uri else m.group(0)

    html = re.sub(r'(<(?:img|source|video|audio)\b[^>]*?\bsrc\s*=\s*)"([^"]+)"', src_repl, html, flags=re.I)
    html = re.sub(r'(<img\b[^>]*?\bsrc\s*=\s*)\'([^\']+)\'', lambda m: src_repl(m), html, flags=re.I)
    # embed the manifest so AI agents reading the bare HTML still get the metadata
    meta = json.dumps({"title": manifest.get("title"), "authors": manifest.get("authors"),
                       "ai_metadata": manifest.get("ai_metadata")}, ensure_ascii=False).replace("</", "<\\/")
    tag = f'<script type="application/json" id="hdox-manifest">{meta}</script>'
    html = re.sub(r"</head>", tag + "\n</head>", html, count=1, flags=re.I) if re.search(r"</head>", html, re.I) \
        else tag + html
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


# --------------------------------------------------------------------------- HDOX -> PDF

def _render_pdf(root: Path, out: Path) -> None:
    try:
        from weasyprint import HTML
    except ImportError:
        HTML = None
    if HTML is not None:
        HTML(filename=str(root / "index.html"), base_url=str(root)).write_pdf(str(out))
        return
    browser = next((p for p in (shutil.which(n) for n in
                                ("chromium", "chromium-browser", "google-chrome", "chrome", "msedge")) if p), None)
    if not browser:
        raise HDOXError("PDF export needs WeasyPrint (pip install 'hdox[pdf]') or a Chromium/Chrome/Edge executable")
    with TemporaryDirectory() as profile:
        try:
            subprocess.run(
                [browser, "--headless", "--disable-gpu", "--no-sandbox", f"--user-data-dir={profile}",
                 "--no-pdf-header-footer", f"--print-to-pdf={out}", (root / "index.html").as_uri()],
                check=True, capture_output=True, timeout=120)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise HDOXError(f"headless browser failed to render the PDF: {exc}") from exc


def to_pdf(source: str | Path, output: str | Path, embed: bool = False) -> Path:
    """Render to PDF. With ``embed=True`` the .hdox source is attached inside the PDF,
    so the PDF stays a normal viewable PDF while AI agents can recover the semantic HTML
    (``hdox llm-read file.pdf``)."""
    src = Path(source)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "doc"
        unpack(src, root)
        import json
        entry = json.loads((root / "manifest.json").read_text(encoding="utf-8")).get("entrypoint", "index.html")
        if entry != "index.html":
            shutil.copyfile(root / entry, root / "index.html") if not (root / "index.html").exists() else None
        rendered = Path(tmp) / "rendered.pdf"
        _render_pdf(root, rendered)
        if not embed:
            shutil.copyfile(rendered, out)
            return out
        try:
            from pypdf import PdfReader, PdfWriter
        except ImportError as exc:
            raise HDOXError("--embed requires pypdf: pip install 'hdox[pdf]'") from exc
        writer = PdfWriter(clone_from=PdfReader(str(rendered)))
        writer.add_attachment(EMBEDDED_NAME, src.read_bytes())
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        info = {"/Title": str(manifest.get("title", "")), "/Author": ", ".join(manifest.get("authors", [])),
                "/Keywords": ", ".join((manifest.get("ai_metadata") or {}).get("keywords", [])),
                "/Producer": f"hdox {FORMAT_VERSION}"}
        writer.add_metadata({k: v for k, v in info.items() if v})
        buf = io.BytesIO()
        writer.write(buf)
        out.write_bytes(buf.getvalue())
    return out


# --------------------------------------------------------------------------- build (LaTeX-style one-shot)

def build(input_path: str | Path, output: str | Path, embed: bool = True) -> Path:
    """One command from source to artifact, by output extension: .hdox, .pdf or .html.

    Source may be a Markdown file, an HTML-project directory, or an existing .hdox.
    """
    src = Path(input_path)
    out = Path(output)
    ext = out.suffix.lower()
    if ext not in (".hdox", ".pdf", ".html"):
        raise HDOXError("output must end in .hdox, .pdf or .html")
    with TemporaryDirectory() as tmp:
        if src.is_dir():
            archive = pack(src, Path(tmp) / "doc.hdox")
        elif src.suffix.lower() in (".md", ".markdown"):
            archive = from_markdown(src, Path(tmp) / "doc.hdox")
        elif src.suffix.lower() == ".hdox":
            archive = src
        else:
            raise HDOXError("input must be a directory, a Markdown file, or a .hdox file")
        if ext == ".hdox":
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(archive, out)
        elif ext == ".pdf":
            to_pdf(archive, out, embed=embed)
        else:
            to_html(archive, out)
    return out
