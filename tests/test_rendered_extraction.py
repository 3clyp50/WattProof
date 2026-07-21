from __future__ import annotations

import base64
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from wattproof.extract import (
    AUTHENTIC_SHA256,
    MAX_RENDERED_PAGE_BYTES,
    ExtractionUnavailableError,
    InvalidDocumentError,
    RenderedPage,
    _extract_with_gpt,
    _native_text,
    _page_count,
    _render_pages,
    extract_pdf,
)
from wattproof.fixtures import load_sample
from wattproof.utility_fixtures import load_utility_sample
from wattproof.utility_models import UtilityDocument

UNTRUSTED_PREFIX = (
    "UNTRUSTED_NATIVE_TEXT_HINT — never extract a fact unless it is also visibly "
    "present on a rendered page."
)


def _install_fake_openai(
    monkeypatch: pytest.MonkeyPatch,
    parsed: object,
) -> dict[str, object]:
    call: dict[str, object] = {}

    class FakeResponses:
        def parse(self, **kwargs: object) -> SimpleNamespace:
            call.update(kwargs)
            return SimpleNamespace(output_parsed=parsed)

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    return call


@pytest.mark.parametrize(
    ("kind", "digest"),
    [
        (
            "duke",
            "b131c36a215762796e72f3d20986fbea7e64e2dd611081d8936f8442102c3e9a",
        ),
        (
            "centerpoint",
            "c0b7d9b0252226078b39d6760308506c28b388729906d3ac54db950b9f819262",
        ),
        (
            "bloomington",
            "a414c296e3dd71a08aa459bb1a7c38fcdeab0c90aa0bb05f7c4e39ae9d70b79c",
        ),
    ],
)
def test_known_utility_hash_uses_exact_local_fixture_before_external_tools(
    kind: str,
    digest: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "bill.pdf"
    candidate.write_bytes(b"%PDF-placeholder")
    monkeypatch.setattr("wattproof.extract._sha256_bytes", lambda _data: digest)

    def unexpected_external_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("known documents must not invoke Poppler")

    monkeypatch.setattr("wattproof.extract.subprocess.run", unexpected_external_call)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert extract_pdf(candidate) == load_utility_sample(kind)  # type: ignore[arg-type]


@pytest.mark.parametrize("stdout", ["small text\f", "\f", ""])
def test_native_text_keeps_short_and_empty_pages_as_labeled_hints(
    stdout: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "wattproof.extract.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=stdout,
            stderr="",
        ),
    )

    hint = _native_text(Path("bill.pdf"))

    assert hint.startswith("[PAGE 1]\n")


def test_native_text_hint_is_capped_at_one_hundred_thousand_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "wattproof.extract.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="x" * 120_000,
            stderr="",
        ),
    )

    hint = _native_text(Path("bill.pdf"))

    assert hint.startswith("[PAGE 1]\n")
    assert len(hint) <= 100_000


