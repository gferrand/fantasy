"""Private Discord attachment normalization before interactive advisor tasks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from openai import OpenAI


MAX_TEXT_BYTES = 1_000_000
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_NORMALIZED_CHARS = 20_000

_AUDIO_SUFFIXES = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg", ".opus"}


class AttachmentIntakeError(RuntimeError):
    """Raised when a private Discord attachment cannot be normalized."""


@dataclass(frozen=True)
class NormalizedAttachment:
    text: str
    filename: str
    kind: str
    content_type: str | None


def classify_attachment(filename: str, content_type: str | None) -> str:
    suffix = Path(filename).suffix.casefold()
    mime = (content_type or "").split(";", 1)[0].casefold()
    if suffix == ".pdf" or mime == "application/pdf":
        return "pdf"
    if suffix == ".txt" or mime == "text/plain":
        return "text"
    if suffix in _AUDIO_SUFFIXES or mime.startswith("audio/"):
        return "audio"
    raise AttachmentIntakeError("Supported attachments are PDF, .txt, and an audio/voice-note file.")


def validate_attachment_size(kind: str, size: int) -> None:
    if size < 1:
        raise AttachmentIntakeError("The attachment is empty.")
    limit = {"text": MAX_TEXT_BYTES, "pdf": MAX_PDF_BYTES, "audio": MAX_AUDIO_BYTES}[kind]
    if size > limit:
        label = {"text": "1 MB", "pdf": "20 MB", "audio": "25 MB"}[kind]
        raise AttachmentIntakeError(f"This {kind} attachment is too large; the limit is {label}.")


def _bounded_text(text: str, *, filename: str) -> str:
    normalized = text.strip()
    if not normalized:
        raise AttachmentIntakeError(f"I couldn’t extract readable text from {filename!r}.")
    if len(normalized) > MAX_NORMALIZED_CHARS:
        raise AttachmentIntakeError(
            f"{filename!r} produced more than {MAX_NORMALIZED_CHARS:,} characters. Please split it into smaller parts."
        )
    return normalized


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AttachmentIntakeError("Text files must use UTF-8 encoding.") from exc


def _transcribe_audio(client: OpenAI, path: Path, *, model: str) -> str:
    try:
        with path.open("rb") as audio_file:
            result = client.audio.transcriptions.create(model=model, file=audio_file)
    except Exception as exc:  # SDK transport errors are intentionally user-safe at this boundary.
        raise AttachmentIntakeError("OpenAI couldn’t transcribe that voice note. Please try again.") from exc
    return str(getattr(result, "text", ""))


def _extract_pdf(client: OpenAI, path: Path, *, model: str) -> str:
    file_id: str | None = None
    try:
        with path.open("rb") as document:
            uploaded = client.files.create(file=document, purpose="user_data")
        file_id = str(uploaded.id)
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Extract this PDF faithfully as clean plain text for a later advisor. "
                                "Preserve headings, tables, labels, dates, and numerical values where possible. "
                                "Do not summarize, analyze, or add conclusions."
                            ),
                        },
                        {"type": "input_file", "file_id": file_id, "detail": "low"},
                    ],
                }
            ],
            max_output_tokens=6000,
        )
        return str(getattr(response, "output_text", ""))
    except Exception as exc:  # SDK errors must not spill raw provider diagnostics into Discord.
        raise AttachmentIntakeError("OpenAI couldn’t read that PDF. Please try a smaller or text-based PDF.") from exc
    finally:
        if file_id:
            try:
                client.files.delete(file_id)
            except Exception:
                # The local raw file is still removed by the caller. A failed
                # remote deletion is logged by the gateway without exposing an ID.
                pass


def normalize_attachment(
    path: Path,
    *,
    filename: str,
    content_type: str | None,
    api_key: str,
    audio_model: str,
    document_model: str,
    client_factory: Callable[..., OpenAI] = OpenAI,
) -> NormalizedAttachment:
    """Convert one already-downloaded private attachment into bounded text."""

    kind = classify_attachment(filename, content_type)
    validate_attachment_size(kind, path.stat().st_size)
    if kind == "text":
        text = _read_text_file(path)
    else:
        if not api_key:
            raise AttachmentIntakeError("OpenAI attachment processing is not configured on this advisor yet.")
        client = client_factory(api_key=api_key)
        if kind == "pdf":
            text = _extract_pdf(client, path, model=document_model)
        else:
            # Discord voice notes are commonly OGG/Opus. Nettie's production
            # path sends those bytes directly to OpenAI successfully, avoiding
            # an unnecessary local conversion dependency.
            text = _transcribe_audio(client, path, model=audio_model)
    return NormalizedAttachment(
        text=_bounded_text(text, filename=filename),
        filename=filename,
        kind=kind,
        content_type=content_type,
    )


def render_attachment_message(caption: str, attachment: NormalizedAttachment) -> str:
    """Make source provenance clear when normalized content reaches Codex."""

    prefix = caption.strip()
    source = f"Attachment ({attachment.kind}; {attachment.filename}):\n{attachment.text}"
    return f"{prefix}\n\n{source}" if prefix else source
