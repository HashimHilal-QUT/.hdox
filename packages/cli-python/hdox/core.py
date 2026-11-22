from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

MIMETYPE = "application/vnd.hdox+zip"
FORMAT_VERSION = "0.1.0"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "manifest.schema.json"

# Directories / files never packed into an archive.
_EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".hg", ".svn"}
_EXCLUDED_FILES = {".DS_Store", "Thumbs.db", "mimetype", "signatures.json"}

# Hard limits that protect unpack/validate against decompression bombs.
MAX_ENTRIES = 10_000
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


class HDOXError(Exception):
    pass


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid


# --------------------------------------------------------------------------- helpers

def _safe_name(name: str) -> bool:
    if not name or name.startswith("/") or "\\" in name or "\x00" in name:
        return False
    if re.match(r"^[a-zA-Z]:", name):  # Windows drive letter
        return False
    parts = PurePosixPath(name.rstrip("/")).parts
    return bool(parts) and ".." not in parts and not any(p in ("", ".") for p in parts)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class _TextCollector(HTMLParser):
    """Visible text only: skips <head>, <script>, <style>, <template>."""

    _SKIP = {"script", "style", "head", "template", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self._skip_depth:
            self.parts.append(data)


def _html_text(html: str) -> str:
    parser = _TextCollector()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())


def _default_manifest(title: str, text: str = "", language: str = "en") -> dict:
    now = _now()
    return {
        "$schema": "https://hdox.org/schemas/v0.1/manifest.schema.json",
        "hdox_version": FORMAT_VERSION,
        "id": f"urn:uuid:{uuid.uuid4()}",
        "title": title,
        "authors": [],
        "created_at": now,
        "modified_at": now,
        "language": language,
        "entrypoint": "index.html",
        "page_setup": {"size": "A4", "orientation": "portrait", "margins": "20mm"},
        "security": {"allow_scripts": False, "allow_external_network": False, "signed": False},
        "ai_metadata": {
            "summary": text[:500],
            "keywords": [],
            "reading_order": ["index.html"],
            "token_estimate": len(text.split()),
        },
    }


# --------------------------------------------------------------------------- init / pack / unpack