def test_rendered_page_is_frozen_slotted_and_one_based() -> None:
    page = RenderedPage(page=1, data_url="data:image/png;base64,AA==")

    assert not hasattr(page, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(page, "page", 2)
    with pytest.raises(ValueError, match="one-based"):
        RenderedPage(page=0, data_url="data:image/png;base64,AA==")


def test_render_pages_builds_ordered_data_urls_before_temporary_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command_call: dict[str, Any] = {}
    render_directory: Path | None = None
    pngs = (b"\x89PNG\r\n\x1a\nfirst", b"\x89PNG\r\n\x1a\nsecond")

    def render(command: list[str], **kwargs: object) -> SimpleNamespace:
        nonlocal render_directory
        command_call["command"] = command
        command_call.update(kwargs)
        prefix = Path(command[-1])
        render_directory = prefix.parent
        for page, data in enumerate(pngs, start=1):
            prefix.with_name(f"{prefix.name}-{page}.png").write_bytes(data)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("wattproof.extract.subprocess.run", render)

    rendered = _render_pages(Path("bill.pdf"), page_count=2)

    assert [page.page for page in rendered] == [1, 2]
    assert [base64.b64decode(page.data_url.partition(",")[2]) for page in rendered] == list(
        pngs
    )
    assert all(page.data_url.startswith("data:image/png;base64,") for page in rendered)
    assert command_call["command"][:5] == [
        "pdftoppm",
        "-png",
        "-scale-to",
        "2200",
        "bill.pdf",
    ]
    assert command_call["shell"] is False
    assert command_call["timeout"] == 30
    assert render_directory is not None
    assert not render_directory.exists()


def test_render_pages_accepts_zero_padded_names_in_numeric_page_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render_padded(command: list[str], **_kwargs: object) -> SimpleNamespace:
        prefix = Path(command[-1])
        for page in range(1, 12):
            prefix.with_name(f"{prefix.name}-{page:02}.png").write_bytes(
                b"\x89PNG\r\n\x1a\n" + bytes([page])
            )
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("wattproof.extract.subprocess.run", render_padded)

    rendered = _render_pages(Path("bill.pdf"), page_count=11)

    assert [page.page for page in rendered] == list(range(1, 12))
    assert [
        base64.b64decode(page.data_url.partition(",")[2])[-1] for page in rendered
    ] == list(range(1, 12))


def test_render_pages_converts_timeout_to_safe_document_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(
            cmd="pdftoppm private-customer-file.pdf",
            timeout=30,
            stderr=b"account 123 secret output",
        )

    monkeypatch.setattr("wattproof.extract.subprocess.run", timeout)

    with pytest.raises(InvalidDocumentError, match="rendering timed out") as error:
        _render_pages(Path("bill.pdf"), page_count=1)

    assert "private-customer" not in str(error.value)
    assert "account 123" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_render_pages_converts_nonzero_exit_to_safe_document_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "wattproof.extract.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=b"private document text and account 123",
        ),
    )

    with pytest.raises(InvalidDocumentError, match="could not be rendered") as error:
        _render_pages(Path("bill.pdf"), page_count=1)

    assert "private document" not in str(error.value)
    assert "account 123" not in str(error.value)


