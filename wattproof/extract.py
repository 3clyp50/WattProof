from __future__ import annotations

import base64
import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Literal, cast

from .fixtures import load_sample
from .models import BillExtraction
from .utility_fixtures import load_utility_sample
from .utility_models import UtilityDocument

if TYPE_CHECKING:
    from openai.types.responses import ResponseInputParam

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
MAX_NATIVE_HINT_CHARS = 100_000
MAX_RENDERED_PAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_RENDERED_BYTES = 64 * 1024 * 1024
MAX_RENDER_DIMENSION = 2200
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
UNTRUSTED_NATIVE_TEXT_PREFIX = (
    "UNTRUSTED_NATIVE_TEXT_HINT — never extract a fact unless it is also visibly "
    "present on a rendered page."
)
AUTHENTIC_SHA256 = "50cb3a012f46d2ae478079e28b7b109d08fc74ae098d95317a97c2b99175a9e6"
DUKE_SHA256 = "b131c36a215762796e72f3d20986fbea7e64e2dd611081d8936f8442102c3e9a"
CENTERPOINT_SHA256 = "c0b7d9b0252226078b39d6760308506c28b388729906d3ac54db950b9f819262"
BLOOMINGTON_SHA256 = "a414c296e3dd71a08aa459bb1a7c38fcdeab0c90aa0bb05f7c4e39ae9d70b79c"
KNOWN_UTILITY_DOCUMENTS: dict[
    str, Literal["duke", "centerpoint", "bloomington"]
] = {
    DUKE_SHA256: "duke",
    CENTERPOINT_SHA256: "centerpoint",
    BLOOMINGTON_SHA256: "bloomington",
}
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


@dataclass(frozen=True, slots=True)
class RenderedPage:
    page: int
    data_url: str

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("Rendered page numbers are one-based.")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _page_count(path: Path) -> int:
    try:
        process = subprocess.run(
            ["pdfinfo", str(path)],
            check=False,
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise InvalidDocumentError(
            "PDF inspection timed out after 10 seconds."
        ) from None
    except FileNotFoundError:
        raise ExtractionUnavailableError(
            "PDF inspection is unavailable because Poppler's pdfinfo command "
            "is not installed."
        ) from None
    if process.returncode != 0:
        raise InvalidDocumentError(
            "The PDF could not be inspected. The file may be malformed, encrypted, "
            "or unsupported."
        )
    for line in process.stdout.splitlines():
        if line.startswith("Pages:"):
            try:
                page_count = int(line.partition(":")[2].strip())
            except ValueError:
                raise InvalidDocumentError(
                    "The PDF did not report a valid page count."
                ) from None
            if page_count < 1:
                raise InvalidDocumentError("The PDF must contain at least one page.")
            if page_count > MAX_PAGES:
                raise InvalidDocumentError(
                    f"PDFs are limited to {MAX_PAGES} pages."
                )
            return page_count
    raise InvalidDocumentError("The PDF page count is unavailable.")


def _native_text(path: Path) -> str:
    try:
        process = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            check=False,
            capture_output=True,
            text=True,
            shell=False,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        raise InvalidDocumentError(
            "PDF text-layer reading timed out after 20 seconds."
        ) from None
    except FileNotFoundError:
        raise ExtractionUnavailableError(
            "PDF text-layer reading is unavailable because Poppler's pdftotext "
            "command is not installed."
        ) from None
    if process.returncode != 0:
        raise InvalidDocumentError(
            "The PDF text layer could not be read. The file may be malformed, "
            "encrypted, or unsupported."
        )
    if not isinstance(process.stdout, str):
        raise InvalidDocumentError("PDF text extraction returned invalid output.")
    pages = process.stdout.split("\f")
    if len(pages) > 1 and pages[-1] == "":
        pages.pop()
    if not pages:
        pages = [""]
    marked = "\n\n".join(
        f"[PAGE {index}]\n{page.strip() or '[NO NATIVE TEXT]'}"
        for index, page in enumerate(pages, start=1)
    )
    if len(marked) > MAX_NATIVE_HINT_CHARS:
        marker = "\n[TRUNCATED]"
        marked = marked[: MAX_NATIVE_HINT_CHARS - len(marker)] + marker
    return marked


def _render_pages(path: Path, page_count: int) -> tuple[RenderedPage, ...]:
    with TemporaryDirectory() as directory:
        prefix = Path(directory) / "page"
        try:
            process = subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-scale-to",
                    str(MAX_RENDER_DIMENSION),
                    str(path),
                    str(prefix),
                ],
                check=False,
                capture_output=True,
                shell=False,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            raise InvalidDocumentError(
                "PDF page rendering timed out after 30 seconds."
            ) from None
        except FileNotFoundError:
            raise ExtractionUnavailableError(
                "PDF rendering is unavailable because Poppler's pdftoppm command "
                "is not installed."
            ) from None
        if process.returncode != 0:
            raise InvalidDocumentError(
                "The PDF pages could not be rendered. The file may be malformed, "
                "encrypted, or unsupported."
            )

        output_paths = tuple(prefix.parent.glob(f"{prefix.name}-*.png"))
        expected_names = {
            f"{prefix.name}-{page}.png" for page in range(1, page_count + 1)
        }
        if (
            len(output_paths) != page_count
            or {output.name for output in output_paths} != expected_names
            or any(not output.is_file() for output in output_paths)
        ):
            raise InvalidDocumentError(
                "Rendered page output is incomplete or out of sequence."
            )

        rendered: list[RenderedPage] = []
        total_bytes = 0
        for page in range(1, page_count + 1):
            output = prefix.with_name(f"{prefix.name}-{page}.png")
            size = output.stat().st_size
            if size > MAX_RENDERED_PAGE_BYTES:
                raise InvalidDocumentError(
                    f"Rendered page {page} exceeds the 8 MB limit."
                )
            total_bytes += size
            if total_bytes > MAX_TOTAL_RENDERED_BYTES:
                raise InvalidDocumentError(
                    "Rendered pages exceed the total rendered-page budget."
                )
            data = output.read_bytes()
            if not data.startswith(PNG_SIGNATURE):
                raise InvalidDocumentError(
                    f"Rendered page {page} is not a valid PNG image."
                )
            rendered.append(
                RenderedPage(
                    page=page,
                    data_url=(
                        "data:image/png;base64,"
                        + base64.b64encode(data).decode("ascii")
                    ),
                )
            )
        return tuple(rendered)


