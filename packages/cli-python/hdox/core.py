from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable
from zipfile import ZIP_STORED, ZIP_DEFLATED, ZipFile, ZipInfo

MIMETYPE = "application/vnd.hdox+zip"
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "spec" / "manifest.schema.json"


class HDOXError(Exception):
    pass


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid


def _safe_name(name: str) -> bool:
    if not name or name.startswith("/") or "\\" in name:
        return False
    parts = PurePosixPath(name).parts
    return ".." not in parts and not any(part in ("", ".") for part in parts)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _html_text(html: str) -> str:
    from html.parser import HTMLParser

    class TextParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts: list[str] = []
        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    parser = TextParser()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())


def _default_manifest(directory: Path) -> dict:
    html = (directory / "index.html").read_text(encoding="utf-8") if (directory / "index.html").exists() else ""
    now = _now()
    return {
        "$schema": "https://hdox.org/schemas/v0.1/manifest.schema.json",
        "hdox_version": "0.1.0",
        "id": f"urn:uuid:{uuid.uuid4()}",
        "title": directory.name,
        "authors": [],
        "created_at": now,
        "modified_at": now,
        "language": "en",
        "entrypoint": "index.html",
        "page_setup": {"size": "A4", "orientation": "portrait", "margins": "20mm"},
        "security": {"allow_scripts": False, "allow_external_network": False, "signed": False},
        "ai_metadata": {
            "summary": _html_text(html)[:500],
            "keywords": [],
            "reading_order": ["index.html"],
            "token_estimate": max(0, len(_html_text(html).split())),
        },
    }


def init(directory: os.PathLike | str) -> Path:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    (root / "styles").mkdir(exist_ok=True)
    manifest = _default_manifest(root)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / "index.html").write_text(
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\"><title>Untitled</title>\n"
        "<link rel=\"stylesheet\" href=\"styles/paged.css\">\n</head>\n"
        "<body><main><article><header><h1>Untitled</h1></header><section><p>Document content.</p></section></article></main></body>\n</html>\n",
        encoding="utf-8",
    )
    (root / "styles" / "paged.css").write_text(
        "@page { size: A4; margin: 20mm; }\n"
        "main, article, section { break-inside: avoid; }\n",
        encoding="utf-8",
    )
    return root


def pack(directory: os.PathLike | str, output: os.PathLike | str) -> Path:
    root = Path(directory)
    if not root.is_dir():
        raise HDOXError(f"not a directory: {root}")

    manifest_path = root / "manifest.json"
    index_path = root / "index.html"
    if not manifest_path.exists():
        manifest = _default_manifest(root)
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HDOXError(f"invalid manifest.json: {exc}") from exc
        manifest = _default_manifest(root) | manifest
    manifest["modified_at"] = _now()
    if "title" not in manifest or not manifest["title"]:
        manifest["title"] = root.name

    html = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    text = _html_text(html)
    manifest.setdefault("ai_metadata", {})
    manifest["ai_metadata"]["token_estimate"] = max(0, len(text.split()))
    manifest["ai_metadata"]["reading_order"] = manifest["ai_metadata"].get("reading_order") or ["index.html"]
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(out, "w") as zf:
        mimetype = ZipInfo("mimetype")
        mimetype.compress_type = ZIP_STORED
        mimetype.external_attr = 0o100644 << 16
        zf.writestr(mimetype, MIMETYPE)
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(root).as_posix()
            if rel == "manifest.json":
                zf.write(path, rel, compress_type=ZIP_DEFLATED)
            elif rel not in ("mimetype",):
                zf.write(path, rel, compress_type=ZIP_DEFLATED)
    return out