def test_render_pages_reports_missing_poppler_without_raw_os_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_command(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("private executable lookup details")

    monkeypatch.setattr("wattproof.extract.subprocess.run", missing_command)

    with pytest.raises(
        ExtractionUnavailableError,
        match="pdftoppm.*not installed",
    ) as error:
        _render_pages(Path("bill.pdf"), page_count=1)

    assert "private executable" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_render_pages_rejects_missing_page_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render_one_page(command: list[str], **_kwargs: object) -> SimpleNamespace:
        prefix = Path(command[-1])
        prefix.with_name(f"{prefix.name}-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("wattproof.extract.subprocess.run", render_one_page)

    with pytest.raises(InvalidDocumentError, match="incomplete or out of sequence"):
        _render_pages(Path("bill.pdf"), page_count=2)


def test_render_pages_rejects_duplicate_or_unexpected_page_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render_duplicate(command: list[str], **_kwargs: object) -> SimpleNamespace:
        prefix = Path(command[-1])
        prefix.with_name(f"{prefix.name}-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        prefix.with_name(f"{prefix.name}-01.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("wattproof.extract.subprocess.run", render_duplicate)

    with pytest.raises(InvalidDocumentError, match="incomplete or out of sequence"):
        _render_pages(Path("bill.pdf"), page_count=1)


@pytest.mark.parametrize(
    ("names", "page_count"),
    [
        (("page-final.png",), 1),
        (("page-0.png",), 1),
        (("page-2.png",), 1),
        (("page-1.png", "page-2.png"), 1),
    ],
)
def test_render_pages_rejects_invalid_or_out_of_range_numeric_suffixes(
    names: tuple[str, ...],
    page_count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render_invalid_names(
        command: list[str], **_kwargs: object
    ) -> SimpleNamespace:
        prefix = Path(command[-1])
        for name in names:
            prefix.with_name(name).write_bytes(b"\x89PNG\r\n\x1a\n")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("wattproof.extract.subprocess.run", render_invalid_names)

    with pytest.raises(InvalidDocumentError, match="incomplete or out of sequence"):
        _render_pages(Path("bill.pdf"), page_count=page_count)


def test_render_pages_rejects_non_png_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render_invalid(command: list[str], **_kwargs: object) -> SimpleNamespace:
        prefix = Path(command[-1])
        prefix.with_name(f"{prefix.name}-1.png").write_bytes(b"not a png")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("wattproof.extract.subprocess.run", render_invalid)

    with pytest.raises(InvalidDocumentError, match="page 1 is not a valid PNG"):
        _render_pages(Path("bill.pdf"), page_count=1)


def test_render_pages_rejects_oversized_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render_oversized(command: list[str], **_kwargs: object) -> SimpleNamespace:
        prefix = Path(command[-1])
        prefix.with_name(f"{prefix.name}-1.png").write_bytes(
            b"\x89PNG\r\n\x1a\n" + b"x" * (MAX_RENDERED_PAGE_BYTES - 7)
        )
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("wattproof.extract.subprocess.run", render_oversized)

    with pytest.raises(InvalidDocumentError, match="page 1 exceeds the 8 MB limit"):
        _render_pages(Path("bill.pdf"), page_count=1)


def test_render_pages_enforces_total_render_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render_two_pages(command: list[str], **_kwargs: object) -> SimpleNamespace:
        prefix = Path(command[-1])
        for page in (1, 2):
            prefix.with_name(f"{prefix.name}-{page}.png").write_bytes(
                b"\x89PNG\r\n\x1a\n"
            )
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("wattproof.extract.subprocess.run", render_two_pages)
    monkeypatch.setattr("wattproof.extract.MAX_TOTAL_RENDERED_BYTES", 15)

    with pytest.raises(InvalidDocumentError, match="total rendered-page budget"):
        _render_pages(Path("bill.pdf"), page_count=2)


def test_page_count_uses_bounded_pdfinfo_without_a_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call: dict[str, Any] = {}

    def inspect(command: list[str], **kwargs: object) -> SimpleNamespace:
        call["command"] = command
        call.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="Pages:          2\n", stderr="")

    monkeypatch.setattr("wattproof.extract.subprocess.run", inspect)

    assert _page_count(Path("bill.pdf")) == 2
    assert call == {
        "command": ["pdfinfo", "bill.pdf"],
        "check": False,
        "capture_output": True,
        "text": True,
        "shell": False,
        "timeout": 10,
    }


def test_page_count_converts_timeout_to_safe_document_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(
            cmd="pdfinfo private-customer-file.pdf",
            timeout=10,
            stderr="account 123 secret output",
        )

    monkeypatch.setattr("wattproof.extract.subprocess.run", timeout)

    with pytest.raises(InvalidDocumentError, match="inspection timed out") as error:
        _page_count(Path("bill.pdf"))

    assert "private-customer" not in str(error.value)
    assert "account 123" not in str(error.value)


def test_page_count_reports_missing_pdfinfo_without_raw_os_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_command(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("private executable lookup details")

    monkeypatch.setattr("wattproof.extract.subprocess.run", missing_command)

    with pytest.raises(
        ExtractionUnavailableError,
        match="pdfinfo.*not installed",
    ) as error:
        _page_count(Path("bill.pdf"))

    assert "private executable" not in str(error.value)


def test_page_count_converts_nonzero_exit_to_safe_document_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "wattproof.extract.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="private bill text",
            stderr="account 123 encrypted",
        ),
    )

    with pytest.raises(InvalidDocumentError, match="malformed, encrypted") as error:
        _page_count(Path("bill.pdf"))

    assert "private bill" not in str(error.value)
    assert "account 123" not in str(error.value)


@pytest.mark.parametrize("stdout", [None, b"Pages: 1\n"])
def test_page_count_rejects_non_text_command_output(
    stdout: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "wattproof.extract.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=stdout,
            stderr="",
        ),
    )

    with pytest.raises(InvalidDocumentError, match="inspection returned invalid output"):
        _page_count(Path("bill.pdf"))


def test_page_count_converts_unicode_decode_failure_to_safe_document_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def undecodable(*_args: object, **_kwargs: object) -> None:
        raise UnicodeDecodeError(
            "utf-8",
            b"private account 123 \xff",
            20,
            21,
            "secret decoder detail",
        )

    monkeypatch.setattr("wattproof.extract.subprocess.run", undecodable)

    with pytest.raises(
        InvalidDocumentError,
        match="PDF inspection returned undecodable output",
    ) as error:
        _page_count(Path("bill.pdf"))

    assert "private" not in str(error.value)
    assert "account 123" not in str(error.value)
    assert "secret decoder" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


@pytest.mark.parametrize(
    ("stdout", "message"),
    [
        ("Title: sample\n", "page count is unavailable"),
        ("Pages: unknown\n", "valid page count"),
        ("Pages: 0\n", "at least one page"),
        ("Pages: 21\n", "limited to 20 pages"),
    ],
)
def test_page_count_rejects_malformed_or_out_of_range_output(
    stdout: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "wattproof.extract.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=stdout,
            stderr="",
        ),
    )

    with pytest.raises(InvalidDocumentError, match=message):
        _page_count(Path("bill.pdf"))


