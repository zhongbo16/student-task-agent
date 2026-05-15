from pathlib import Path

import fitz


def extract_text_from_pdf(file_path):
    text_parts = []
    document = fitz.open(file_path)

    try:
        for page in document:
            text_parts.append(page.get_text())
    finally:
        document.close()

    return "\n".join(text_parts).strip()


def get_file_metadata(file_path):
    path = Path(file_path)
    document = fitz.open(path)

    try:
        page_count = document.page_count
    finally:
        document.close()

    return {
        "filename": path.name,
        "file_size": path.stat().st_size,
        "page_count": page_count,
    }
