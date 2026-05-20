"""Extract text from PDF files."""

import fitz
import pdfplumber

MIN_TEXT_LENGTH = 100


def extract_text_pymupdf(pdf_path: str) -> str:
    text_parts = []
    with fitz.open(pdf_path) as document:
        for page in document:
            text_parts.append(page.get_text())
    return "".join(text_parts)


def extract_text_pdfplumber(pdf_path: str) -> str:
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text + "\n")
    return "".join(text_parts)


def extract_text(pdf_path: str) -> str:
    text = extract_text_pymupdf(pdf_path).strip()
    if len(text) < MIN_TEXT_LENGTH:
        text = extract_text_pdfplumber(pdf_path).strip()
    return text
