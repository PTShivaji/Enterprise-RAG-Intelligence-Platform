"""Render the PDF and DOCX documents of the sample corpus from their Markdown sources.

The generated binaries are committed so evaluations are reproducible without this
script; re-run it only after editing ``evaluation/datasets/sources/*.md``.

Usage (from the repository root, with the backend virtualenv):
    backend\\.venv\\Scripts\\python.exe evaluation\\scripts\\build_sample_corpus.py
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
from docx import Document

ROOT = Path(__file__).resolve().parents[1] / "datasets"
SOURCES = ROOT / "sources"
CORPUS = ROOT / "sample_corpus"


def _blocks(markdown: str) -> list[tuple[str, str]]:
    """Split Markdown into (kind, text) blocks: h1, h2, li, p, page."""
    out: list[tuple[str, str]] = []
    for raw in markdown.strip().split("\n\n"):
        block = raw.strip()
        if block == "=== PAGE ===":
            out.append(("page", ""))
        elif block.startswith("## "):
            out.append(("h2", block[3:]))
        elif block.startswith("# "):
            out.append(("h1", block[2:]))
        elif all(line.startswith("- ") for line in block.splitlines()):
            out.extend(("li", line[2:]) for line in block.splitlines())
        else:
            out.append(("p", " ".join(block.splitlines())))
    return out


def build_pdf(source: Path, target: Path) -> None:
    doc = pymupdf.open()
    doc.set_metadata({"title": source.stem.replace("_", " ").title(), "author": "Northwind Energy"})
    page = doc.new_page()
    y = 60.0
    sizes = {"h1": 18, "h2": 14, "p": 10.5, "li": 10.5}
    for kind, text in _blocks(source.read_text(encoding="utf-8")):
        if kind == "page":
            page, y = doc.new_page(), 60.0
            continue
        size = sizes[kind]
        text = f"• {text}" if kind == "li" else text
        rect = pymupdf.Rect(60, y, 540, 800)
        spare = page.insert_textbox(rect, text, fontsize=size, fontname="hebo" if kind.startswith("h") else "helv")
        if spare < 0:
            raise RuntimeError(f"Block does not fit on page: {text[:40]}")
        used = (rect.height - spare)
        y += used + (14 if kind.startswith("h") else 8)
    doc.save(target, garbage=4, deflate=True)
    doc.close()


def build_docx(source: Path, target: Path) -> None:
    doc = Document()
    doc.core_properties.title = "Information Security Policy"
    doc.core_properties.author = "Northwind Energy"
    for kind, text in _blocks(source.read_text(encoding="utf-8")):
        if kind == "h1":
            doc.add_heading(text, level=1)
        elif kind == "h2":
            doc.add_heading(text, level=2)
        elif kind == "li":
            doc.add_paragraph(text, style="List Bullet")
        elif kind == "p":
            doc.add_paragraph(text)
    doc.save(target)


if __name__ == "__main__":
    CORPUS.mkdir(parents=True, exist_ok=True)
    build_pdf(SOURCES / "si5000_inverter_manual.md", CORPUS / "si5000_inverter_manual.pdf")
    build_docx(SOURCES / "it_security_policy.md", CORPUS / "it_security_policy.docx")
    print("Built:", *(p.name for p in sorted(CORPUS.iterdir())), sep="\n  ")