_INIT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Untitled</title>
<link rel="stylesheet" href="styles/paged.css">
</head>
<body>
<main>
<article>
<header><h1>Untitled</h1></header>
<section><p>Document content.</p></section>
</article>
</main>
</body>
</html>
"""

_INIT_CSS = """@page { size: A4; margin: 20mm; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; line-height: 1.5; }
h1, h2, h3 { break-after: avoid; }
table, figure, pre { break-inside: avoid; }
"""


def init(directory: os.PathLike | str) -> Path:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    (root / "styles").mkdir(exist_ok=True)
    # never clobber an existing project
    if not (root / "index.html").exists():
        (root / "index.html").write_text(_INIT_HTML, encoding="utf-8")
    if not (root / "styles" / "paged.css").exists():
        (root / "styles" / "paged.css").write_text(_INIT_CSS, encoding="utf-8")
    if not (root / "manifest.json").exists():
        html = (root / "index.html").read_text(encoding="utf-8")
        manifest = _default_manifest(root.resolve().name, _html_text(html))
        (root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return root


def _project_files(root: Path, exclude: Path | None) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in _EXCLUDED_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if name in _EXCLUDED_FILES and path.parent == root:
                continue
            if name == ".DS_Store" or name == "Thumbs.db":
                continue
            if path.is_symlink():
                raise HDOXError(f"symbolic links are not allowed in a project: {path}")
            if exclude is not None and path.resolve() == exclude:
                continue
            files.append(path)
    return files


def _read_manifest_file(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HDOXError(f"invalid manifest.json: {exc}") from exc
    if not isinstance(manifest, dict):
        raise HDOXError("invalid manifest.json: must contain a JSON object")
    return manifest


def build_manifest(root: Path) -> dict:
    """Merge a project's manifest.json (if any) with defaults and refresh derived fields.

    Does not modify the project directory.
    """
    manifest_path = root / "manifest.json"
    user = _read_manifest_file(manifest_path) if manifest_path.exists() else {}
    entry = user.get("entrypoint", "index.html")
    if not isinstance(entry, str) or not _safe_name(entry):
        raise HDOXError(f"invalid entrypoint: {entry!r}")
    entry_path = root / entry
    if not entry_path.is_file():
        raise HDOXError(f"entrypoint not found: {entry}")
    html = entry_path.read_text(encoding="utf-8")
    collector = _TextCollector()
    collector.feed(html)
    text = " ".join(" ".join(collector.parts).split())

    manifest = _default_manifest(collector.title.strip() or root.resolve().name, text)
    manifest.update({k: v for k, v in user.items() if k not in ("ai_metadata", "page_setup", "security")})
    for section in ("ai_metadata", "page_setup", "security"):
        manifest[section] = {**manifest[section], **(user.get(section) or {})}
    if not manifest.get("title"):
        manifest["title"] = collector.title.strip() or root.resolve().name
    ai = manifest["ai_metadata"]
    if not user.get("ai_metadata", {}).get("summary"):
        ai["summary"] = text[:500]
    ai["token_estimate"] = len(text.split())
    ai["reading_order"] = ai.get("reading_order") or [entry]
    manifest["modified_at"] = _now()
    return manifest


def pack(directory: os.PathLike | str, output: os.PathLike | str) -> Path:
    root = Path(directory)
    if not root.is_dir():
        raise HDOXError(f"not a directory: {root}")
    root = root.resolve()
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest(root)
    files = _project_files(root, out.resolve())
    tmp = out.with_name(out.name + ".tmp")
    try:
        with ZipFile(tmp, "w") as zf:
            mimetype = ZipInfo("mimetype", date_time=(1980, 1, 1, 0, 0, 0))
            mimetype.compress_type = ZIP_STORED
            mimetype.external_attr = 0o100644 << 16
            zf.writestr(mimetype, MIMETYPE)
            zf.writestr(
                ZipInfo("manifest.json", date_time=(1980, 1, 1, 0, 0, 0)),
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                compress_type=ZIP_DEFLATED,
            )
            for path in files:
                rel = path.relative_to(root).as_posix()
                if rel == "manifest.json":
                    continue
                zf.write(path, rel, compress_type=ZIP_DEFLATED)
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


def unpack(source: os.PathLike | str, output: os.PathLike | str) -> Path:
    src = Path(source)
    dest = Path(output)
    try:
        zf_ctx = ZipFile(src, "r")
    except (BadZipFile, OSError) as exc:
        raise HDOXError(f"cannot open archive: {exc}") from exc
    with zf_ctx as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise HDOXError("archive has too many entries")
        if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
            raise HDOXError("archive is too large when uncompressed")
        # validate everything before writing anything
        for info in infos:
            if not _safe_name(info.filename):
                raise HDOXError(f"unsafe archive path: {info.filename}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise HDOXError(f"symbolic link entries are not allowed: {info.filename}")
        dest.mkdir(parents=True, exist_ok=True)
        base = dest.resolve()
        for info in infos:
            if info.is_dir():
                continue
            target = (base / info.filename).resolve()
            if base not in target.parents:
                raise HDOXError(f"unsafe archive path: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as srcf, target.open("wb") as dstf:
                shutil.copyfileobj(srcf, dstf)
    return dest


# --------------------------------------------------------------------------- validation

def validate(source: os.PathLike | str) -> ValidationResult:
    path = Path(source)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        zf_ctx = ZipFile(path, "r")
    except FileNotFoundError:
        return ValidationResult(False, [f"file not found: {path}"])
    except (BadZipFile, OSError) as exc:
        return ValidationResult(False, [f"invalid ZIP archive: {exc}"])

    with zf_ctx as zf:
        infos = zf.infolist()
        names = [i.filename for i in infos]

        if len(infos) > MAX_ENTRIES:
            errors.append("archive has too many entries")
            return ValidationResult(False, errors)
        if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
            errors.append("archive is too large when uncompressed")
            return ValidationResult(False, errors)

        if not infos or infos[0].filename != "mimetype":
            errors.append("mimetype must be the first ZIP entry")
        else:
            if infos[0].compress_type != ZIP_STORED:
                errors.append("mimetype must use ZIP_STORED")
            if zf.read("mimetype") != MIMETYPE.encode("ascii"):
                errors.append("mimetype value is invalid")

        dupes = sorted({n for n in names if names.count(n) > 1})
        for name in dupes:
            errors.append(f"duplicate archive entry: {name}")
        for info in infos:
            if not _safe_name(info.filename):
                errors.append(f"unsafe archive path: {info.filename}")
            elif stat.S_ISLNK(info.external_attr >> 16):
                errors.append(f"symbolic link entries are not allowed: {info.filename}")

        for required in ("manifest.json", "index.html"):
            if required not in names:
                errors.append(f"missing required file: {required}")

        manifest: dict | None = None
        if "manifest.json" in names:
            try:
                loaded = json.loads(zf.read("manifest.json").decode("utf-8"))
                if not isinstance(loaded, dict):
                    errors.append("manifest.json must contain a JSON object")
                else:
                    manifest = loaded
                    _validate_manifest_schema(manifest, errors)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                errors.append(f"invalid manifest.json: {exc}")

        entry = "index.html"
        if manifest and isinstance(manifest.get("entrypoint"), str):
            entry = manifest["entrypoint"]
            if entry not in names:
                errors.append(f"entrypoint not found in archive: {entry}")
        allow_net = False  # v0.1: external network access is never permitted
        if manifest and (manifest.get("security") or {}).get("allow_external_network"):
            errors.append("security.allow_external_network is not supported in HDOX v0.1")
        allow_scripts = bool(manifest and (manifest.get("security") or {}).get("allow_scripts"))

        nameset = set(names)
        if entry in nameset:
            html = zf.read(entry).decode("utf-8", errors="replace")
            _check_html(html, entry, nameset, errors, warnings, allow_net, allow_scripts)
        for name in names:
            if name.lower().endswith(".css") and _safe_name(name):
                css = zf.read(name).decode("utf-8", errors="replace")
                _check_css(css, name, nameset, errors, allow_net)

        if "signatures.json" in names:
            warnings.append("archive is signed; run `hdox verify` to check the signature")

    return ValidationResult(not errors, errors, warnings)


def _validate_manifest_schema(manifest: dict, errors: list[str]) -> None:
    import jsonschema

    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(manifest), key=lambda e: list(e.absolute_path)):
        where = ".".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"manifest schema: {where}: {err.message}")


_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*):")
_RESOURCE_ATTRS = {
    ("img", "src"), ("source", "src"), ("script", "src"), ("link", "href"),
    ("video", "src"), ("video", "poster"), ("audio", "src"), ("iframe", "src"),
    ("embed", "src"), ("object", "data"), ("track", "src"), ("input", "src"),
}
_NAV_ATTRS = {("a", "href"), ("area", "href")}
_SAFE_DATA = re.compile(r"^data:(image/|font/|application/font|application/x-font)", re.I)


def _resolve_internal(ref: str, base_file: str) -> str | None:
    """Resolve a relative ref against the file containing it. None => escapes the archive."""
    clean = unquote(ref.split("#", 1)[0].split("?", 1)[0])
    if not clean:
        return base_file
    if clean.startswith("/"):
        return None
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(base_file), clean))
    if joined == ".." or joined.startswith("../"):
        return None
    return joined


def _check_ref(ref: str, kind: str, base_file: str, names: set[str],
               errors: list[str], allow_net: bool) -> None:
    ref = ref.strip()
    if not ref or ref.startswith("#"):
        return
    scheme = _SCHEME.match(ref)
    if ref.startswith("//") or scheme:
        name = scheme.group(1).lower() if scheme else "http"
        if kind == "nav":
            if name in ("http", "https", "mailto", "tel") or ref.startswith("//"):
                return  # plain hyperlinks never load anything
            errors.append(f"prohibited link protocol: {ref[:60]}")
        elif name == "data":
            if not _SAFE_DATA.match(ref):
                errors.append(f"prohibited data URI: {ref[:40]}...")
        elif name in ("http", "https") or ref.startswith("//"):
            if not allow_net:
                errors.append(f"external network reference: {ref}")
        else:
            errors.append(f"prohibited resource protocol: {ref[:60]}")
        return
    resolved = _resolve_internal(ref, base_file)
    if resolved is None:
        errors.append(f"reference escapes the archive: {ref}")
    elif resolved not in names:
        errors.append(f"broken internal link: {ref}")


class _RefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[tuple[str, str]] = []  # (kind, ref)
        self.scripts = 0
        self.handlers: list[str] = []
        self.style_blocks: list[str] = []
        self._in_style = False
        self.base: str | None = None

    def handle_starttag(self, tag, attrs):
        d = {k: (v or "") for k, v in attrs}
        if tag == "base" and "href" in d:
            self.base = d["href"]
        if tag == "style":
            self._in_style = True
            self.style_blocks.append("")
        if tag == "script" and d.get("type", "").lower() not in ("application/ld+json", "application/json"):
            self.scripts += 1
        for key, value in d.items():
            if key.startswith("on"):
                self.handlers.append(f"{tag}[{key}]")
            if (tag, key) in _RESOURCE_ATTRS and value:
                self.refs.append(("res", value))
            elif (tag, key) in _NAV_ATTRS and value:
                self.refs.append(("nav", value))
            elif key == "srcset" or (key == "imagesrcset"):
                for cand in value.split(","):
                    if cand.strip():
                        self.refs.append(("res", cand.strip().split()[0]))
            elif key == "style" and "url(" in value:
                self.style_blocks.append(value)

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.style_blocks[-1] += data


def _check_html(html: str, entry: str, names: set[str], errors: list[str],
                warnings: list[str], allow_net: bool, allow_scripts: bool) -> None:
    parser = _RefParser()
    parser.feed(html)
    if parser.base:
        errors.append("<base href> is not allowed")
    for kind, ref in parser.refs:
        if kind == "nav" and ref.strip().lower().startswith("javascript:"):
            errors.append(f"prohibited link protocol: {ref[:60]}")
            continue
        _check_ref(ref, kind, entry, names, errors, allow_net)
    for block in parser.style_blocks:
        _check_css(block, entry, names, errors, allow_net)
    if not allow_scripts:
        if parser.scripts:
            warnings.append(f"{entry}: {parser.scripts} <script> element(s) will be ignored (allow_scripts is false)")
        if parser.handlers:
            warnings.append(f"{entry}: inline event handlers will be ignored: {', '.join(sorted(set(parser.handlers)))}")


_CSS_URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)|@import\s+(['"])(.*?)\3""", re.I | re.S)


