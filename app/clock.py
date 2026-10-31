"""Horloge UTC partagée par l'API et le pipeline."""

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Instant UTC lexicographiquement triable, avec microsecondes."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
