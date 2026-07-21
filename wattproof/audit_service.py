from __future__ import annotations

from .adapters import TARIFF_ADAPTERS
from .legacy import translate_legacy_bill
from .models import BillExtraction
from .reconcile import reconcile_document
from .utility_models import UtilityAuditResult, UtilityDocument

Extraction = BillExtraction | UtilityDocument


def audit_extraction(extraction: Extraction) -> UtilityAuditResult:
    """Audit either extraction schema without implying unsupported tariff truth."""

    if isinstance(extraction, BillExtraction):
        for adapter in TARIFF_ADAPTERS:
            if adapter.matches(extraction):
                return adapter.audit(extraction)
        return reconcile_document(translate_legacy_bill(extraction))
    return reconcile_document(extraction)
