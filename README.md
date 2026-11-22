# .hdox

**.hdox** is an offline, self-contained document format that combines the visual fidelity and print-ready layout of PDF with the semantic structure and machine readability of HTML.

A `.hdox` file is a ZIP container with a stable MIME marker, a JSON manifest, and an HTML entrypoint. It is portable, inspectable, and designed to remain useful in document, browser, and AI workflows.

## Format overview

HDOX documents use the MIME type `application/vnd.hdox+zip` and store their content in a predictable archive structure:

```text
report.hdox
├── mimetype
├── manifest.json
├── index.html
├── styles/
│   └── paged.css
└── assets/
    └── ...
```

- `mimetype` is the first, uncompressed ZIP entry.
- `manifest.json` describes document metadata, page setup, security, and AI context.
- `index.html` is the document entrypoint.
- All document resources use safe relative paths.

HDOX v0.1 is offline-first: scripts and external network access are disabled by default. JSON-LD, semantic HTML, reading order, and document summaries provide a structured representation for LLM and retrieval workflows.

## Quick start

Create and validate a development environment with Python:

```bash
cd packages/cli-python
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Create a document, pack it, inspect it, and unpack it:

```bash
hdox init my-report
hdox pack my-report -o my-report.hdox
hdox validate my-report.hdox
hdox unpack my-report.hdox -o unpacked
```

The starter example is available at `examples/starter-report`:

```bash
hdox pack examples/starter-report -o starter-report.hdox
hdox validate starter-report.hdox
```

## CLI

| Command | Purpose |
| --- | --- |
| `hdox init <dir>` | Create a new HDOX document project |
| `hdox pack <dir> -o <file.hdox>` | Pack a project into a HDOX archive |
| `hdox unpack <file.hdox> -o <dir>` | Safely extract an archive |
| `hdox validate <file.hdox>` | Validate the container and manifest |
| `hdox llm-read <file.hdox>` | Extract Markdown or JSON-LD/manifest context |
| `hdox from-md <file.md> -o <file.hdox>` | Convert Markdown to HDOX |
| `hdox to-pdf <file.hdox> -o <file.pdf>` | Export an HDOX document to PDF |
| `hdox sign <file.hdox> --key <private.pem>` | Add an Ed25519 signature |
| `hdox verify <file.hdox>` | Verify an existing signature |
| `hdox mcp` | Start the MCP server over stdio |

For LLM-oriented output:

```bash
hdox llm-read starter-report.hdox --format markdown
hdox llm-read starter-report.hdox --format json
```

Markdown frontmatter supports `title`, `authors`, `language`, and `keywords`:

```markdown
---
title: Quarterly Review
authors:
  - Jane Doe
language: en
keywords:
  - quarterly
  - review
---

# Executive summary

The report is ready for review.
```

PDF export uses WeasyPrint when available, with headless Chromium as a fallback.

## TypeScript SDK

Build the SDK:

```bash
cd packages/sdk-ts
npm install
npm run build
```

Read a HDOX archive and convert its content for an AI context:

```ts
import { readHDOX, toLLMContext } from "@hdox/sdk";

const archive = readHDOX(new Uint8Array(await file.arrayBuffer()));
const context = toLLMContext(archive.html, archive.manifest);
```

The SDK also exports `HDOXViewer` for rendering an archive inside a sandboxed iframe and `HDOX_MIMETYPE` for MIME-type handling.

## Web viewer

The browser viewer accepts a `.hdox` file by drag and drop. Serve the repository from an HTTP server after building the SDK:

```bash
cd packages/sdk-ts
npm install
npm run build

cd ../..
python3 -m http.server 8000
```

Open `http://localhost:8000/packages/web-viewer/` and drop a HDOX archive into the page.

## Security and validation

Validation checks:

- the `mimetype` entry is first and uses stored ZIP compression;
- required `manifest.json` and `index.html` files exist;
- the manifest conforms to `spec/manifest.schema.json`;
- archive paths do not escape the package;
- HTML links do not point outside the archive or to prohibited protocols.

Scripts are removed by the SDK viewer unless `manifest.security.allow_scripts` is explicitly enabled. External network access is rejected in HDOX v0.1.

See [`spec/SPECIFICATION.md`](spec/SPECIFICATION.md) for the container and security requirements, and [`spec/manifest.schema.json`](spec/manifest.schema.json) for the manifest schema.

## Repository layout

```text
packages/cli-python/       Python CLI, archive tools, conversions, and MCP server
packages/sdk-ts/           TypeScript archive reader, viewer, and LLM context tools
packages/web-viewer/       Drag-and-drop browser viewer
packages/os-integrations/  Linux, macOS, Windows, Android, and iOS integration files
examples/starter-report/   Minimal HDOX document project
spec/                     Format specification and manifest schema
```
