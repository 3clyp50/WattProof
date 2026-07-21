from __future__ import annotations

import base64
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from wattproof.extract import (
    AUTHENTIC_SHA256,
    MAX_NATIVE_HINT_CHARS,
    MAX_RENDERED_PAGE_BYTES,
    ExtractionLoginRequiredError,
    ExtractionUnavailableError,
    InvalidDocumentError,
    RenderedPage,
    _native_text,
    _page_count,
    _render_pages,
    _validate_rendered_pages,
    extract_pdf,
)
from wattproof.fixtures import load_sample
from wattproof.utility_fixtures import load_utility_sample
from wattproof.utility_models import UtilityDocument

VALID_PNG_DATA_URL = (
    "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
)


def _valid_rendered_pages(page_count: int) -> tuple[RenderedPage, ...]:
    return tuple(
        RenderedPage(page=page, data_url=VALID_PNG_DATA_URL)
        for page in range(1, page_count + 1)
    )


def _install_live_process(
    monkeypatch: pytest.MonkeyPatch,
    script: str,
    arguments_for: Callable[[list[str]], list[str]],
    *,
    stdin_data: bytes | None = None,
) -> tuple[dict[str, object], list[subprocess.Popen[bytes]]]:
    real_popen = subprocess.Popen
    call: dict[str, object] = {}
    processes: list[subprocess.Popen[bytes]] = []

    def launch(command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        call["command"] = command
        call.update(kwargs)
        process = real_popen(
            [sys.executable, "-c", script, *arguments_for(command)],
            stdin=subprocess.PIPE if stdin_data is not None else None,
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            shell=False,
        )
        if stdin_data is not None:
            assert process.stdin is not None
            process.stdin.write(stdin_data)
            process.stdin.close()
        processes.append(process)
        return process

    monkeypatch.setattr("wattproof.extract.subprocess.Popen", launch)
    return call, processes


def _cleanup_live_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)


class _CompletedPopen:
    def __init__(self, returncode: int = 0, stdout: object | None = None) -> None:
        self.returncode = returncode
        self.stdout = stdout

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


def _install_live_output_process(
    monkeypatch: pytest.MonkeyPatch,
    output: bytes,
    *,
    returncode: int = 0,
) -> tuple[dict[str, object], list[subprocess.Popen[bytes]]]:
    script = """
import base64
import sys

sys.stdout.buffer.write(base64.b64decode(sys.stdin.buffer.read()))
sys.stdout.buffer.flush()
raise SystemExit(int(sys.argv[1]))
"""
    return _install_live_process(
        monkeypatch,
        script,
        lambda _command: [str(returncode)],
        stdin_data=base64.b64encode(output),
    )


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

    assert extract_pdf(candidate) == load_utility_sample(kind)  # type: ignore[arg-type]


def test_unknown_pdf_without_connected_codex_stops_before_poppler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "bill.pdf"
    candidate.write_bytes(b"%PDF-placeholder")
    monkeypatch.setattr("wattproof.extract._sha256_bytes", lambda _data: "7" * 64)

    def unexpected_expensive_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("disconnected unknown documents must stop before Poppler")

    for name in ("_page_count", "_render_pages", "_native_text"):
        monkeypatch.setattr(f"wattproof.extract.{name}", unexpected_expensive_call)

    with pytest.raises(ExtractionLoginRequiredError, match="Connect Codex"):
        extract_pdf(candidate)


def test_unknown_pdf_holds_process_local_slot_for_the_expensive_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "bill.pdf"
    candidate.write_bytes(b"%PDF-placeholder")
    events: list[object] = []

    class RecordingSlots:
        def acquire(self, *, blocking: bool) -> bool:
            events.append(("acquire", blocking))
            return True

        def release(self) -> None:
            events.append("release")

    monkeypatch.setattr("wattproof.extract._sha256_bytes", lambda _data: "6" * 64)
    monkeypatch.setattr(
        "wattproof.extract._EXTRACTION_SLOTS",
        RecordingSlots(),
        raising=False,
    )

    def page_count(_path: Path) -> int:
        events.append("page_count")
        return 1

    def render_pages(_path: Path, _count: int) -> tuple[RenderedPage, ...]:
        events.append("render")
        return _valid_rendered_pages(1)

    def native_text(_path: Path) -> str:
        events.append("native")
        return "[PAGE 1]\nhint"

    monkeypatch.setattr("wattproof.extract._page_count", page_count)
    monkeypatch.setattr("wattproof.extract._render_pages", render_pages)
    monkeypatch.setattr("wattproof.extract._native_text", native_text)
    expected = load_utility_sample("duke")

    def visual_extractor(
        _pages: tuple[RenderedPage, ...],
        _hint: str,
        _digest: str,
        _page_count: int,
    ) -> UtilityDocument:
        events.append("model")
        return expected

    assert extract_pdf(candidate, visual_extractor) == expected
    assert events == [
        ("acquire", False),
        "page_count",
        "render",
        "native",
        "model",
        "release",
    ]


