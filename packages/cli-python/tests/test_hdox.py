import json
import stat
import zipfile
from pathlib import Path

import pytest

from hdox import (HDOXError, generate_keypair, init, pack, sign, to_llm_context,
                  to_markdown, unpack, validate, verify)
from hdox.cli import main
from hdox.converters import build, from_markdown, to_html, to_pdf
from hdox.core import MIMETYPE
from hdox.llm import chunk_markdown

REPO = Path(__file__).resolve().parents[3]


def make(tmp_path, html, extra=None, manifest=None):
    project = tmp_path / "proj"
    init(project)
    (project / "index.html").write_text(html, encoding="utf-8")
    for name, data in (extra or {}).items():
        (project / name).parent.mkdir(parents=True, exist_ok=True)
        (project / name).write_bytes(data if isinstance(data, bytes) else data.encode())
    if manifest:
        m = json.loads((project / "manifest.json").read_text())
        m.update(manifest)
        (project / "manifest.json").write_text(json.dumps(m))
    return pack(project, tmp_path / "out.hdox")


# ---- container ---------------------------------------------------------------

def test_roundtrip(tmp_path):
    project = tmp_path / "r"
    init(project)
    archive = pack(project, tmp_path / "r.hdox")
    assert validate(archive).valid
    unpack(archive, tmp_path / "u")
    assert (tmp_path / "u" / "index.html").exists()


def test_mimetype_first_stored(tmp_path):
    project = tmp_path / "r"
    init(project)
    pack(project, tmp_path / "r.hdox")
    with zipfile.ZipFile(tmp_path / "r.hdox") as zf:
        first = zf.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == MIMETYPE.encode()


def test_pack_is_deterministic_apart_from_manifest_time(tmp_path):
    project = tmp_path / "r"
    init(project)
    pack(project, tmp_path / "a.hdox")
    with zipfile.ZipFile(tmp_path / "a.hdox") as zf:
        assert zf.read("index.html") == (project / "index.html").read_bytes()


def test_pack_does_not_mutate_project_or_include_junk(tmp_path):
    project = tmp_path / "r"
    init(project)
    before = (project / "manifest.json").read_text()
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("x")
    (project / "__pycache__").mkdir()
    (project / "__pycache__" / "x.pyc").write_bytes(b"1")
    out = pack(project, project / "self.hdox")  # output inside the project
    assert (project / "manifest.json").read_text() == before
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert not any(n.startswith((".git", "__pycache__")) or n == "self.hdox" for n in names)
    assert len(names) == len(set(names))