def _check_css(css: str, base_file: str, names: set[str], errors: list[str], allow_net: bool) -> None:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for m in _CSS_URL.finditer(css):
        ref = (m.group(2) if m.group(2) is not None else m.group(4)) or ""
        _check_ref(ref, "res", base_file, names, errors, allow_net)


# --------------------------------------------------------------------------- signing

def _hash_archive(zf: ZipFile) -> bytes:
    hashes = {}
    for info in zf.infolist():
        if info.filename != "signatures.json" and not info.is_dir():
            hashes[info.filename] = hashlib.sha256(zf.read(info.filename)).hexdigest()
    return json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(source: os.PathLike | str, private_key: os.PathLike | str) -> Path:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    src = Path(source)
    try:
        key = serialization.load_pem_private_key(Path(private_key).read_bytes(), None)
    except (ValueError, TypeError, OSError) as exc:
        raise HDOXError(f"cannot load private key: {exc}") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise HDOXError("private key must be Ed25519")
    try:
        with ZipFile(src, "r") as zf:
            payload = _hash_archive(zf)
    except (BadZipFile, OSError) as exc:
        raise HDOXError(f"cannot open archive: {exc}") from exc
    envelope = {
        "algorithm": "Ed25519",
        "public_key": key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex(),
        "payload_hash": hashlib.sha256(payload).hexdigest(),
        "signature": key.sign(payload).hex(),
    }
    tmp = src.with_name(src.name + ".tmp")
    try:
        with ZipFile(src, "r") as original, ZipFile(tmp, "w") as out:
            for info in original.infolist():
                if info.filename != "signatures.json":
                    out.writestr(info, original.read(info.filename), compress_type=info.compress_type)
            out.writestr("signatures.json", json.dumps(envelope, indent=2), compress_type=ZIP_DEFLATED)
        tmp.replace(src)
    finally:
        tmp.unlink(missing_ok=True)
    return src


