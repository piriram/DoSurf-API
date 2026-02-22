"""Utilities for safely building Firestore path components."""


def sanitize_firestore_id(value: str) -> str:
    """Normalize a Firestore collection/document ID component."""
    return str(value).replace("/", "_").replace(" ", "_")

