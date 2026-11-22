import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hdox.core import HDOXError, init, pack, unpack, validate
from hdox.llm import to_markdown, to_llm_context


def test_init_pack_validate_and_unpack(tmp_path):
    project = tmp_path / "report"
    init(project)
    archive = tmp_path / "report.hdox"
    pack(project, archive)

    result = validate(archive)
    assert result.valid, result.errors
    unpack_dir = tmp_path / "unpacked"
    unpack(archive, unpack_dir)


def test_mimetype_is_first_entry_and_stored(tmp_path):
    import zipfile

    project = tmp_path / "report"
    init(project)
    archive = tmp_path / "report.hdox"
    pack(project, archive)
    with zipfile.ZipFile(archive) as zf:
        assert zf.infolist()[0].filename == "mimetype"
        assert zf.infolist()[0].compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/vnd.hdox+zip"


def test_external_link_is_rejected(tmp_path):
    project = tmp_path / "report"
    init(project)
    (project / "index.html").write_text(
        '<html><body><main><a href="https://example.com">External</a></main></body></html>',
        encoding="utf-8",
    )
    archive = tmp_path / "report.hdox"
    pack(project, archive)
    result = validate(archive)
    assert not result.valid
    assert any("external network" in error for error in result.errors)


def test_llm_context_includes_manifest_markdown_and_ld_json(tmp_path):
    project = tmp_path / "report"
    init(project)
    (project / "index.html").write_text(
        '<html><head><script type="application/ld+json">'
        '{"@type":"Report","name":"Quarterly"}'
        "</script></head><body><main><article><h1>Quarterly</h1>"
        "<section><p>Hello world</p></section></article></main></body></html>",
        encoding="utf-8",
    )
    archive = tmp_path / "report.hdox"
    pack(project, archive)
    markdown = to_markdown(archive)
    context = json.loads(to_llm_context(archive))
    assert "Quarterly" in markdown
    assert context["json_ld"][0]["@type"] == "Report"


def test_zip_slip_is_blocked(tmp_path):
    import zipfile

    archive = tmp_path / "bad.hdox"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("mimetype", "application/vnd.hdox+zip")
        zf.writestr("../escape.txt", "bad")
    destination = tmp_path / "out"
    from hdox.core import unpack
    with pytest.raises(HDOXError):
        unpack(archive, destination)