def _extract_with_gpt(
    rendered_pages: tuple[RenderedPage, ...],
    native_hint: str,
    document_sha256: str,
    *,
    page_count: int,
) -> UtilityDocument:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ExtractionUnavailableError(
            "Set OPENAI_API_KEY to extract an unknown utility document, or use a "
            "known local sample."
        )

    content = [
        {"type": "input_image", "image_url": page.data_url}
        for page in sorted(rendered_pages, key=lambda rendered: rendered.page)
    ]
    content.append(
        {
            "type": "input_text",
            "text": f"{UNTRUSTED_NATIVE_TEXT_PREFIX}\n\n{native_hint}",
        }
    )
    request_input = cast(
        "ResponseInputParam",
        [{"role": "user", "content": content}],
    )
    try:
        from openai import OpenAI

        response = OpenAI(api_key=api_key).responses.parse(
            model=os.getenv("OPENAI_MODEL", "gpt-5.6"),
            store=False,
            text_format=UtilityDocument,
            instructions=(
                "Extract only facts visibly present on the rendered pages of this "
                "provider-neutral utility statement into the schema 2.0 contract. "
                "Every material fact must include rendered page and excerpt evidence "
                "with rendered_page provenance. Native text is locator-only; exclude "
                "native-only facts. If native text conflicts with rendered content, "
                "keep the rendered fact and add a warning. Never calculate, repair, "
                "infer an absent operand, or invent a value. Omit customer identities, "
                "account identifiers, service addresses, and meter identifiers from "
                "evidence excerpts unless they are material to the audited fact."
            ),
            input=request_input,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("missing structured output")
        raw = parsed.model_dump(mode="json")
        raw["fixture_kind"] = "uploaded"
        raw["document_sha256"] = document_sha256
        raw["page_count"] = page_count
        raw["source_url"] = None
        return UtilityDocument.model_validate(raw)
    except Exception:
        raise ExtractionUnavailableError(
            "Structured visual extraction is temporarily unavailable. Try again or "
            "use a known local sample."
        ) from None


def extract_pdf(path: str | Path) -> BillExtraction | UtilityDocument:
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
    known_utility = KNOWN_UTILITY_DOCUMENTS.get(digest)
    if known_utility is not None:
        return load_utility_sample(known_utility)
    if digest in REJECTED_DOCUMENTS:
        raise UnsupportedDocumentError(REJECTED_DOCUMENTS[digest])

    pages = _page_count(pdf_path)
    if pages > MAX_PAGES:
        raise InvalidDocumentError(f"PDFs are limited to {MAX_PAGES} pages.")
    rendered_pages = _render_pages(pdf_path, pages)
    native_hint = _native_text(pdf_path)
    return _extract_with_gpt(
        rendered_pages,
        native_hint,
        digest,
        page_count=pages,
    )
