"""Problem Details helpers following RFC 9457."""

from __future__ import annotations

from flask import jsonify


def problem_details(status: int, title: str, detail: str, instance: str):
    response = jsonify(
        {
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": instance,
        }
    )
    response.status_code = status
    response.content_type = "application/problem+json"
    return response
