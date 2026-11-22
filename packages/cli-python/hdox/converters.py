from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

import markdown

from .core import pack
from zipfile import ZipFile
from tempfile import TemporaryDirectory


def to_pdf(source: str | Path, output: str | Path) -> Path:
    src = Path(source)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        from weasyprint import HTML
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with ZipFile(src, "r") as zf:
                zf.extractall(root)
            HTML(filename=str(root / "index.html"), base_url=str(root)).write_pdf(out)
        return out
    except ImportError:
        pass
    browser = next((shutil.which(name) for name in ("chromium", "chromium-browser", "google-chrome") if shutil.which(name)), None)
    if not browser:
        raise RuntimeError("PDF conversion requires WeasyPrint or a headless Chromium executable")
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        with ZipFile(src, "r") as zf:
            zf.extractall(root)
        subprocess.run([
            browser, "--headless", "--disable-gpu", "--no-sandbox",
            "--allow-file-access-from-files", "--print-to-pdf=" + str(out),
            str(root / "index.html"),
        ], check=True)
    return out


def from_markdown(input_md: str | Path, output: str | Path) -> Path:
    source = Path(input_md)
    text = source.read_text(encoding="utf-8")
    frontmatter: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                import yaml
                frontmatter = yaml.safe_load(parts[1]) or {}
            except ImportError:
                frontmatter = {}
            body = parts[2].lstrip("\n")

    title = str(frontmatter.get("title", source.stem))
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = {
        "$schema": "https://hdox.org/schemas/v0.1/manifest.schema.json",
        "hdox_version": "0.1.0",
        "id": f"urn:uuid:{uuid.uuid4()}",
        "title": title,
        "authors": frontmatter.get("authors", []),
        "created_at": now,
        "modified_at": now,
        "language": str(frontmatter.get("language", "en")),
        "entrypoint": "index.html",
        "page_setup": {"size": "A4", "orientation": "portrait", "margins": "20mm"},
        "security": {"allow_scripts": False, "allow_external_network": False, "signed": False},
        "ai_metadata": {
            "summary": body[:500].replace("\n", " "),
            "keywords": frontmatter.get("keywords", []),
            "reading_order": ["index.html"],
            "token_estimate": len(body.split()),
        },
    }
    project = Path(output).with_suffix(".project")
    project.mkdir(parents=True, exist_ok=True)
    (project / "styles").mkdir(exist_ok=True)
    (project / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (project / "styles" / "paged.css").write_text(
        "@page { size: A4; margin: 20mm; }\nmain, article, section { break-inside: avoid; }\n",
        encoding="utf-8",
    )
    html_body = markdown.markdown(body, extensions=["tables", "fenced_code"])
    (project / "index.html").write_text(
        '<!doctype html>\n<html lang="' + manifest["language"] + '"><head><meta charset="utf-8">'
        '<title>' + title + '</title><link rel="stylesheet" href="styles/paged.css"></head>'
        '<body><main><article><header><h1>' + title + '</h1></header>' + html_body + '</article></main></body></html>\n',
        encoding="utf-8",
    )
    result = pack(project, output)
    import shutil
    shutil.rmtree(project)
    return result
