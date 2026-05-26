"""Structured audit logging for extraction jobs."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("service_extractor.audit")


def emit_audit_event(event: dict[str, Any]) -> None:
    """Emit one structured audit event as JSON."""
    logger.info(json.dumps(event, sort_keys=True))