def test_unknown_pdf_returns_busy_error_without_starting_expensive_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "bill.pdf"
    candidate.write_bytes(b"%PDF-placeholder")

    class BusySlots:
        def acquire(self, *, blocking: bool) -> bool:
            assert blocking is False
            return False

        def release(self) -> None:
            raise AssertionError("an unacquired slot must not be released")

    monkeypatch.setattr("wattproof.extract._sha256_bytes", lambda _data: "5" * 64)
    monkeypatch.setattr(
        "wattproof.extract._EXTRACTION_SLOTS",
        BusySlots(),
        raising=False,
    )

    def unexpected_expensive_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("busy extraction must not start Poppler or the model")

    for name in ("_page_count", "_render_pages", "_native_text"):
        monkeypatch.setattr(f"wattproof.extract.{name}", unexpected_expensive_call)

    with pytest.raises(ExtractionUnavailableError, match="busy"):
        extract_pdf(candidate, lambda *_args: load_utility_sample("duke"))


def test_unknown_pdf_releases_process_local_slot_after_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "bill.pdf"
    candidate.write_bytes(b"%PDF-placeholder")
    released = False

    class RecordingSlots:
        def acquire(self, *, blocking: bool) -> bool:
            assert blocking is False
            return True

        def release(self) -> None:
            nonlocal released
            released = True

    monkeypatch.setattr("wattproof.extract._sha256_bytes", lambda _data: "4" * 64)
    monkeypatch.setattr(
        "wattproof.extract._EXTRACTION_SLOTS",
        RecordingSlots(),
        raising=False,
    )
    monkeypatch.setattr(
        "wattproof.extract._page_count",
        lambda _path: (_ for _ in ()).throw(InvalidDocumentError("bad PDF")),
    )

    with pytest.raises(InvalidDocumentError, match="bad PDF"):
        extract_pdf(candidate, lambda *_args: load_utility_sample("duke"))

    assert released is True


def test_visual_extractor_failure_releases_slot_and_next_extraction_proceeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "bill.pdf"
    candidate.write_bytes(b"%PDF-placeholder")
    slot_events: list[str] = []
    model_calls = 0

    class SingleSlot:
        held = False

        def acquire(self, *, blocking: bool) -> bool:
            assert blocking is False
            slot_events.append("acquire")
            if self.held:
                return False
            self.held = True
            return True

        def release(self) -> None:
            assert self.held is True
            self.held = False
            slot_events.append("release")

    def visual_extractor(*_args: object) -> UtilityDocument:
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            raise ExtractionUnavailableError("Visual extraction failed.")
        return load_utility_sample("bloomington")

    slots = SingleSlot()
    monkeypatch.setattr("wattproof.extract._sha256_bytes", lambda _data: "1" * 64)
    monkeypatch.setattr("wattproof.extract._EXTRACTION_SLOTS", slots)
    monkeypatch.setattr("wattproof.extract._page_count", lambda _path: 1)
    monkeypatch.setattr(
        "wattproof.extract._render_pages",
        lambda _path, _count: _valid_rendered_pages(1),
    )
    monkeypatch.setattr(
        "wattproof.extract._native_text", lambda _path: "[PAGE 1]\nlocator"
    )
    with pytest.raises(ExtractionUnavailableError, match="Visual extraction failed"):
        extract_pdf(candidate, visual_extractor)

    assert model_calls == 1
    assert slots.held is False
    assert slot_events == ["acquire", "release"]

    extracted = extract_pdf(candidate, visual_extractor)

    assert extracted == load_utility_sample("bloomington")
    assert model_calls == 2
    assert slots.held is False
    assert slot_events == ["acquire", "release", "acquire", "release"]


