"""Builders for realistic test documents (PDF / DOCX / TXT) created in memory."""

from __future__ import annotations

import io

import pymupdf
from docx import Document

LEAVE_POLICY_TXT = """# Leave Policy

## Annual Leave

Employees with less than two years of service receive 18 days of paid annual leave per year.
Employees with two to five years of service receive 22 days of paid annual leave per year.
Employees with more than five years of service receive 26 days of paid annual leave.

## Carry Over

Up to 5 unused annual leave days may be carried over to the next year. Carried-over days expire on March 31.

## Sick Leave

Employees receive 10 days of paid sick leave per year. A medical certificate is required after three consecutive sick days.
"""

INVERTER_PAGES = [
    ("Inverter Maintenance Manual", [
        "This manual describes maintenance of the SI-5000 solar inverter.",
        "Always isolate the DC disconnect switch and wait five minutes for the capacitors to discharge before opening the enclosure.",
    ]),
    ("Quarterly Inspection", [
        "Inspect the cooling fan and air filters every quarter.",
        "Clean the air filters with compressed air every six months.",
        "Torque the DC terminals to 2.5 Nm during the annual inspection.",
    ]),
]


def make_pdf(pages: list[tuple[str, list[str]]] = INVERTER_PAGES) -> bytes:
    """Multi-page PDF: a large-font heading and body paragraphs on each page."""
    doc = pymupdf.open()
    for heading, paragraphs in pages:
        page = doc.new_page()
        y = 72
        page.insert_text((72, y), heading, fontsize=18)
        y += 36
        for para in paragraphs:
            rect = pymupdf.Rect(72, y, 540, y + 60)
            page.insert_textbox(rect, para, fontsize=11)
            y += 70
    data = doc.tobytes()
    doc.close()
    return data


def make_docx() -> bytes:
    doc = Document()
    doc.add_heading("IT Security Policy", level=1)
    doc.add_paragraph("All passwords must be at least 14 characters long.")
    doc.add_heading("Remote Access", level=2)
    doc.add_paragraph("Multi-factor authentication is required for all remote access to company systems.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Classification"
    table.cell(0, 1).text = "Handling"
    table.cell(1, 0).text = "Restricted"
    table.cell(1, 1).text = "Encrypted storage only"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