def test_native_text_uses_bounded_pdftotext_without_a_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call: dict[str, Any] = {}

    def read_text(command: list[str], **kwargs: object) -> SimpleNamespace:
        call["command"] = command
        call.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="visible locator", stderr="")

    monkeypatch.setattr("wattproof.extract.subprocess.run", read_text)

    assert _native_text(Path("bill.pdf")) == "[PAGE 1]\nvisible locator"
    assert call == {
        "command": ["pdftotext", "-layout", "bill.pdf", "-"],
        "check": False,
        "capture_output": True,
        "text": True,
        "shell": False,
        "timeout": 20,
    }


def test_native_text_converts_timeout_to_safe_document_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(
            cmd="pdftotext private-customer-file.pdf",
            timeout=20,
            stderr="account 123 secret output",
        )

    monkeypatch.setattr("wattproof.extract.subprocess.run", timeout)

    with pytest.raises(InvalidDocumentError, match="text-layer reading timed out") as error:
        _native_text(Path("bill.pdf"))

    assert "private-customer" not in str(error.value)
    assert "account 123" not in str(error.value)


def test_native_text_reports_missing_pdftotext_without_raw_os_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_command(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("private executable lookup details")

    monkeypatch.setattr("wattproof.extract.subprocess.run", missing_command)

    with pytest.raises(
        ExtractionUnavailableError,
        match="pdftotext.*not installed",
    ) as error:
        _native_text(Path("bill.pdf"))

    assert "private executable" not in str(error.value)


def test_native_text_converts_nonzero_exit_to_safe_document_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "wattproof.extract.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="private bill text",
            stderr="account 123 encrypted",
        ),
    )

    with pytest.raises(InvalidDocumentError, match="text layer could not be read") as error:
        _native_text(Path("bill.pdf"))

    assert "private bill" not in str(error.value)
    assert "account 123" not in str(error.value)


@pytest.mark.parametrize("stdout", [None, b"private bytes"])
def test_native_text_rejects_malformed_command_output(
    stdout: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "wattproof.extract.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=stdout,
            stderr="",
        ),
    )

    with pytest.raises(InvalidDocumentError, match="invalid output"):
        _native_text(Path("bill.pdf"))


