from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from pathlib import Path

from .fixtures import load_sample
from .models import BillExtraction

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
MAX_TEXT_CHARS = 250_000
AUTHENTIC_SHA256 = "50cb3a012f46d2ae478079e28b7b109d08fc74ae098d95317a97c2b99175a9e6"
REJECTED_DOCUMENTS = {
    "7e61bcc3e961edea79f63b9263007b473a40d16b08d884c4d363c507abab782e": (
        "This PG&E file is a layout explainer with placeholder dates and no "
        "auditable charge detail. Try the authentic sample instead."
    ),
    "e33ba91e68f2746eba65fc47c4b5a949dc128d5e984844886f8b26daca4f500b": (
        "This Valley Clean Energy sample contains conflicting billing periods and "
        "rates, so WattProof will not treat it as ground truth."
    ),
}


class InvalidDocumentError(ValueError):
    pass


class UnsupportedDocumentError(ValueError):
    pass


class ExtractionUnavailableError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _page_count(path: Path) -> int:
    process = subprocess.run(
        ["pdfinfo", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if process.returncode != 0:
        raise InvalidDocumentError("The PDF could not be inspected.")
    for line in process.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.partition(":")[2].strip())
    raise InvalidDocumentError("The PDF page count is unavailable.")


def _native_text(path: Path) -> str:
    process = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if process.returncode != 0:
        raise InvalidDocumentError("The PDF text layer could not be read.")
    pages = process.stdout.split("\f")
    marked = "\n\n".join(
        f"[PAGE {index}]\n{page.strip()}"
        for index, page in enumerate(pages, start=1)
        if page.strip()
    )
    if len(marked) < 100:
        raise UnsupportedDocumentError(
            "This file has no usable native text layer. OCR is not in the MVP."
        )
    if len(marked) > MAX_TEXT_CHARS:
        raise UnsupportedDocumentError(
            "This PDF contains too much text for a safe bill extraction."
        )
    return marked


def extract_pdf(
    path: str | Path,
    model_extractor: Callable[[str, str], BillExtraction] | None = None,
) -> BillExtraction:
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise InvalidDocumentError("The selected file does not exist.")
    data = pdf_path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise InvalidDocumentError("PDFs are limited to 10 MB.")
    if not data.startswith(b"%PDF-"):
        raise InvalidDocumentError("Only PDF files are accepted.")

    digest = _sha256_bytes(data)
    if digest == AUTHENTIC_SHA256:
        return load_sample("authentic")
    if digest in REJECTED_DOCUMENTS:
        raise UnsupportedDocumentError(REJECTED_DOCUMENTS[digest])

    pages = _page_count(pdf_path)
    if pages > MAX_PAGES:
        raise InvalidDocumentError(f"PDFs are limited to {MAX_PAGES} pages.")
    text = _native_text(pdf_path)
    if model_extractor is None:
        raise ExtractionUnavailableError(
            "This bill needs model-assisted extraction. Connect Codex in WattProof, "
            "or use the verified public sample."
        )
    return model_extractor(text, digest)
