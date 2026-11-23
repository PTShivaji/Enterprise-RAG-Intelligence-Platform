"""Parser registry and upload validation (extension + magic-byte sniffing)."""

from __future__ import annotations

from collections.abc import Callable

from app.core.exceptions import UnsupportedMediaError
from app.ingestion.parsers.base import ParsedDocument
from app.ingestion.parsers.docx import parse_docx
from app.ingestion.parsers.pdf import parse_pdf
from app.ingestion.parsers.txt import parse_txt

Parser = Callable[[bytes], ParsedDocument]

PARSERS: dict[str, Parser] = {"pdf": parse_pdf, "docx": parse_docx, "txt": parse_txt}
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
}
_EXTENSION_ALIASES = {"md": "txt", "markdown": "txt", "text": "txt"}


def detect_file_type(filename: str, head: bytes) -> str:
    """Determine the file type from the extension AND verify it against magic bytes.

    Trusting the client-supplied extension or Content-Type alone would let
    arbitrary binaries through, so the leading bytes must agree with the extension.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    ext = _EXTENSION_ALIASES.get(ext, ext)
    if ext not in PARSERS:
        raise UnsupportedMediaError(
            f"Unsupported file type '.{ext}'. Allowed: PDF, DOCX, TXT",
            details={"allowed": sorted(PARSERS)},
        )
    if ext == "pdf" and not head.startswith(b"%PDF-"):
        raise UnsupportedMediaError("File content is not a valid PDF")
    if ext == "docx" and not head.startswith(b"PK\x03\x04"):
        raise UnsupportedMediaError("File content is not a valid DOCX (ZIP) document")
    if ext == "txt" and (head.startswith((b"%PDF-", b"PK\x03\x04", b"MZ", b"\x7fELF"))):
        raise UnsupportedMediaError("File content is binary, not plain text")
    return ext


def parse_document(file_type: str, data: bytes) -> ParsedDocument:
    """Dispatch to the parser registered for ``file_type``."""
    try:
        parser = PARSERS[file_type]
    except KeyError as exc:
        raise UnsupportedMediaError(f"No parser for file type '{file_type}'") from exc
    return parser(data)


__all__ = ["CONTENT_TYPES", "PARSERS", "ParsedDocument", "detect_file_type", "parse_document"]
