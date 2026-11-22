# `.hdox` File Format Specification v1.0

Status: draft. Keywords MUST, SHOULD and MAY are used as in RFC 2119.

## 1. Goals

1. **Portable** – one file, opens identically on every OS and browser; printable and exportable to PDF.
2. **AI-native** – the document *is* semantic HTML, so an LLM reads the same source a human sees.
3. **Code-native** – a document is a plain-text project (HTML + CSS + JSON) that can be generated, diffed and version-controlled; the archive is just a build artifact.
4. **Safe** – no code execution and no network access by default.

## 2. Container

A `.hdox` file is a ZIP archive (PKWARE APPNOTE) with media type `application/vnd.hdox+zip`
and file extension `.hdox`.

- The first entry MUST be `mimetype`, stored uncompressed (method 0), containing exactly
  `application/vnd.hdox+zip` with no trailing newline. This allows `file(1)`-style sniffing at a fixed offset.
- Entry names are relative, UTF-8, `/`-separated. Names MUST NOT be empty, absolute, contain `\`, a drive
  letter, `.`/`..` segments or NUL. Duplicate names and symbolic-link entries are prohibited.
- Readers SHOULD cap entry count and total uncompressed size (reference implementation: 10 000 entries / 512 MiB).

## 3. Required entries

| Entry | Purpose |
| --- | --- |
| `mimetype` | format marker (§2) |
| `manifest.json` | UTF-8 JSON, conforms to `manifest.schema.json` |
| the entrypoint (default `index.html`) | HTML5 document; `manifest.entrypoint` names it |

Optional: `styles/`, `assets/` (images, fonts), and `signatures.json` (§6).

## 4. Manifest

Required fields: `$schema`, `hdox_version` (`"1.0.0"`), `id`, `title`, `authors`, `created_at`,
`modified_at`, `language`, `entrypoint`, `page_setup`, `security`, `ai_metadata`.
Unknown fields are allowed and MUST be preserved by tools that rewrite manifests.

- `page_setup` – `size` (e.g. `A4`), `orientation`, `margins`. Authoritative page geometry is the
  entrypoint's CSS `@page` rule; the manifest value is a hint for tools that do not render CSS.
- `ai_metadata` – `summary`, `keywords`, `reading_order` (list of entries, entrypoint first),
  `token_estimate` (whitespace-token count of visible text).

`pack` derives `title` (from `<title>`), `summary` (unless set) and `token_estimate` from the
document, and refreshes `modified_at`. It never modifies the source directory.

## 5. Content rules

The entrypoint is HTML5. Authors SHOULD use semantic elements (`main`, `article`, `section`, `header`,
`h1–h6`, `table`, `figure`, `ul/ol`) and MAY embed `<script type="application/ld+json">` for structured data.
Layout for print/PDF uses CSS Paged Media (`@page`, `break-*`).

**Resource references** (`img/source/video/audio/track/embed/iframe src`, `object data`, `link href`,
`script src`, `srcset`, CSS `url()` and `@import`, in HTML, inline styles and `.css` entries):

- relative refs MUST resolve (after normalisation, relative to the referring file) to an entry inside the archive;
- `data:` URIs are allowed only for `image/*` and font types;
- `http:`, `https:`, `//` and every other scheme are prohibited.

**Hyperlinks** (`a/area href`): in-archive paths, `#fragments`, `http`, `https`, `mailto` and `tel` are
allowed (a hyperlink loads nothing). `javascript:` and other schemes are prohibited. `<base href>` is prohibited.

## 6. Security

- Viewers MUST NOT execute scripts unless `security.allow_scripts` is `true`, and SHOULD render inside a sandbox.
  Validators warn on scripts and inline event handlers when scripts are disabled.
- `security.allow_external_network` MUST be `false` in v1.0; validators reject `true`.
- **Signatures** – `signatures.json` holds `{algorithm: "Ed25519", public_key, payload_hash, signature}`. The signed
  payload is the compact, key-sorted JSON map `{entry name: sha256 hex}` of every entry except `signatures.json`.
  Adding, removing or changing any entry invalidates the signature. A valid signature proves integrity
  and key possession; trust in the key itself is out of band (verifiers SHOULD allow pinning the expected public key).
  The presence of `signatures.json`, not `manifest.security.signed`, is authoritative.

## 7. Hybrid PDF

A tool MAY render the document to PDF and attach the original `.hdox` as an embedded file named `source.hdox`.
The result is an ordinary PDF for any viewer, while AI tooling recovers the semantic HTML from the attachment.
Readers that accept PDFs SHOULD look for an attached `*.hdox` entry.

## 8. Conformance of the reference implementation

`hdox validate` implements §2–§6; `hdox llm-read` implements the HTML→Markdown projection (headings, emphasis,
links, nested lists, tables, code blocks, images as `![alt](path)`; `<head>`, scripts and styles excluded).
