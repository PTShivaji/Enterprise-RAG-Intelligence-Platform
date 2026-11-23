"""File validation and PDF / DOCX / TXT extraction."""

from __future__ import annotations

import pytest

from app.core.exceptions import DocumentParsingError, UnsupportedMediaError
from app.ingestion.cleaning import normalize_text
from app.ingestion.parsers import detect_file_type, parse_document
from tests.factories import LEAVE_POLICY_TXT, make_docx, make_pdf


class TestFileValidation:
    def test_accepts_matching_magic_bytes(self) -> None:
        assert detect_file_type("report.PDF", b"%PDF-1.7") == "pdf"
        assert detect_file_type("policy.docx", b"PK\x03\x04") == "docx"
        assert detect_file_type("notes.txt", b"hello") == "txt"
        assert detect_file_type("readme.md", b"# hi") == "txt"

    @pytest.mark.parametrize("name", ["malware.exe", "image.png", "noextension", "archive.zip"])
    def test_rejects_unsupported_extensions(self, name: str) -> None:
        with pytest.raises(UnsupportedMediaError):
            detect_file_type(name, b"whatever")

    def test_rejects_spoofed_extension(self) -> None:
        with pytest.raises(UnsupportedMediaError):
            detect_file_type("fake.pdf", b"MZ\x90\x00")  # Windows executable renamed to .pdf
        with pytest.raises(UnsupportedMediaError):
            detect_file_type("fake.txt", b"%PDF-1.4")


class TestPdf:
    def test_extracts_pages_and_headings(self) -> None:
        parsed = parse_document("pdf", make_pdf())
        assert parsed.page_count == 2
        assert "SI-5000" in parsed.text
        assert "2.5 Nm" in parsed.text
        titles = [s.title for s in parsed.sections]
        assert "Quarterly Inspection" in titles
        # Offset -> page mapping is exact.
        assert parsed.page_at(parsed.text.index("SI-5000")) == 1
        assert parsed.page_at(parsed.text.index("2.5 Nm")) == 2

    def test_corrupted_pdf_raises_clean_error(self) -> None:
        with pytest.raises(DocumentParsingError):
            parse_document("pdf", b"%PDF-1.4 this is not really a pdf")


class TestDocx:
    def test_extracts_headings_paragraphs_and_tables(self) -> None:
        parsed = parse_document("docx", make_docx())
        assert "14 characters" in parsed.text
        assert "Restricted | Encrypted storage only" in parsed.text
        assert [s.title for s in parsed.sections] == ["IT Security Policy", "Remote Access"]
        assert parsed.page_count is None  # DOCX has no fixed pages: never invent them
        mfa = parsed.text.index("Multi-factor")
        assert parsed.section_at(mfa) == "Remote Access"

    def test_corrupted_docx_raises_clean_error(self) -> None:
        with pytest.raises(DocumentParsingError):
            parse_document("docx", b"PK\x03\x04garbage")


class TestTxt:
    def test_markdown_headings_become_sections(self) -> None:
        parsed = parse_document("txt", LEAVE_POLICY_TXT.encode())
        assert [s.title for s in parsed.sections][:3] == ["Leave Policy", "Annual Leave", "Carry Over"]
        assert parsed.section_at(parsed.text.index("10 days of paid sick")) == "Sick Leave"

    def test_decodes_utf16_and_latin1(self) -> None:
        assert "café" in parse_document("txt", "café policy".encode("utf-16")).text
        assert "café" in parse_document("txt", "café policy".encode("latin-1")).text

    def test_empty_text_raises(self) -> None:
        with pytest.raises(DocumentParsingError):
            parse_document("txt", b"   \n\n  ")


def test_normalize_text_repairs_common_artifacts() -> None:
    raw = "The main-\ntenance ﬁle\r\nhas   extra\t spaces\n\n\n\nNew para"
    assert normalize_text(raw) == "The maintenance file\nhas extra spaces\n\nNew para"
