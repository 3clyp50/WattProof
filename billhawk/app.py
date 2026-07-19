from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file
from pydantic import ValidationError
from werkzeug.exceptions import RequestEntityTooLarge

from .audit import UnsupportedBillError, audit_bill
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


def _json_model(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_FILE_BYTES,
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/sample.pdf")
    def sample_pdf():
        return send_file(
            PROJECT_ROOT / "assets/pge-anonymous-3ce-sample-bill.pdf",
            mimetype="application/pdf",
            download_name="billhawk-public-anonymized-sample.pdf",
        )

    @app.get("/api/sample/<kind>")
    def sample(kind: str):
        if kind not in {"authentic", "synthetic"}:
            return jsonify(error="Choose the authentic or synthetic sample."), 404
        return jsonify(extraction=_json_model(load_sample(kind)))

    @app.post("/api/extract")
    def extract():
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
    def audit():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="The reviewed extraction is missing."), 400
        extraction = BillExtraction.model_validate(payload)
        return jsonify(audit=_json_model(audit_bill(extraction)))

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error: RequestEntityTooLarge):
        return jsonify(error="PDFs are limited to 10 MB."), 413

    @app.errorhandler(ValidationError)
    def validation_error(error: ValidationError):
        first = error.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first["loc"])
        return jsonify(error=f"Review {location}: {first['msg']}"), 422

    for error_type in (
        ExtractionUnavailableError,
        InvalidDocumentError,
        SourceIntegrityError,
        UnsupportedBillError,
        UnsupportedDocumentError,
    ):
        app.register_error_handler(
            error_type,
            lambda error: (jsonify(error=str(error)), 422),
        )

    return app
