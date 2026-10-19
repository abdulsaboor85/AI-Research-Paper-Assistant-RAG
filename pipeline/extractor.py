"""
extractor.py  -  read the text out of a PDF file.

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
1. We first try PyMuPDF. It is fast.
2. If we get almost no text (less than 100 letters), the PDF is odd.
   Then we try pdfplumber as a backup.
3. A PDF made of pictures only (a scan) has no text. We cannot read it (no OCR).

FUNCTION GUIDE
------------------------------------------------------------
   extract_text_pymupdf      read the text with PyMuPDF
   extract_text_pdfplumber   read the text with pdfplumber (backup)
   extract_text              try the first way, then the backup
"""

import fitz            # this is PyMuPDF
import pdfplumber

MIN_TEXT_LENGTH = 100   # less text than this means "could not read the PDF"


def extract_text_pymupdf(pdf_path):
    parts = []
    with fitz.open(pdf_path) as document:
        for page in document:
            parts.append(page.get_text())
    return "".join(parts)


def extract_text_pdfplumber(pdf_path):
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                parts.append(page_text + "\n")
    return "".join(parts)


def extract_text(pdf_path):
    text = extract_text_pymupdf(pdf_path).strip()
    if len(text) < MIN_TEXT_LENGTH:
        text = extract_text_pdfplumber(pdf_path).strip()
    return text