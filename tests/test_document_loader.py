import tempfile
from pathlib import Path

import pytest

from core.document_loader import DocumentLoader


def test_load_dispatches_by_extension(monkeypatch):
    loader = DocumentLoader()
    calls = []

    monkeypatch.setattr(loader, "_load_pdf", lambda path: calls.append(("pdf", path)) or ["pdf"])
    monkeypatch.setattr(loader, "_load_docx", lambda path: calls.append(("docx", path)) or ["docx"])
    monkeypatch.setattr(loader, "_load_doc", lambda path: calls.append(("doc", path)) or ["doc"])
    monkeypatch.setattr(loader, "_load_pptx", lambda path: calls.append(("pptx", path)) or ["pptx"])
    monkeypatch.setattr(loader, "_load_xlsx", lambda path: calls.append(("xlsx", path)) or ["xlsx"])
    monkeypatch.setattr(loader, "_load_text", lambda path: calls.append(("text", path)) or ["text"])
    monkeypatch.setattr(loader, "_load_html", lambda path: calls.append(("html", path)) or ["html"])
    monkeypatch.setattr(loader, "_load_image", lambda path: calls.append(("image", path)) or ["image"])

    assert loader.load("/tmp/a.pdf") == ["pdf"]
    assert loader.load("/tmp/a.docx") == ["docx"]
    assert loader.load("/tmp/a.doc") == ["doc"]
    assert loader.load("/tmp/a.pptx") == ["pptx"]
    assert loader.load("/tmp/a.xlsx") == ["xlsx"]
    assert loader.load("/tmp/a.txt") == ["text"]
    assert loader.load("/tmp/a.md") == ["text"]
    assert loader.load("/tmp/a.xdmp") == ["text"]
    assert loader.load("/tmp/a.html") == ["html"]
    assert loader.load("/tmp/a.png") == ["image"]
    assert calls == [
        ("pdf", "/tmp/a.pdf"),
        ("docx", "/tmp/a.docx"),
        ("doc", "/tmp/a.doc"),
        ("pptx", "/tmp/a.pptx"),
        ("xlsx", "/tmp/a.xlsx"),
        ("text", "/tmp/a.txt"),
        ("text", "/tmp/a.md"),
        ("text", "/tmp/a.xdmp"),
        ("html", "/tmp/a.html"),
        ("image", "/tmp/a.png"),
    ]


def test_load_rejects_unknown_extension():
    loader = DocumentLoader()
    with pytest.raises(ValueError, match="Unsupported file type"):
        loader.load("/tmp/a.exe")


def test_load_text_preserves_metadata():
    loader = DocumentLoader()
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "note.md"
        path.write_text("hello world", encoding="utf-8")

        docs = loader._load_text(str(path))

    assert len(docs) == 1
    assert docs[0].text == "hello world"
    assert docs[0].metadata["file_name"] == "note.md"


def test_load_html_strips_tags():
    loader = DocumentLoader()
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "page.html"
        path.write_text(
            "<html><body><h1>Title</h1><script>alert(1)</script><p>Hello <b>GraphRAG</b></p></body></html>",
            encoding="utf-8",
        )

        docs = loader._load_html(str(path))

    assert len(docs) == 1
    assert "Title" in docs[0].text
    assert "Hello GraphRAG" in docs[0].text
    assert "alert" not in docs[0].text


def test_load_doc_uses_converted_docx_text(monkeypatch):
    loader = DocumentLoader()
    monkeypatch.setattr(loader, "_convert_doc_to_docx_text", lambda path: "converted text")

    docs = loader._load_doc("/tmp/legacy.doc")

    assert len(docs) == 1
    assert docs[0].text == "converted text"
    assert docs[0].metadata["file_name"] == "legacy.doc"


def test_load_doc_falls_back_to_legacy_extractors(monkeypatch):
    loader = DocumentLoader()
    monkeypatch.setattr(loader, "_convert_doc_to_docx_text", lambda path: None)
    monkeypatch.setattr(loader, "_extract_doc_with_legacy_tools", lambda path: "legacy text")

    docs = loader._load_doc("/tmp/legacy.doc")

    assert len(docs) == 1
    assert docs[0].text == "legacy text"


def test_load_doc_raises_when_no_parser_available(monkeypatch):
    loader = DocumentLoader()
    monkeypatch.setattr(loader, "_convert_doc_to_docx_text", lambda path: None)
    monkeypatch.setattr(loader, "_extract_doc_with_legacy_tools", lambda path: None)

    with pytest.raises(ValueError, match="Legacy \\.doc parsing requires LibreOffice"):
        loader._load_doc("/tmp/legacy.doc")
