from __future__ import annotations

import json
import tempfile
from decimal import Decimal, DecimalException
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_file
from pydantic import BaseModel, ValidationError
from werkzeug.exceptions import RequestEntityTooLarge

from .audit import UnsupportedBillError
from .audit_service import audit_extraction
from .extract import (
    MAX_FILE_BYTES,
    ExtractionUnavailableError,
    InvalidDocumentError,
    UnsupportedDocumentError,
    extract_pdf,
)
from .fixtures import PROJECT_ROOT, load_sample
from .models import BillExtraction
from .tariffs import SourceIntegrityError
from .utility_fixtures import load_utility_sample
from .utility_models import UtilityDocument

MAX_AUDIT_JSON_NUMBER_CHARACTERS = 128


def _json_model(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON number: {value}")


def _parse_json_decimal(value: str) -> Decimal:
    if len(value) > MAX_AUDIT_JSON_NUMBER_CHARACTERS:
        raise ValueError("JSON number is too long")
    try:
        return Decimal(value)
    except DecimalException as error:
        raise ValueError("JSON decimal is outside the supported parser range") from error


def _parse_json_integer(value: str) -> int:
    if len(value) > MAX_AUDIT_JSON_NUMBER_CHARACTERS:
        raise ValueError("JSON number is too long")
    return int(value)


def _exact_audit_payload() -> dict[str, Any] | None:
    """Decode audit numbers exactly instead of first rounding them through float."""

    if not request.is_json:
        return None
    try:
        payload: Any = json.loads(
            request.get_data(cache=True),
            parse_float=_parse_json_decimal,
            parse_int=_parse_json_integer,
            parse_constant=_reject_json_constant,
        )
    except (JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_FILE_BYTES,
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )

    @app.get("/healthz")
    def health() -> Response:
        return jsonify(status="ok")

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/sample.pdf")
    def sample_pdf() -> Response:
        return send_file(
            PROJECT_ROOT / "assets/pge-anonymous-3ce-sample-bill.pdf",
            mimetype="application/pdf",
            download_name="wattproof-public-anonymized-sample.pdf",
        )

    @app.get("/api/sample/<kind>")
    def sample(kind: str) -> Response | tuple[Response, int]:
        extraction: BillExtraction | UtilityDocument
        if kind == "authentic":
            extraction = load_sample("authentic")
        elif kind == "synthetic":
            extraction = load_sample("synthetic")
        elif kind == "duke":
            extraction = load_utility_sample("duke")
        elif kind == "centerpoint":
            extraction = load_utility_sample("centerpoint")
        elif kind == "bloomington":
            extraction = load_utility_sample("bloomington")
        else:
            return jsonify(
                error=(
                    "Choose one of: authentic, synthetic, duke, centerpoint, "
                    "bloomington."
                )
            ), 404
        return jsonify(extraction=_json_model(extraction))

    @app.post("/api/extract")
    def extract() -> Response | tuple[Response, int]:
        upload = request.files.get("bill")
        if upload is None or not upload.filename:
            return jsonify(error="Choose a PDF bill first."), 400

        data = upload.stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            return jsonify(error="PDFs are limited to 10 MB."), 413
        with tempfile.NamedTemporaryFile(suffix=".pdf") as temporary:
            temporary.write(data)
            temporary.flush()
            extraction = extract_pdf(Path(temporary.name))
        return jsonify(extraction=_json_model(extraction))

    @app.post("/api/audit")
    def audit() -> Response | tuple[Response, int]:
        payload = _exact_audit_payload()
        if payload is None:
            return jsonify(error="The reviewed extraction is missing."), 400
        schema_version = payload.get("schema_version")
        extraction: BillExtraction | UtilityDocument
        if schema_version == "1.0":
            extraction = BillExtraction.model_validate(payload)
        elif schema_version == "2.0":
            extraction = UtilityDocument.model_validate(payload)
        else:
            return jsonify(
                error="Review schema_version: expected '1.0' or '2.0'."
            ), 422
        return jsonify(audit=_json_model(audit_extraction(extraction)))

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error: RequestEntityTooLarge) -> tuple[Response, int]:
        return jsonify(error="PDFs are limited to 10 MB."), 413

    @app.errorhandler(ValidationError)
    def validation_error(error: ValidationError) -> tuple[Response, int]:
        errors = error.errors(include_url=False)
        first = next(
            (
                item
                for item in errors
                if "utility-bill" in str(item["msg"])
            ),
            errors[0],
        )
        location = ".".join(
            str(part)
            for part in first["loc"]
            if not (
                isinstance(part, str)
                and part.startswith(("function-after[", "function-before["))
            )
        ) or "document"
        message = str(first["msg"])
        if "percent_of_charges references unknown charge ID:" in message:
            message = (
                "Value error, percent_of_charges references an unknown charge ID"
            )
        return jsonify(error=f"Review {location}: {message}"), 422

    def reviewable_error(error: Exception) -> tuple[Response, int]:
        return jsonify(error=str(error)), 422

    for error_type in (
        ExtractionUnavailableError,
        InvalidDocumentError,
        SourceIntegrityError,
        UnsupportedBillError,
        UnsupportedDocumentError,
    ):
        app.register_error_handler(error_type, reviewable_error)

    return app