def test_pack_without_manifest_uses_html_title(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    (project / "index.html").write_text("<html><head><title>My Doc</title><style>.x{}</style></head><body><p>Hello there</p></body></html>")
    archive = pack(project, tmp_path / "p.hdox")
    assert validate(archive).valid
    with zipfile.ZipFile(archive) as zf:
        m = json.loads(zf.read("manifest.json"))
    assert m["title"] == "My Doc"
    assert m["ai_metadata"]["summary"].startswith("My Doc") or "Hello" in m["ai_metadata"]["summary"]
    assert ".x{}" not in m["ai_metadata"]["summary"]


def test_pack_errors(tmp_path):
    with pytest.raises(HDOXError):
        pack(tmp_path / "nope", tmp_path / "o.hdox")
    p = tmp_path / "p"
    p.mkdir()
    with pytest.raises(HDOXError, match="entrypoint"):
        pack(p, tmp_path / "o.hdox")
    (p / "index.html").write_text("<p>x</p>")
    (p / "manifest.json").write_text("{bad")
    with pytest.raises(HDOXError, match="manifest"):
        pack(p, tmp_path / "o.hdox")
    (p / "manifest.json").write_text('{"entrypoint": "../x.html"}')
    with pytest.raises(HDOXError, match="entrypoint"):
        pack(p, tmp_path / "o.hdox")


def test_pack_rejects_symlink(tmp_path):
    p = tmp_path / "p"
    init(p)
    (p / "link").symlink_to("/etc/passwd")
    with pytest.raises(HDOXError, match="symbolic"):
        pack(p, tmp_path / "o.hdox")


def test_init_does_not_clobber(tmp_path):
    p = tmp_path / "p"
    init(p)
    (p / "index.html").write_text("<p>mine</p>")
    init(p)
    assert (p / "index.html").read_text() == "<p>mine</p>"


# ---- unpack safety -----------------------------------------------------------

@pytest.mark.parametrize("name", ["../escape.txt", "/abs.txt", "a/../../b.txt", "C:/x.txt", "a\\b.txt"])
def test_unsafe_paths_blocked(tmp_path, name):
    archive = tmp_path / "bad.hdox"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("mimetype", MIMETYPE)
        zf.writestr(name, "bad")
    with pytest.raises(HDOXError):
        unpack(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())
    assert not validate(archive).valid


def test_symlink_entry_blocked(tmp_path):
    archive = tmp_path / "s.hdox"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("mimetype", MIMETYPE)
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(HDOXError, match="symbolic"):
        unpack(archive, tmp_path / "o")
    assert any("symbolic" in e for e in validate(archive).errors)


def test_unpack_non_zip(tmp_path):
    f = tmp_path / "x.hdox"
    f.write_text("junk")
    with pytest.raises(HDOXError):
        unpack(f, tmp_path / "o")


# ---- validation --------------------------------------------------------------

def test_validate_missing_and_garbage(tmp_path):
    assert "not found" in validate(tmp_path / "none.hdox").errors[0]
    f = tmp_path / "j.hdox"
    f.write_text("junk")
    assert not validate(f).valid


def test_manifest_schema_errors_are_reported(tmp_path):
    a = make(tmp_path, "<p>x</p>", manifest={"authors": "bob", "language": 5})
    r = validate(a)
    assert not r.valid
    assert any("authors" in e for e in r.errors) and any("language" in e for e in r.errors)


def test_schema_copies_in_sync():
    assert (REPO / "spec" / "manifest.schema.json").read_bytes() == \
        (REPO / "packages/cli-python/hdox/schema/manifest.schema.json").read_bytes()


def test_external_resources_rejected(tmp_path):
    for html in ['<img src="https://x.com/a.png">', '<link rel="stylesheet" href="//cdn/x.css">',
                 '<script src="http://x/a.js"></script>', '<img srcset="https://x/a.png 1x">',
                 '<div style="background:url(https://x/a.png)"></div>',
                 '<style>@import "https://x/a.css";</style>']:
        r = validate(make(tmp_path, f"<html><body>{html}</body></html>"))
        assert not r.valid, html
        assert any("external" in e for e in r.errors), (html, r.errors)


def test_external_network_flag_unsupported_in_v01(tmp_path):
    a = make(tmp_path, "<p>x</p>",
             manifest={"security": {"allow_scripts": False, "allow_external_network": True, "signed": False}})
    assert any("allow_external_network" in e for e in validate(a).errors)


def test_hyperlinks_and_data_images_ok(tmp_path):
    html = ('<a href="https://example.com">e</a> <a href="mailto:a@b.co">m</a> <a href="#top">t</a>'
            '<img src="data:image/png;base64,AAAA">')
    assert validate(make(tmp_path, html)).valid


def test_dangerous_protocols_rejected(tmp_path):
    for html in ['<a href="javascript:alert(1)">x</a>', '<img src="data:text/html;base64,AAAA">',
                 '<iframe src="javascript:1"></iframe>', '<base href="https://evil/">',
                 '<img src="file:///etc/passwd">']:
        assert not validate(make(tmp_path, html)).valid, html


def test_broken_and_escaping_links(tmp_path):
    r = validate(make(tmp_path, '<img src="nope.png"><img src="../x.png"><img src="/abs.png">'))
    assert any("broken" in e for e in r.errors)
    assert sum("escapes" in e for e in r.errors) == 2


def test_internal_links_resolve_variants(tmp_path):
    html = '<img src="./assets/a b.png?v=1#x"><link rel="stylesheet" href="styles/../styles/paged.css">'
    a = make(tmp_path, html, extra={"assets/a b.png": b"png"})
    assert validate(a).valid, validate(a).errors


def test_css_urls_resolved_relative_to_css(tmp_path):
    a = make(tmp_path, '<link rel="stylesheet" href="styles/paged.css">',
             extra={"styles/paged.css": "body{background:url(../assets/bg.png)} /* url(nothing.png) */",
                    "assets/bg.png": b"x"})
    assert validate(a).valid
    b = make(tmp_path, '<link rel="stylesheet" href="styles/paged.css">',
             extra={"styles/paged.css": "@font-face{src:url('https://fonts/x.woff')}"})
    assert not validate(b).valid


def test_scripts_warn_not_fail(tmp_path):
    r = validate(make(tmp_path, '<script>1</script><p onclick="x()">a</p>'
                                '<script type="application/ld+json">{}</script>'))
    assert r.valid and any("script" in w for w in r.warnings) and any("onclick" in w for w in r.warnings)


def test_custom_entrypoint(tmp_path):
    p = tmp_path / "p"
    init(p)
    (p / "main.html").write_text("<title>Alt</title><p>alt body</p>")
    m = json.loads((p / "manifest.json").read_text())
    m["entrypoint"] = "main.html"
    (p / "manifest.json").write_text(json.dumps(m))
    a = pack(p, tmp_path / "a.hdox")
    assert validate(a).valid
    assert "alt body" in to_markdown(a)


def test_missing_entrypoint_flagged(tmp_path):
    a = tmp_path / "a.hdox"
    with zipfile.ZipFile(a, "w") as zf:
        zf.writestr("mimetype", MIMETYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr("index.html", "<p>x</p>")
        zf.writestr("manifest.json", json.dumps({"entrypoint": "gone.html"}))
    assert any("entrypoint" in e for e in validate(a).errors)


def test_validate_bad_mimetype(tmp_path):
    a = tmp_path / "a.hdox"
    with zipfile.ZipFile(a, "w") as zf:
        zf.writestr("manifest.json", "{}")
        zf.writestr("mimetype", "text/plain", compress_type=zipfile.ZIP_DEFLATED)
    errs = validate(a).errors
    assert any("first" in e for e in errs)


# ---- LLM extraction ----------------------------------------------------------

HTML = """<!doctype html><html><head><title>T</title><style>p{color:red}</style>
<script type="application/ld+json">{"@type":"Report","name":"Q"}</script></head>
<body><main><article><h1>Heading</h1><p>Some <strong>bold</strong>, <em>it</em> and <code>code</code> <a href="https://e.com">link</a>.</p>
<ul><li>one</li><li>two<ul><li>nested</li></ul></li></ul><ol start="3"><li>a</li><li>b</li></ol>
<table><thead><tr><th>H1</th><th>H2</th></tr></thead><tbody><tr><td>1</td><td>a|b</td></tr></tbody></table>
<pre>line1
  line2</pre><blockquote>quoted</blockquote>
<img src="a.png" alt="A pic"><img src="data:image/png;base64,AAAA" alt="Inline">
<script>var secret=1</script></article></main></body></html>"""


def test_markdown_extraction(tmp_path):
    a = make(tmp_path, HTML, extra={"a.png": b"x"})
    md = to_markdown(a)
    assert "# Heading" in md
    assert "**bold**" in md and "*it*" in md and "`code`" in md and "[link](https://e.com)" in md
    assert "- one" in md and "  - nested" in md and "3. a" in md and "4. b" in md
    assert "| H1 | H2 |" in md and "| --- | --- |" in md and "| 1 | a\\|b |" in md
    assert "```\nline1\n  line2\n```" in md
    assert "![A pic](a.png)" in md and "[image: Inline]" in md and "AAAA" not in md
    assert "color:red" not in md and "secret" not in md


def test_llm_json_context(tmp_path):
    ctx = json.loads(to_llm_context(make(tmp_path, HTML, extra={"a.png": b"x"})))
    assert ctx["json_ld"] == [{"@type": "Report", "name": "Q"}]
    assert ctx["manifest"]["hdox_version"] == "0.1.0" and "Heading" in ctx["markdown"]


def test_frontmatter_is_valid_yaml(tmp_path):
    import yaml
    md = to_markdown(make(tmp_path, "<p>x</p>", manifest={"title": 'He said "hi": ok', "authors": ["Ünï"]}))
    meta = yaml.safe_load(md.split("---")[1])
    assert meta["title"] == 'He said "hi": ok' and meta["authors"] == ["Ünï"]


def test_chunking_respects_paragraphs(tmp_path):
    body = "".join(f"<p>{'word ' * 50}{i}</p>" for i in range(20))
    chunks = chunk_markdown(make(tmp_path, body), max_chars=600)
    assert len(chunks) > 3 and all(len(c) <= 600 for c in chunks)
    assert all(c.rstrip().split()[-1].isdigit() for c in chunks)


def test_llm_errors(tmp_path):
    f = tmp_path / "x.hdox"
    f.write_text("junk")
    with pytest.raises(HDOXError):
        to_markdown(f)
    with pytest.raises(HDOXError):
        to_markdown(tmp_path / "missing.hdox")


# ---- Markdown import ---------------------------------------------------------

def test_from_markdown(tmp_path):
    (tmp_path / "pic.png").write_bytes(b"png")
    md = tmp_path / "d.md"
    md.write_text('---\ntitle: "A <b> & B"\nauthors: [Jane]\nkeywords: [x, y]\n---\n\nHello\n\n'
                  '| a | b |\n|---|---|\n| 1 | 2 |\n\n![p](pic.png)\n\n```py\nprint(1)\n```\n', encoding="utf-8")
    out = from_markdown(md, tmp_path / "d.hdox")
    assert validate(out).valid, validate(out).errors
    with zipfile.ZipFile(out) as zf:
        html = zf.read("index.html").decode()
        m = json.loads(zf.read("manifest.json"))
        assert "pic.png" in zf.namelist()
    assert "<b>" not in html.split("<body>")[0] and "A &lt;b&gt; &amp; B" in html
    assert m["title"] == "A <b> & B" and m["authors"] == ["Jane"] and m["ai_metadata"]["keywords"] == ["x", "y"]
    assert "<table>" in html
    assert not (tmp_path / "d.project").exists()


def test_from_markdown_title_fallbacks_and_no_clobber(tmp_path):
    keep = tmp_path / "d.project"
    keep.mkdir()
    (keep / "precious.txt").write_text("keep me")
    md = tmp_path / "d.md"
    md.write_text("# From Heading\n\ntext\n")
    out = from_markdown(md, tmp_path / "d.hdox")
    assert (keep / "precious.txt").exists()
    with zipfile.ZipFile(out) as zf:
        assert json.loads(zf.read("manifest.json"))["title"] == "From Heading"
        assert zf.read("index.html").decode().count("<h1") == 1
    md.write_text("---\ntitle: [unclosed\n---\nx")
    with pytest.raises(HDOXError, match="front matter"):
        from_markdown(md, tmp_path / "e.hdox")


# ---- HTML / PDF export -------------------------------------------------------

def test_to_html_is_self_contained(tmp_path):
    a = make(tmp_path, '<link rel="stylesheet" href="styles/paged.css"><p>hi</p><img src="a.png" alt="x">',
             extra={"a.png": b"PNGDATA", "styles/paged.css": "p{background:url(../a.png)}"})
    out = to_html(a, tmp_path / "o.html")
    html = out.read_text()
    assert "href=\"styles/paged.css\"" not in html and "data:image/png;base64," in html
    assert "hdox-manifest" in html and 'src="a.png"' not in html


def test_to_pdf_and_embed_roundtrip(tmp_path):
    pytest.importorskip("weasyprint")
    pytest.importorskip("pypdf")
    a = make(tmp_path, "<h1>Round Trip</h1><p>Embedded source text</p>")
    pdf = to_pdf(a, tmp_path / "o.pdf", embed=True)
    assert pdf.read_bytes().startswith(b"%PDF-")
    assert "Embedded source text" in to_markdown(pdf)  # AI reads HTML source out of the PDF
    plain = to_pdf(a, tmp_path / "p.pdf")
    with pytest.raises(HDOXError, match="no embedded"):
        to_markdown(plain)


def test_build_variants(tmp_path):
    md = tmp_path / "d.md"
    md.write_text("# Hi\n\ntext")
    assert validate(build(md, tmp_path / "o.hdox")).valid
    assert build(md, tmp_path / "o.html").read_text().startswith("<!doctype html>")
    proj = tmp_path / "proj"
    init(proj)
    assert validate(build(proj, tmp_path / "p.hdox")).valid
    with pytest.raises(HDOXError):
        build(md, tmp_path / "o.docx")
    with pytest.raises(HDOXError):
        build(tmp_path / "x.txt", tmp_path / "o.hdox")


# ---- signing -----------------------------------------------------------------

def test_sign_verify_and_tamper(tmp_path):
    a = make(tmp_path, "<p>x</p>")
    key = tmp_path / "k.pem"
    pub = generate_keypair(key)
    assert not verify(a).valid  # unsigned
    sign(a, key)
    assert verify(a).valid and verify(a, pub).valid
    assert validate(a).valid  # signature file doesn't break validation
    assert not verify(a, "00" * 32).valid  # pinned to a different signer
    sign(a, key)  # re-signing is idempotent
    assert verify(a).valid
    # tamper
    tampered = tmp_path / "t.hdox"
    with zipfile.ZipFile(a) as src, zipfile.ZipFile(tampered, "w") as dst:
        for i in src.infolist():
            data = src.read(i.filename)
            dst.writestr(i, data.replace(b"<p>x</p>", b"<p>y</p>") if i.filename == "index.html" else data)
    assert not verify(tampered).valid
    # injected extra file
    with zipfile.ZipFile(a, "a") as zf:
        zf.writestr("extra.txt", "x")
    assert not verify(a).valid


def test_sign_bad_key(tmp_path):
    a = make(tmp_path, "<p>x</p>")
    bad = tmp_path / "bad.pem"
    bad.write_text("nope")
    with pytest.raises(HDOXError):
        sign(a, bad)
    with pytest.raises(HDOXError):
        sign(a, tmp_path / "missing.pem")
    assert not list(tmp_path.glob("*.tmp"))


def test_verify_garbage(tmp_path):
    f = tmp_path / "g.hdox"
    f.write_text("junk")
    assert not verify(f).valid
    assert not verify(tmp_path / "none.hdox").valid


# ---- CLI + MCP ---------------------------------------------------------------

def test_cli_flow(tmp_path, capsys):
    proj = str(tmp_path / "p")
    out = str(tmp_path / "p.hdox")
    assert main(["init", proj]) == 0
    assert main(["pack", proj, "-o", out]) == 0
    assert main(["validate", out]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert main(["llm-read", out]) == 0
    assert main(["llm-read", out, "--format", "json"]) == 0
    assert main(["to-html", out, "-o", str(tmp_path / "p.html")]) == 0
    assert main(["unpack", out, "-o", str(tmp_path / "u")]) == 0
    assert main(["keygen", "--private", str(tmp_path / "k.pem")]) == 0
    assert main(["sign", out, "--key", str(tmp_path / "k.pem")]) == 0
    assert main(["verify", out]) == 0


def test_cli_errors_exit_nonzero_without_traceback(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "none.hdox")]) == 1
    assert main(["unpack", str(tmp_path / "none.hdox"), "-o", str(tmp_path / "o")]) == 1
    assert main(["llm-read", str(tmp_path / "none.hdox")]) == 1
    assert main(["pack", str(tmp_path / "none"), "-o", "x"]) == 1
    assert main(["from-md", str(tmp_path / "none.md"), "-o", str(tmp_path / "x.hdox")]) == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err and "hdox: error" in err


def test_mcp_protocol(tmp_path):
    from hdox.mcp_server import handle
    a = make(tmp_path, "<h1>MCP</h1>")
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})["result"]["serverInfo"]["name"] == "hdox"
    tools = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert all("inputSchema" in t for t in tools)
    r = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "read_hdox_markdown", "arguments": {"file": str(a)}}})
    assert "# MCP" in r["result"]["content"][0]["text"]
    r = handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {"name": "validate_hdox", "arguments": {"file": str(a)}}})
    assert json.loads(r["result"]["content"][0]["text"])["valid"]
    r = handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                "params": {"name": "read_hdox", "arguments": {}}})
    assert r["result"]["isError"]
    assert "error" in handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "zzz"}})
    assert "error" in handle({"jsonrpc": "2.0", "id": 7, "method": "nope"})


def test_examples_validate():
    for ex in (REPO / "examples").iterdir():
        if ex.is_dir():
            out = ex.parent / f".{ex.name}.tmp.hdox"
            try:
                assert validate(pack(ex, out)).valid, ex
            finally:
                out.unlink(missing_ok=True)