def unpack(source: os.PathLike | str, output: os.PathLike | str) -> Path:
    src = Path(source)
    dest = Path(output)
    dest.mkdir(parents=True, exist_ok=True)
    with ZipFile(src, "r") as zf:
        for info in zf.infolist():
            if not _safe_name(info.filename):
                raise HDOXError(f"unsafe archive path: {info.filename}")
            if info.is_dir():
                continue
            target = (dest / info.filename).resolve()
            if dest.resolve() not in target.parents:
                raise HDOXError(f"unsafe archive path: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as srcf, target.open("wb") as dstf:
                shutil.copyfileobj(srcf, dstf)
    return dest


def validate(source: os.PathLike | str) -> ValidationResult:
    path = Path(source)
    errors: list[str] = []
    try:
        with ZipFile(path, "r") as zf:
            infos = zf.infolist()
            if not infos or infos[0].filename != "mimetype":
                errors.append("mimetype must be the first ZIP entry")
            else:
                if infos[0].compress_type != ZIP_STORED:
                    errors.append("mimetype must use ZIP_STORED")
                try:
                    if zf.read("mimetype") != MIMETYPE.encode("ascii"):
                        errors.append("mimetype value is invalid")
                except Exception:
                    errors.append("mimetype entry is unreadable")

            names = [i.filename for i in infos]
            for name in names:
                if not _safe_name(name):
                    errors.append(f"unsafe archive path: {name}")
            for required in ("manifest.json", "index.html"):
                if required not in names:
                    errors.append(f"missing required file: {required}")

            if "manifest.json" in names:
                try:
                    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                    if not isinstance(manifest, dict):
                        errors.append("manifest.json must contain a JSON object")
                    else:
                        _validate_manifest_schema(manifest, errors)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    errors.append(f"invalid manifest.json: {exc}")

            if "index.html" in names:
                html = zf.read("index.html").decode("utf-8", errors="replace")
                _check_html(html, names, errors)
    except (OSError, Exception) as exc:
        if isinstance(exc, HDOXError):
            raise
        errors.append(f"invalid ZIP archive: {exc}")
    return ValidationResult(not errors, errors)


def _validate_manifest_schema(manifest: dict, errors: list[str]) -> None:
    if SCHEMA_PATH.exists():
        try:
            import jsonschema
            with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
                jsonschema.validate(manifest, json.load(fh))
        except jsonschema.ValidationError as exc:
            errors.append(f"manifest schema: {exc.message}")
        except jsonschema.SchemaError as exc:
            errors.append(f"manifest schema: {exc.message}")
    else:
        required = {"$schema", "hdox_version", "id", "title", "authors", "created_at",
                    "modified_at", "language", "entrypoint", "page_setup", "security", "ai_metadata"}
        missing = sorted(required - manifest.keys())
        if missing:
            errors.append("manifest missing fields: " + ", ".join(missing))


def _check_html(html: str, names: list[str], errors: list[str]) -> None:
    from html.parser import HTMLParser

    class RefParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.refs: list[str] = []
        def handle_starttag(self, tag, attrs):
            for key, value in attrs:
                if key in ("src", "href") and value:
                    self.refs.append(value)

    parser = RefParser()
    parser.feed(html)
    for ref in parser.refs:
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", ref) or ref.startswith("//"):
            errors.append(f"external network reference: {ref}")
            continue
        clean = ref.split("#", 1)[0].split("?", 1)[0]
        if clean and not clean.startswith("/") and clean not in names:
            errors.append(f"broken internal link: {ref}")


def sign(source: os.PathLike | str, private_key: os.PathLike | str) -> Path:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    except ImportError as exc:
        raise HDOXError("cryptography is required to sign HDOX files") from exc

    src = Path(source)
    key_data = Path(private_key).read_bytes()
    key = serialization.load_pem_private_key(key_data, None)
    if not isinstance(key, Ed25519PrivateKey):
        raise HDOXError("private key must be Ed25519")

    hashes = {}
    with ZipFile(src, "r") as zf:
        for info in zf.infolist():
            if info.filename != "signatures.json":
                hashes[info.filename] = hashlib.sha256(zf.read(info.filename)).hexdigest()
    payload = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = key.sign(payload)
    public_key = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    envelope = {
        "algorithm": "Ed25519",
        "public_key": public_key.hex(),
        "payload_hash": hashlib.sha256(payload).hexdigest(),
        "signature": signature.hex(),
    }
    tmp = src.with_suffix(src.suffix + ".tmp")
    with ZipFile(src, "r") as original, ZipFile(tmp, "w") as out:
        mimetype = None
        for info in original.infolist():
            if info.filename == "mimetype":
                mimetype = info
                out.writestr(info, original.read(info.filename))
            elif info.filename != "signatures.json":
                out.writestr(info, original.read(info.filename))
        out.writestr("signatures.json", json.dumps(envelope, indent=2))
    tmp.replace(src)
    return src


def verify(source: os.PathLike | str) -> ValidationResult:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise HDOXError("cryptography is required to verify HDOX files") from exc
    src = Path(source)
    errors = []
    try:
        with ZipFile(src, "r") as zf:
            envelope = json.loads(zf.read("signatures.json").decode("utf-8"))
            public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(envelope["public_key"]))
            hashes = {}
            for info in zf.infolist():
                if info.filename not in ("signatures.json",):
                    hashes[info.filename] = hashlib.sha256(zf.read(info.filename)).hexdigest()
            payload = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
            public.verify(bytes.fromhex(envelope["signature"]), payload)
            if hashlib.sha256(payload).hexdigest() != envelope["payload_hash"]:
                errors.append("signed payload hash mismatch")
    except Exception as exc:
        errors.append(f"signature verification failed: {exc}")
    return ValidationResult(not errors, errors)