def generate_keypair(private_path: os.PathLike | str, public_path: os.PathLike | str | None = None) -> str:
    """Write a PEM Ed25519 private key; return the hex public key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    p = Path(private_path)
    p.write_bytes(pem)
    try:
        p.chmod(0o600)
    except OSError:
        pass
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    if public_path:
        Path(public_path).write_text(pub + "\n", encoding="utf-8")
    return pub


def verify(source: os.PathLike | str, public_key: str | None = None) -> ValidationResult:
    """Verify an archive signature. Pass ``public_key`` (hex) to pin the expected signer."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    errors: list[str] = []
    try:
        with ZipFile(source, "r") as zf:
            if "signatures.json" not in zf.namelist():
                return ValidationResult(False, ["archive is not signed"])
            envelope = json.loads(zf.read("signatures.json").decode("utf-8"))
            if envelope.get("algorithm") != "Ed25519":
                return ValidationResult(False, ["unsupported signature algorithm"])
            if public_key and envelope["public_key"].lower() != public_key.strip().lower():
                return ValidationResult(False, ["signed by a different key than expected"])
            public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(envelope["public_key"]))
            payload = _hash_archive(zf)
            if hashlib.sha256(payload).hexdigest() != envelope["payload_hash"]:
                errors.append("archive contents changed after signing")
            public.verify(bytes.fromhex(envelope["signature"]), payload)
    except InvalidSignature:
        errors.append("signature does not match archive contents")
    except FileNotFoundError:
        errors.append(f"file not found: {source}")
    except (BadZipFile, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"signature verification failed: {exc}")
    return ValidationResult(not errors, errors)
