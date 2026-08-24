"""Defensive parsing of generated knowledge-point JSON responses."""

from __future__ import annotations

import json
from typing import AbstractSet

from .data import normalize_text


class ResponseParseError(ValueError):
    """Raised when model output cannot be interpreted as tagging JSON."""


def _first_json_object(text: str) -> dict[object, object]:
    start = text.find("{")
    if start < 0:
        raise ResponseParseError("response does not contain a JSON object")
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as error:
        raise ResponseParseError(f"response contains invalid JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise ResponseParseError("response JSON must be an object")
    return payload


def parse_response(text: str, taxonomy: AbstractSet[str]) -> list[str]:
    """Extract a normalized, de-duplicated in-taxonomy label list from model output."""
    payload = _first_json_object(text)
    labels = payload.get("knowledge_points")
    if not isinstance(labels, list):
        raise ResponseParseError("response JSON must contain a knowledge_points array")
    normalized_taxonomy = {normalize_text(label) for label in taxonomy}
    return sorted(
        {
            normalized
            for label in labels
            if isinstance(label, str)
            for normalized in [normalize_text(label)]
            if normalized and normalized in normalized_taxonomy
        }
    )
