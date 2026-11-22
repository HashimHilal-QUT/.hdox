# `.hdox` File Format Specification v0.1

## Container

A `.hdox` file is a PKWARE ZIP archive with MIME type
`application/vnd.hdox+zip`. The first central-directory entry MUST be
`mimetype`; it MUST use ZIP method `0` (stored) and contain exactly
`application/vnd.hdox+zip` without a trailing newline.

## Required files

- `mimetype`
- `manifest.json`
- `index.html`

`manifest.json` is UTF-8 JSON and MUST conform to the versioned
JSON Schema in `manifest.schema.json`.

## Internal paths

Paths are relative POSIX paths. Traversal names, absolute paths,
symbolic-link entries, and external `http:`, `https:`, `//`, `data:`,
or protocol URLs are prohibited.

## Security

Documents are offline by default. Script execution is disabled unless
`manifest.security.allow_scripts` is explicitly true, and external network
access is disabled unless `allow_external_network` is true.
