"""
Shared upload validation for every user-supplied file (ticket attachments,
work-order evidence, ...): size limit, extension allow-list, content sniffing
with libmagic (the bytes must match the extension), and a SHA-256 digest.
SVG and executables are never accepted.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from rest_framework import exceptions

DOCUMENTS: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".txt": frozenset({"text/plain"}),
    ".log": frozenset({"text/plain"}),
    ".csv": frozenset({"text/csv", "text/plain", "application/csv"}),
    ".docx": frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"}),
    ".xlsx": frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/zip"}),
    ".zip": frozenset({"application/zip"}),
}
IMAGES: dict[str, frozenset[str]] = {
    ".png": frozenset({"image/png"}),
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    ".webp": frozenset({"image/webp"}),
    ".gif": frozenset({"image/gif"}),
    ".heic": frozenset({"image/heic", "image/heif"}),
}
ALL_ALLOWED = {**IMAGES, **DOCUMENTS}


@dataclass(frozen=True)
class ValidatedUpload:
    original_name: str
    content_type: str
    size: int
    sha256: str


def sniff_mime(fileobj) -> str:
    import magic

    head = fileobj.read(4096)
    fileobj.seek(0)
    return magic.from_buffer(head, mime=True)


def validate_upload(upload, allowed: dict[str, frozenset[str]] = ALL_ALLOWED) -> ValidatedUpload:
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if upload.size > max_bytes:
        raise exceptions.ValidationError({"file": [f"Files must be {settings.MAX_UPLOAD_SIZE_MB} MB or smaller."]})
    if upload.size == 0:
        raise exceptions.ValidationError({"file": ["The file is empty."]})
    original_name = Path(upload.name).name[:255]
    ext = Path(original_name).suffix.lower()
    if ext not in allowed:
        raise exceptions.ValidationError(
            {"file": [f"This file type is not allowed. Allowed: {', '.join(sorted(allowed))}."]}
        )
    sniffed = sniff_mime(upload)
    if sniffed not in allowed[ext]:
        # The content doesn't match the extension (e.g. an executable renamed to .pdf).
        raise exceptions.ValidationError({"file": ["The file content does not match its extension."]})
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return ValidatedUpload(original_name=original_name, content_type=sniffed, size=upload.size, sha256=digest.hexdigest())