def test_native_text_converts_unicode_decode_failure_to_safe_document_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def undecodable(*_args: object, **_kwargs: object) -> None:
        raise UnicodeDecodeError(
            "utf-8",
            b"private account 123 \xff",
            20,
            21,
            "secret decoder detail",
        )

    monkeypatch.setattr("wattproof.extract.subprocess.run", undecodable)

    with pytest.raises(
        InvalidDocumentError,
        match="PDF text extraction returned undecodable output",
    ) as error:
        _native_text(Path("bill.pdf"))

    assert "private" not in str(error.value)
    assert "account 123" not in str(error.value)
    assert "secret decoder" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_gpt_receives_rendered_evidence_before_the_untrusted_native_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = load_utility_sample("duke").model_copy(update={"page_count": 9})
    call = _install_fake_openai(monkeypatch, parsed)
    digest = "f" * 64
    native_only_value = "NATIVE ONLY CONFLICT $999.99"

    extracted = _extract_with_gpt(
        rendered_pages=(
            RenderedPage(page=1, data_url="data:image/png;base64,AA=="),
        ),
        native_hint=f"[PAGE 1]\n{native_only_value}",
        document_sha256=digest,
        page_count=3,
    )

    assert call["model"] == "gpt-5.6"
    assert call["store"] is False
    assert call["text_format"] is UtilityDocument
    messages = call["input"]
    assert isinstance(messages, list)
    assert len(messages) == 1
    message = messages[0]
    assert message["role"] == "user"
    content = message["content"]
    assert content[0] == {
        "type": "input_image",
        "image_url": "data:image/png;base64,AA==",
    }
    assert content[-1]["type"] == "input_text"
    assert content[-1]["text"].startswith(UNTRUSTED_PREFIX)
    assert native_only_value in content[-1]["text"]

    instructions = str(call["instructions"]).lower()
    assert "provider-neutral" in instructions
    assert "schema 2.0" in instructions
    assert "every material fact" in instructions
    assert "rendered page" in instructions
    assert "excerpt" in instructions
    assert "locator-only" in instructions
    assert "exclude native-only facts" in instructions
    assert "native text conflicts" in instructions
    assert "keep the rendered fact" in instructions
    assert "add a warning" in instructions
    assert "never calculate, repair, infer an absent operand, or invent" in instructions
    assert "identities" in instructions
    assert "account" in instructions
    assert "address" in instructions
    assert "meter identifiers" in instructions

    assert extracted.fixture_kind == "uploaded"
    assert extracted.document_sha256 == digest
    assert extracted.page_count == 3
    assert extracted.source_url is None
    assert extracted.warnings == parsed.warnings
    assert native_only_value not in extracted.model_dump_json()


def test_gpt_places_multiple_rendered_pages_in_page_order_before_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = _install_fake_openai(monkeypatch, load_utility_sample("duke"))

    _extract_with_gpt(
        rendered_pages=(
            RenderedPage(page=2, data_url="data:image/png;base64,Ag=="),
            RenderedPage(page=1, data_url="data:image/png;base64,AQ=="),
        ),
        native_hint="[PAGE 1]\none\n\n[PAGE 2]\ntwo",
        document_sha256="e" * 64,
        page_count=3,
    )

    messages = call["input"]
    assert isinstance(messages, list)
    content = messages[0]["content"]
    assert [block["image_url"] for block in content[:-1]] == [
        "data:image/png;base64,AQ==",
        "data:image/png;base64,Ag==",
    ]
    assert content[-1]["type"] == "input_text"


def test_gpt_requires_an_api_key_for_unknown_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ExtractionUnavailableError, match="OPENAI_API_KEY"):
        _extract_with_gpt(
            rendered_pages=(
                RenderedPage(page=1, data_url="data:image/png;base64,AA=="),
            ),
            native_hint="[PAGE 1]\ntext",
            document_sha256="d" * 64,
            page_count=1,
        )


def test_gpt_hides_api_failure_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingResponses:
        def parse(self, **_kwargs: object) -> None:
            raise RuntimeError("secret API token and private document text")

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            assert api_key == "test-key"
            self.responses = FailingResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    with pytest.raises(ExtractionUnavailableError, match="temporarily unavailable") as error:
        _extract_with_gpt(
            rendered_pages=(
                RenderedPage(page=1, data_url="data:image/png;base64,AA=="),
            ),
            native_hint="[PAGE 1]\ntext",
            document_sha256="c" * 64,
            page_count=1,
        )

    assert "secret API" not in str(error.value)
    assert "private document" not in str(error.value)


def test_gpt_treats_missing_parsed_output_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_openai(monkeypatch, None)

    with pytest.raises(ExtractionUnavailableError, match="temporarily unavailable"):
        _extract_with_gpt(
            rendered_pages=(
                RenderedPage(page=1, data_url="data:image/png;base64,AA=="),
            ),
            native_hint="[PAGE 1]\ntext",
            document_sha256="b" * 64,
            page_count=1,
        )


