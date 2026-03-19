"""
单元测试：api.utils 安全与上传限制（不依赖 Ollama/Neo4j/Postgres）
CI 可仅运行本文件以保证无外部依赖时通过。
"""
import os
import tempfile
import pytest
from api.utils import (
    sanitize_filename,
    is_allowed_extension,
    resolve_path_under,
    ALLOWED_EXTENSIONS,
    MAX_FILES_PER_UPLOAD,
    MAX_FILE_SIZE_BYTES,
)


def test_sanitize_filename_basic():
    assert sanitize_filename("doc.pdf") == "doc.pdf"
    assert sanitize_filename("  report.docx  ") == "report.docx"
    assert sanitize_filename("报告.txt") == "报告.txt"


def test_sanitize_filename_rejects_path_traversal():
    assert sanitize_filename("..") == ""
    assert sanitize_filename("../etc/passwd") == ""
    assert sanitize_filename("a/../b") == ""
    assert sanitize_filename("a\\b") == ""


def test_sanitize_filename_rejects_empty():
    assert sanitize_filename("") == ""
    assert sanitize_filename("   ") == ""


def test_sanitize_filename_basename_only():
    assert sanitize_filename("/tmp/foo.pdf") == "foo.pdf"
    assert sanitize_filename("folder/sub/file.txt") == "file.txt"


def test_is_allowed_extension():
    assert is_allowed_extension("x.pdf") is True
    assert is_allowed_extension("x.PDF") is True
    assert is_allowed_extension("x.docx") is True
    assert is_allowed_extension("x.doc") is True
    assert is_allowed_extension("x.txt") is True
    assert is_allowed_extension("x.md") is True
    assert is_allowed_extension("x.html") is True
    assert is_allowed_extension("x.jpg") is True
    assert is_allowed_extension("x.png") is True
    assert is_allowed_extension("x.exe") is False
    assert is_allowed_extension("x") is False


def test_resolve_path_under_safe():
    with tempfile.TemporaryDirectory() as d:
        assert resolve_path_under(d, "a.txt") == os.path.realpath(os.path.join(d, "a.txt"))
        assert resolve_path_under(d, "  b.pdf  ") == os.path.realpath(os.path.join(d, "b.pdf"))


def test_resolve_path_under_rejects_traversal():
    with tempfile.TemporaryDirectory() as d:
        assert resolve_path_under(d, "../other/file.txt") is None
        assert resolve_path_under(d, "..") is None
        sub = os.path.join(d, "sub")
        os.makedirs(sub, exist_ok=True)
        # 从 sub 出发的 .. 会逃出 d
        assert resolve_path_under(sub, "../outside") is None


def test_resolve_path_under_rejects_invalid_filename():
    with tempfile.TemporaryDirectory() as d:
        assert resolve_path_under(d, "") is None
        assert resolve_path_under(d, "..") is None


def test_constants():
    assert MAX_FILES_PER_UPLOAD > 0
    assert MAX_FILE_SIZE_BYTES > 0
    assert ".pdf" in ALLOWED_EXTENSIONS
    assert ".doc" in ALLOWED_EXTENSIONS
    assert ".md" in ALLOWED_EXTENSIONS
    assert ".html" in ALLOWED_EXTENSIONS
    assert ".txt" in ALLOWED_EXTENSIONS
