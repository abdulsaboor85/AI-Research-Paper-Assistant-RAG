import fitz  # PyMuPDF
import pdfplumber

def extract_text_pymupdf(pdf_path):
    text = ""
    doc = fitz.open(pdf_path)
    for page in doc:
        text += page.get_text()
    doc.close()
    return text

def extract_text_pdfplumber(pdf_path):
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

def extract_text(pdf_path):
    text = extract_text_pymupdf(pdf_path)
    
    # If PyMuPDF gives very little text, fall back to pdfplumber
    if len(text.strip()) < 100:
        text = extract_text_pdfplumber(pdf_path)
    
    return text.strip()