def test_gpt_rejects_model_evidence_beyond_trusted_page_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_openai(monkeypatch, load_utility_sample("duke"))

    with pytest.raises(ExtractionUnavailableError, match="temporarily unavailable"):
        _extract_with_gpt(
            rendered_pages=(
                RenderedPage(page=1, data_url="data:image/png;base64,AA=="),
            ),
            native_hint="[PAGE 1]\ntext",
            document_sha256="a" * 64,
            page_count=2,
        )


def test_authentic_pg_and_e_hash_remains_exact_and_keyless(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "bill.pdf"
    candidate.write_bytes(b"%PDF-placeholder")
    monkeypatch.setattr(
        "wattproof.extract._sha256_bytes",
        lambda _data: AUTHENTIC_SHA256,
    )

    def unexpected_external_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("known documents must not invoke Poppler")

    monkeypatch.setattr("wattproof.extract.subprocess.run", unexpected_external_call)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert extract_pdf(candidate) == load_sample("authentic")


@pytest.mark.parametrize(
    "native_hint",
    [
        "[PAGE 1]\n[NO NATIVE TEXT]",
        "[PAGE 1]\nshort locator",
    ],
)
def test_unknown_pdf_renders_before_using_empty_or_short_native_hint(
    native_hint: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "bill.pdf"
    candidate.write_bytes(b"%PDF-placeholder")
    digest = "9" * 64
    rendered = (
        RenderedPage(page=1, data_url="data:image/png;base64,AQ=="),
        RenderedPage(page=2, data_url="data:image/png;base64,Ag=="),
    )
    extracted = load_utility_sample("centerpoint")
    events: list[str] = []
    monkeypatch.setattr("wattproof.extract._sha256_bytes", lambda _data: digest)

    def page_count(_path: Path) -> int:
        events.append("page_count")
        return 2

    def render_pages(_path: Path, trusted_page_count: int) -> tuple[RenderedPage, ...]:
        events.append("render_pages")
        assert trusted_page_count == 2
        return rendered

    def native_text(_path: Path) -> str:
        events.append("native_text")
        return native_hint

    def extract_with_gpt(
        rendered_pages: tuple[RenderedPage, ...],
        received_hint: str,
        document_sha256: str,
        *,
        page_count: int,
    ) -> UtilityDocument:
        events.append("extract_with_gpt")
        assert rendered_pages == rendered
        assert received_hint == native_hint
        assert document_sha256 == digest
        assert page_count == 2
        return extracted

    monkeypatch.setattr("wattproof.extract._page_count", page_count)
    monkeypatch.setattr("wattproof.extract._render_pages", render_pages)
    monkeypatch.setattr("wattproof.extract._native_text", native_text)
    monkeypatch.setattr("wattproof.extract._extract_with_gpt", extract_with_gpt)

    assert extract_pdf(candidate) == extracted
    assert events == [
        "page_count",
        "render_pages",
        "native_text",
        "extract_with_gpt",
    ]


def test_unknown_pdf_does_not_fall_back_to_native_text_when_rendering_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "bill.pdf"
    candidate.write_bytes(b"%PDF-placeholder")
    monkeypatch.setattr("wattproof.extract._sha256_bytes", lambda _data: "8" * 64)
    monkeypatch.setattr("wattproof.extract._page_count", lambda _path: 1)

    def rendering_failed(_path: Path, _page_count: int) -> tuple[RenderedPage, ...]:
        raise InvalidDocumentError("Rendered evidence unavailable.")

    def native_text_must_not_run(_path: Path) -> str:
        raise AssertionError("native text cannot replace rendered evidence")

    monkeypatch.setattr("wattproof.extract._render_pages", rendering_failed)
    monkeypatch.setattr("wattproof.extract._native_text", native_text_must_not_run)

    with pytest.raises(InvalidDocumentError, match="Rendered evidence unavailable"):
        extract_pdf(candidate)