@pytest.mark.parametrize("stdout", ["small text\f", "\f", ""])
def test_native_text_keeps_short_and_empty_pages_as_labeled_hints(
    stdout: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _call, processes = _install_live_output_process(
        monkeypatch,
        stdout.encode("utf-8"),
    )

    try:
        hint = _native_text(Path("bill.pdf"))
    finally:
        _cleanup_live_processes(processes)

    assert hint.startswith("[PAGE 1]\n")


def test_native_text_hint_is_capped_at_one_hundred_thousand_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = """
import sys

sys.stdout.buffer.write(b"x" * int(sys.argv[1]))
sys.stdout.buffer.flush()
"""
    _call, processes = _install_live_process(
        monkeypatch,
        script,
        lambda _command: ["120000"],
    )

    try:
        hint = _native_text(Path("bill.pdf"))
    finally:
        _cleanup_live_processes(processes)

    assert hint.startswith("[PAGE 1]\n")
    assert len(hint) <= 100_000


def test_native_text_terminates_live_producer_at_character_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "producer-completed"
    script = """
import pathlib
import signal
import sys
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
sys.stdout.buffer.write(b"x" * int(sys.argv[1]))
sys.stdout.buffer.flush()
time.sleep(2)
pathlib.Path(sys.argv[2]).write_text("completed", encoding="utf-8")
"""
    call, processes = _install_live_process(
        monkeypatch,
        script,
        lambda _command: [str(MAX_NATIVE_HINT_CHARS + 50_000), str(marker)],
    )

    started = time.monotonic()
    try:
        hint = _native_text(Path("bill.pdf"))
        elapsed = time.monotonic() - started

        assert hint.startswith("[PAGE 1]\n")
        assert len(hint) <= MAX_NATIVE_HINT_CHARS
        assert elapsed < 1
        assert not marker.exists()
        assert processes and processes[0].poll() is not None
        assert call["stdout"] is subprocess.PIPE
        assert call["stderr"] is subprocess.DEVNULL
        assert call["shell"] is False
    finally:
        _cleanup_live_processes(processes)


def test_native_text_enforces_total_deadline_on_silent_live_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = """
import time

time.sleep(2)
"""
    _call, processes = _install_live_process(
        monkeypatch,
        script,
        lambda _command: [],
    )
    monkeypatch.setattr(
        "wattproof.extract.NATIVE_TEXT_TIMEOUT_SECONDS",
        0.05,
        raising=False,
    )

    started = time.monotonic()
    try:
        with pytest.raises(InvalidDocumentError, match="text-layer reading timed out"):
            _native_text(Path("bill.pdf"))
        assert time.monotonic() - started < 1
        assert processes and processes[0].poll() is not None
    finally:
        _cleanup_live_processes(processes)


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

    def render(command: list[str], **kwargs: object) -> _CompletedPopen:
        nonlocal render_directory
        command_call["command"] = command
        command_call.update(kwargs)
        prefix = Path(command[-1])
        render_directory = prefix.parent
        for page, data in enumerate(pngs, start=1):
            prefix.with_name(f"{prefix.name}-{page}.png").write_bytes(data)
        return _CompletedPopen()

    monkeypatch.setattr("wattproof.extract.subprocess.Popen", render)

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
    assert command_call["stdout"] is subprocess.DEVNULL
    assert command_call["stderr"] is subprocess.DEVNULL
    assert render_directory is not None
    assert not render_directory.exists()


def test_render_pages_accepts_zero_padded_names_in_numeric_page_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render_padded(command: list[str], **_kwargs: object) -> _CompletedPopen:
        prefix = Path(command[-1])
        for page in range(1, 12):
            prefix.with_name(f"{prefix.name}-{page:02}.png").write_bytes(
                b"\x89PNG\r\n\x1a\n" + bytes([page])
            )
        return _CompletedPopen()

    monkeypatch.setattr("wattproof.extract.subprocess.Popen", render_padded)

    rendered = _render_pages(Path("bill.pdf"), page_count=11)

    assert [page.page for page in rendered] == list(range(1, 12))
    assert [
        base64.b64decode(page.data_url.partition(",")[2])[-1] for page in rendered
    ] == list(range(1, 12))


def test_render_pages_converts_timeout_to_safe_document_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = """
import time

time.sleep(2)
"""
    _call, processes = _install_live_process(
        monkeypatch,
        script,
        lambda _command: [],
    )
    monkeypatch.setattr("wattproof.extract.RENDER_TIMEOUT_SECONDS", 0.05)

    try:
        with pytest.raises(InvalidDocumentError, match="rendering timed out") as error:
            _render_pages(Path("bill.pdf"), page_count=1)
    finally:
        _cleanup_live_processes(processes)

    assert "private-customer" not in str(error.value)
    assert "account 123" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_render_pages_converts_nonzero_exit_to_safe_document_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "wattproof.extract.subprocess.Popen",
        lambda *_args, **_kwargs: _CompletedPopen(returncode=1),
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

    monkeypatch.setattr("wattproof.extract.subprocess.Popen", missing_command)

    with pytest.raises(
        ExtractionUnavailableError,
        match="pdftoppm.*not installed",
    ) as error:
        _render_pages(Path("bill.pdf"), page_count=1)

    assert "private executable" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_render_pages_hides_other_poppler_launch_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied_command(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("private executable permission details")

    monkeypatch.setattr("wattproof.extract.subprocess.Popen", denied_command)

    with pytest.raises(
        ExtractionUnavailableError,
        match="PDF rendering could not be started",
    ) as error:
        _render_pages(Path("bill.pdf"), page_count=1)

    assert "private executable" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_render_pages_rejects_missing_page_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render_one_page(command: list[str], **_kwargs: object) -> _CompletedPopen:
        prefix = Path(command[-1])
        prefix.with_name(f"{prefix.name}-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return _CompletedPopen()

    monkeypatch.setattr("wattproof.extract.subprocess.Popen", render_one_page)

    with pytest.raises(InvalidDocumentError, match="incomplete or out of sequence"):
        _render_pages(Path("bill.pdf"), page_count=2)


def test_render_pages_rejects_duplicate_or_unexpected_page_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render_duplicate(command: list[str], **_kwargs: object) -> _CompletedPopen:
        prefix = Path(command[-1])
        prefix.with_name(f"{prefix.name}-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        prefix.with_name(f"{prefix.name}-01.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return _CompletedPopen()

    monkeypatch.setattr("wattproof.extract.subprocess.Popen", render_duplicate)

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
    ) -> _CompletedPopen:
        prefix = Path(command[-1])
        for name in names:
            prefix.with_name(name).write_bytes(b"\x89PNG\r\n\x1a\n")
        return _CompletedPopen()

    monkeypatch.setattr("wattproof.extract.subprocess.Popen", render_invalid_names)

    with pytest.raises(InvalidDocumentError, match="incomplete or out of sequence"):
        _render_pages(Path("bill.pdf"), page_count=page_count)


def test_render_pages_rejects_non_png_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render_invalid(command: list[str], **_kwargs: object) -> _CompletedPopen:
        prefix = Path(command[-1])
        prefix.with_name(f"{prefix.name}-1.png").write_bytes(b"not a png")
        return _CompletedPopen()

    monkeypatch.setattr("wattproof.extract.subprocess.Popen", render_invalid)

    with pytest.raises(InvalidDocumentError, match="page 1 is not a valid PNG"):
        _render_pages(Path("bill.pdf"), page_count=1)


def test_render_pages_rejects_oversized_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render_oversized(command: list[str], **_kwargs: object) -> _CompletedPopen:
        prefix = Path(command[-1])
        prefix.with_name(f"{prefix.name}-1.png").write_bytes(
            b"\x89PNG\r\n\x1a\n" + b"x" * (MAX_RENDERED_PAGE_BYTES - 7)
        )
        return _CompletedPopen()

    monkeypatch.setattr("wattproof.extract.subprocess.Popen", render_oversized)

    with pytest.raises(InvalidDocumentError, match="page 1 exceeds the 8 MB limit"):
        _render_pages(Path("bill.pdf"), page_count=1)


def test_render_pages_enforces_total_render_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def render_two_pages(command: list[str], **_kwargs: object) -> _CompletedPopen:
        prefix = Path(command[-1])
        for page in (1, 2):
            prefix.with_name(f"{prefix.name}-{page}.png").write_bytes(
                b"\x89PNG\r\n\x1a\n"
            )
        return _CompletedPopen()

    monkeypatch.setattr("wattproof.extract.subprocess.Popen", render_two_pages)
    monkeypatch.setattr("wattproof.extract.MAX_TOTAL_RENDERED_BYTES", 15)

    with pytest.raises(InvalidDocumentError, match="total rendered-page budget"):
        _render_pages(Path("bill.pdf"), page_count=2)


def test_render_pages_terminates_live_producer_at_partial_page_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "renderer-completed"
    script = """
import pathlib
import sys
import time

prefix = pathlib.Path(sys.argv[1])
prefix.with_name(f"{prefix.name}-1.png").write_bytes(b"x" * 33)
time.sleep(2)
pathlib.Path(sys.argv[2]).write_text("completed", encoding="utf-8")
"""
    call, processes = _install_live_process(
        monkeypatch,
        script,
        lambda command: [command[-1], str(marker)],
    )
    monkeypatch.setattr("wattproof.extract.MAX_RENDERED_PAGE_BYTES", 32)

    started = time.monotonic()
    try:
        with pytest.raises(InvalidDocumentError, match="page 1 exceeds"):
            _render_pages(Path("bill.pdf"), page_count=1)
        assert time.monotonic() - started < 1
        assert not marker.exists()
        assert processes and processes[0].poll() is not None
        assert call["stdout"] is subprocess.DEVNULL
        assert call["stderr"] is subprocess.DEVNULL
        assert call["shell"] is False
    finally:
        _cleanup_live_processes(processes)


def test_render_pages_terminates_live_producer_at_aggregate_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "renderer-completed"
    script = """
import pathlib
import sys
import time

prefix = pathlib.Path(sys.argv[1])
for page in (1, 2):
    prefix.with_name(f"{prefix.name}-{page}.png").write_bytes(b"x" * 8)
time.sleep(2)
pathlib.Path(sys.argv[2]).write_text("completed", encoding="utf-8")
"""
    _call, processes = _install_live_process(
        monkeypatch,
        script,
        lambda command: [command[-1], str(marker)],
    )
    monkeypatch.setattr("wattproof.extract.MAX_RENDERED_PAGE_BYTES", 100)
    monkeypatch.setattr("wattproof.extract.MAX_TOTAL_RENDERED_BYTES", 15)

    started = time.monotonic()
    try:
        with pytest.raises(InvalidDocumentError, match="total rendered-page budget"):
            _render_pages(Path("bill.pdf"), page_count=2)
        assert time.monotonic() - started < 1
        assert not marker.exists()
        assert processes and processes[0].poll() is not None
    finally:
        _cleanup_live_processes(processes)


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
    call, processes = _install_live_output_process(monkeypatch, b"visible locator")

    try:
        assert _native_text(Path("bill.pdf")) == "[PAGE 1]\nvisible locator"
    finally:
        _cleanup_live_processes(processes)
    assert call == {
        "command": ["pdftotext", "-layout", "bill.pdf", "-"],
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "shell": False,
    }


def test_native_text_reports_missing_pdftotext_without_raw_os_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_command(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("private executable lookup details")

    monkeypatch.setattr("wattproof.extract.subprocess.Popen", missing_command)

    with pytest.raises(
        ExtractionUnavailableError,
        match="pdftotext.*not installed",
    ) as error:
        _native_text(Path("bill.pdf"))

    assert "private executable" not in str(error.value)


def test_native_text_hides_other_poppler_launch_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied_command(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("private executable permission details")

    monkeypatch.setattr("wattproof.extract.subprocess.Popen", denied_command)

    with pytest.raises(
        ExtractionUnavailableError,
        match="PDF text-layer reading could not be started",
    ) as error:
        _native_text(Path("bill.pdf"))

    assert "private executable" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_native_text_converts_nonzero_exit_to_safe_document_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _call, processes = _install_live_output_process(
        monkeypatch,
        b"private bill text",
        returncode=1,
    )

    try:
        with pytest.raises(
            InvalidDocumentError,
            match="text layer could not be read",
        ) as error:
            _native_text(Path("bill.pdf"))
    finally:
        _cleanup_live_processes(processes)

    assert "private bill" not in str(error.value)
    assert "account 123" not in str(error.value)


@pytest.mark.parametrize("stdout", [None, b"private bytes"])
def test_native_text_rejects_malformed_command_output(
    stdout: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "wattproof.extract.subprocess.Popen",
        lambda *_args, **_kwargs: _CompletedPopen(stdout=stdout),
    )

    with pytest.raises(InvalidDocumentError, match="invalid output"):
        _native_text(Path("bill.pdf"))


def test_native_text_converts_unicode_decode_failure_to_safe_document_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _call, processes = _install_live_output_process(
        monkeypatch,
        b"private account 123 \xff",
    )

    try:
        with pytest.raises(
            InvalidDocumentError,
            match="PDF text extraction returned undecodable output",
        ) as error:
            _native_text(Path("bill.pdf"))
    finally:
        _cleanup_live_processes(processes)

    assert "private" not in str(error.value)
    assert "account 123" not in str(error.value)
    assert "secret decoder" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_rendered_page_validation_orders_complete_png_evidence() -> None:
    ordered = _validate_rendered_pages(
        tuple(reversed(_valid_rendered_pages(3))),
        page_count=3,
    )

    assert tuple(page.page for page in ordered) == (1, 2, 3)


@pytest.mark.parametrize(
    ("rendered_pages", "page_count", "message"),
    [
        ((), 1, "exactly match trusted pages"),
        (
            (
                RenderedPage(page=1, data_url=VALID_PNG_DATA_URL),
                RenderedPage(page=1, data_url=VALID_PNG_DATA_URL),
            ),
            2,
            "exactly match trusted pages",
        ),
        (
            (
                RenderedPage(page=1, data_url=VALID_PNG_DATA_URL),
                RenderedPage(page=3, data_url=VALID_PNG_DATA_URL),
            ),
            3,
            "exactly match trusted pages",
        ),
        (
            (
                RenderedPage(page=1, data_url=VALID_PNG_DATA_URL),
                RenderedPage(page=2, data_url=VALID_PNG_DATA_URL),
                RenderedPage(page=4, data_url=VALID_PNG_DATA_URL),
            ),
            3,
            "exactly match trusted pages",
        ),
        (_valid_rendered_pages(1), 2, "exactly match trusted pages"),
        (
            (RenderedPage(page=1, data_url="https://example.com/page.png"),),
            1,
            "valid PNG data URL",
        ),
        (
            (RenderedPage(page=1, data_url="data:image/png;base64,%%%"),),
            1,
            "valid PNG data URL",
        ),
        (
            (
                RenderedPage(
                    page=1,
                    data_url=(
                        "data:image/png;base64,"
                        + base64.b64encode(b"not png").decode("ascii")
                    ),
                ),
            ),
            1,
            "valid PNG data URL",
        ),
    ],
)
def test_rendered_page_validation_rejects_untrusted_evidence(
    rendered_pages: tuple[RenderedPage, ...],
    page_count: int,
    message: str,
) -> None:
    with pytest.raises(InvalidDocumentError, match=message):
        _validate_rendered_pages(rendered_pages, page_count=page_count)


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
    rendered = _valid_rendered_pages(2)
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

    def visual_extractor(
        rendered_pages: tuple[RenderedPage, ...],
        received_hint: str,
        document_sha256: str,
        page_count: int,
    ) -> UtilityDocument:
        events.append("visual_extractor")
        assert rendered_pages == rendered
        assert received_hint == native_hint
        assert document_sha256 == digest
        assert page_count == 2
        return extracted

    monkeypatch.setattr("wattproof.extract._page_count", page_count)
    monkeypatch.setattr("wattproof.extract._render_pages", render_pages)
    monkeypatch.setattr("wattproof.extract._native_text", native_text)

    assert extract_pdf(candidate, visual_extractor) == extracted
    assert events == [
        "page_count",
        "render_pages",
        "native_text",
        "visual_extractor",
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
        extract_pdf(candidate, lambda *_args: load_utility_sample("duke"))
