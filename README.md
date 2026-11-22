# .hdox

**One file that is a PDF for people and HTML for machines.**

`.hdox` is an open, offline-first document format. A document is a small project of plain text
(HTML + CSS + a JSON manifest) – you write it like code, diff it in Git, generate it from scripts – and the
format packs it into a single portable file that renders the same everywhere, prints like a PDF, and gives
AI agents the clean semantic source instead of a pile of positioned glyphs.

> **Status:** v1.0.0 reference implementation · MIT licensed · contributions welcome – see [Contribute](#contribute).

**Why does this exist?** PDFs are great to read and terrible to parse: LLMs and scrapers get scrambled text, lost tables
and no structure. HTML is great to parse but isn't a single, printable, signable file. `.hdox` is a thin, open
container that keeps the HTML as the source of truth and treats PDF as just one rendering of it.

```python
from hdox import to_markdown, validate

assert validate("report.hdox").valid
print(to_markdown("report.hdox"))      # headings, tables, lists – intact, ready for your LLM / RAG pipeline
```

| | PDF | HTML | **.hdox** |
| --- | :---: | :---: | :---: |
| Single portable file | ✅ | ❌ (loose assets) | ✅ |
| Fixed page layout / print | ✅ | ⚠️ | ✅ (CSS Paged Media) |
| Source is text / diffable / code-native | ❌ | ✅ | ✅ |
| Clean structure for LLMs (headings, tables, lists) | ❌ lossy extraction | ✅ | ✅ |
| Safe by default (no scripts, no network) | ⚠️ | ❌ | ✅ |
| Signable, tamper-evident | ✅ | ❌ | ✅ (Ed25519) |
| Opens with no special software | ✅ | ✅ | ✅ via `to-html` / `to-pdf` |

## How it works

```text
 write                       build                         everyone gets what they need
┌──────────────┐   hdox    ┌──────────────┐   ┌─ starter-report.pdf   universal viewing, printing
│ HTML + CSS  │ ───────▶  │ starter-report│ ──┼─ starter-report.html  one file, opens in any browser
│ rich sample  │           │ .hdox (ZIP) │   └─ llm-read             Markdown + JSON-LD for AI agents
└──────────────┘           └──────────────┘
```

A `.hdox` is a ZIP with a `mimetype` marker, a `manifest.json`, and an HTML entrypoint:

```text
report.hdox
├── mimetype          application/vnd.hdox+zip (first entry, uncompressed)
├── manifest.json     title, authors, page setup, security, AI metadata
├── index.html        the document – semantic HTML5
├── styles/paged.css  @page rules for print / PDF layout
└── assets/…          images, fonts (referenced by relative path)
```

**Hybrid PDF.** `hdox to-pdf --embed` renders a normal PDF and attaches the `.hdox` source inside it. Every PDF viewer
opens it; `hdox llm-read report.pdf` pulls the structured HTML back out. PDF for portability, HTML for AI – in one file.

## Install

Requires Python 3.9 or newer. The following setup installs the core package, PDF renderer,
PDF attachment support, and the rich starter-report dependencies in an isolated virtual environment.

### Linux

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv libpango-1.0-0 libpangocairo-1.0-0 libcairo2
cd /path/to/HDOX
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
cd packages/cli-python
python -m pip install -e ".[pdf,dev]"
cd ../..
```

Fedora:

```bash
sudo dnf install -y python3 python3-pip pango cairo
cd /path/to/HDOX
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "./packages/cli-python[pdf,dev]"
```

### macOS

Install Python and Pango, then install HDOX in a virtual environment:

```bash
brew install python pango cairo
cd /path/to/HDOX
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "./packages/cli-python[pdf,dev]"
```

If Homebrew is not already installed, install it first from <https://brew.sh/>.

### Windows (PowerShell)

Install Python 3.9+ and the GTK3 runtime, then restart PowerShell and run:

```powershell
winget install --id Python.Python.3.12 -e
winget install --id GtkD.GtkPlusRuntime.x64 -e --source winget

# Restart PowerShell after installing either package.
cd C:\path\to\HDOX
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".\packages\cli-python[pdf,dev]"
```

If PowerShell blocks virtual-environment activation:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

### Verify every dependency

Run the same verification on Linux, macOS, and Windows:

```text
python -c "import sys, markdown, yaml, jsonschema, cryptography, weasyprint, pypdf; print(sys.executable); print('dependencies ready')"
python -m pip show hdox weasyprint pypdf
hdox --version
```

Always use `python -m pip` inside the active virtual environment. This ensures packages are
installed for the same Python interpreter used to launch `hdox`.

## Cross-platform universal test

The repository includes a complete rich HTML/CSS sample at
[`examples/starter-report`](examples/starter-report). It contains a colorful cover,
an SVG chart, metrics, regional tables, print styling, and system-font typography.
Build it on Windows, Linux, or macOS and compare the generated formats.

### Linux and macOS

```bash
source .venv/bin/activate

hdox build examples/starter-report -o examples/starter-report/starter-report.hdox
hdox build examples/starter-report -o examples/starter-report/starter-report.html
hdox build examples/starter-report -o examples/starter-report/starter-report.pdf

hdox validate examples/starter-report/starter-report.hdox
hdox llm-read examples/starter-report/starter-report.hdox
hdox llm-read examples/starter-report/starter-report.pdf
```

Open the generated PDF with the platform viewer:

```bash
# macOS
open examples/starter-report/starter-report.pdf

# Linux
xdg-open examples/starter-report/starter-report.pdf
```

### Windows (PowerShell)

```powershell
.\.venv\Scripts\Activate.ps1

hdox build examples\starter-report -o examples\starter-report\starter-report.hdox
hdox build examples\starter-report -o examples\starter-report\starter-report.html
hdox build examples\starter-report -o examples\starter-report\starter-report.pdf

hdox validate examples\starter-report\starter-report.hdox
hdox llm-read examples\starter-report\starter-report.hdox
hdox llm-read examples\starter-report\starter-report.pdf

Start-Process examples\starter-report\starter-report.pdf
Start-Process examples\starter-report\starter-report.html
```

The result demonstrates that the same rich HTML/CSS source produces:

- **`.hdox`**: portable semantic HTML/CSS, manifest, SVG asset, and JSON metadata in one file
- **PDF**: printable A4 output with the source `.hdox` attached for AI round-tripping
- **HTML**: self-contained browser output with CSS and the SVG chart inlined
- **LLM read**: structured Markdown from both `.hdox` and the hybrid PDF

## 60-second tour

### Bash

```bash
# Write Markdown (YAML front matter optional) and build every output from it
cat > report.md <<'MD'
---
title: Quarterly Review
authors: [Jane Doe]
keywords: [quarterly, review]
---
# Executive summary
Revenue grew **12%**.

| Region | Growth |
| ------ | ------ |
| EMEA   | 9%     |
MD

hdox build report.md -o report.hdox     # the portable source of truth
hdox build report.md -o report.pdf      # PDF with the .hdox embedded
hdox build report.md -o report.html     # single self-contained HTML file

hdox validate report.hdox               # container, manifest schema, links, safety
hdox llm-read report.hdox               # Markdown from the portable source
hdox llm-read report.pdf                # Markdown for an LLM – works on .hdox and hybrid PDFs
```

### Windows (PowerShell)

```powershell
# Write Markdown (YAML front matter optional) and build every output from it
@'
---
title: Quarterly Review
authors: [Jane Doe]
keywords: [quarterly, review]
---
# Executive summary
Revenue grew **12%**.

| Region | Growth |
| ------ | ------ |
| EMEA   | 9%     |
'@ | Set-Content -Path report.md -Encoding utf8

hdox build report.md -o report.hdox     # the portable source of truth
hdox build report.md -o report.pdf      # PDF with the .hdox embedded
hdox build report.md -o report.html     # single self-contained HTML file

hdox validate report.hdox               # container, manifest schema, links, safety
hdox llm-read report.hdox               # Markdown from the portable source
hdox llm-read report.pdf                # Markdown for an LLM – works on .hdox and hybrid PDFs
```

Prefer hand-written HTML/CSS? `hdox init my-report`, edit `index.html` and `styles/paged.css`, then
`hdox build my-report -o my-report.pdf`. See [`examples/starter-report`](examples/starter-report).

## CLI reference

| Command | What it does |
| --- | --- |
| `hdox init <dir>` | scaffold a project (never overwrites existing files) |
| `hdox pack <dir> -o f.hdox` | pack a project; derives title/summary/token count; never modifies the source dir |
| `hdox unpack f.hdox -o <dir>` | safe extraction (blocks path traversal, symlinks, zip bombs) |
| `hdox validate f.hdox` | JSON report of `errors` and `warnings`; exit code 1 if invalid |
| `hdox llm-read f.hdox [--format markdown\|json]` | Markdown (or manifest + Markdown + JSON-LD) – accepts hybrid PDFs too |
| `hdox from-md f.md -o f.hdox` | Markdown → `.hdox` (tables, code, footnotes, local images bundled) |
| `hdox to-pdf f.hdox -o f.pdf [--embed]` | PDF via WeasyPrint or headless Chrome/Edge/Chromium |
| `hdox to-html f.hdox -o f.html` | one self-contained HTML file (CSS/images inlined) |
| `hdox build <md\|dir\|hdox> -o out.{hdox,pdf,html}` | one-shot build, like `latexmk` |
| `hdox keygen --private k.pem` / `sign` / `verify [--public-key HEX]` | Ed25519 signatures; verify detects any change, addition or removal |
| `hdox mcp` | MCP server (stdio): `read_hdox`, `read_hdox_markdown`, `validate_hdox`, `create_hdox` |

Python API: `from hdox import pack, validate, to_markdown, to_llm_context, chunk_markdown, sign, verify`.

## Why it is safe to open

- No script execution and no network access in v1.0.0; the TypeScript viewer strips scripts and sandboxes the iframe.
- Resources must live inside the archive; `data:` URIs only for images/fonts. Hyperlinks (`https:`, `mailto:`) are fine – they load nothing.
- Archive paths are normalised and checked; symlinks, duplicates, traversal and oversized archives are rejected.
- Optional Ed25519 signing, with public-key pinning on verify.

## Open it anywhere

| Where | How |
| --- | --- |
| Any OS / browser | `hdox to-html` (no tooling needed to read the result) or `hdox to-pdf` |
| Browser viewer | drag a `.hdox` onto [`packages/web-viewer`](packages/web-viewer) (build the SDK first, serve over HTTP) |
| Web / Node apps | [`packages/sdk-ts`](packages/sdk-ts): `readHDOX`, `toLLMContext`, `HDOXViewer` |
| AI agents | `hdox llm-read`, the MCP server, or the TypeScript SDK |
| File-manager integration | Linux, macOS (Quick Look), Windows (preview handler), Android, iOS under [`packages/os-integrations`](packages/os-integrations) – **scaffolding, not yet shipped or tested** |
| Editors | it is a ZIP of text: `unzip`, or `hdox unpack`, and edit with anything |

## Who is it for?

- **AI / RAG developers** – ingest documents without OCR or layout heuristics: structured Markdown, JSON-LD and an MCP server out of the box.
- **Docs-as-code teams** – write Markdown or HTML/CSS, build PDFs in CI, keep everything diffable.
- **Tool builders** – a small, documented spec with a JSON Schema, a validator and a TypeScript SDK to build viewers, editors and converters on.

## Status and roadmap

v1.0.0 is a working reference implementation. Implemented and tested: container, manifest schema,
validator, Markdown import, PDF/HTML export, hybrid PDF, LLM extraction, MCP server, signing. Not yet there:
native OS preview handlers (scaffolds only), in-place section editing, a live-reload `hdox watch`,
and Python-side CSS paged-media features beyond what WeasyPrint/Chromium support.

## Contribute

HDOX is young, so early contributors shape the format. Read [CONTRIBUTING.md](CONTRIBUTING.md) (setup takes two minutes), then pick something:

**Help wanted**

- 🟢 Add example documents (invoice, résumé, paper, slide-style) under `examples/` with a passing `validate`
- 🟢 Improve the HTML→Markdown extractor (`definition lists`, `<details>`, footnotes) – add a test per element
- 🟢 Port the validator rules to the TypeScript SDK so both reject exactly the same files
- `hdox watch`: rebuild and live-reload the PDF/HTML preview on file change
- Native previews: finish and test the Windows / macOS Quick Look / Linux thumbnailer scaffolds
- Section-level editing API (`edit_hdox_section` for the MCP server)
- Spec review: find ambiguities in [`spec/SPECIFICATION.md`](spec/SPECIFICATION.md) and open an issue
- Security review of the unpack/validate path (fuzzing welcome)

Found a bug? Open an issue with the smallest `.hdox` (or Markdown) that reproduces it.

## License

[MIT](LICENSE) © 2026 Hashim Hilal

## Development

```bash
cd packages/cli-python && python -m pip install -e ".[dev]" && pytest # 48 tests
cd packages/sdk-ts && npm ci && npm run build
```

`spec/manifest.schema.json` is mirrored in `packages/cli-python/hdox/schema/`; a test keeps the two identical.
Format details: [`spec/SPECIFICATION.md`](spec/SPECIFICATION.md).

```text
packages/cli-python/       Python library, CLI, converters, MCP server, tests
packages/sdk-ts/           TypeScript reader, viewer, LLM context
packages/web-viewer/       drag-and-drop browser viewer
packages/os-integrations/  OS preview/association scaffolding
examples/starter-report/   rich HTML/CSS project with generated HDOX, HTML, and hybrid PDF
spec/                      specification + manifest schema
```
