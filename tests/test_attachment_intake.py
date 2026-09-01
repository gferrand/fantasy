import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fantasy_advisor.attachment_intake import (
    AttachmentIntakeError,
    MAX_NORMALIZED_CHARS,
    classify_attachment,
    normalize_attachment,
    render_attachment_message,
)


class AttachmentIntakeTests(unittest.TestCase):
    def test_classifies_requested_input_types(self):
        self.assertEqual(classify_attachment("notes.txt", "text/plain"), "text")
        self.assertEqual(classify_attachment("report.pdf", "application/pdf"), "pdf")
        self.assertEqual(classify_attachment("voice.ogg", "audio/ogg"), "audio")
        with self.assertRaisesRegex(AttachmentIntakeError, "Supported attachments"):
            classify_attachment("photo.png", "image/png")

    def test_text_attachment_is_lossless_and_needs_no_api_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "notes.txt"
            path.write_text("\ufeffCaptain discussion", encoding="utf-8")
            result = normalize_attachment(path, filename="notes.txt", content_type="text/plain", api_key="", audio_model="gpt-transcribe", document_model="gpt-4.1-mini")
        self.assertEqual(result.text, "Captain discussion")
        self.assertEqual(result.kind, "text")

    def test_pdf_uses_file_input_and_deletes_remote_upload(self):
        client = Mock()
        client.files.create.return_value = Mock(id="file-123")
        client.responses.create.return_value = Mock(output_text="Extracted table")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.pdf"
            path.write_bytes(b"%PDF-1.4")
            result = normalize_attachment(path, filename="report.pdf", content_type="application/pdf", api_key="key", audio_model="gpt-transcribe", document_model="gpt-4.1-mini", client_factory=lambda **_: client)
        self.assertEqual(result.text, "Extracted table")
        self.assertEqual(client.responses.create.call_args.kwargs["model"], "gpt-4.1-mini")
        client.files.delete.assert_called_once_with("file-123")

    def test_audio_uses_transcription_model(self):
        client = Mock()
        client.audio.transcriptions.create.return_value = Mock(text="Add Matt O'Riley to my watchlist")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "voice.m4a"
            path.write_bytes(b"audio")
            result = normalize_attachment(path, filename="voice.m4a", content_type="audio/mp4", api_key="key", audio_model="gpt-transcribe", document_model="gpt-4.1-mini", client_factory=lambda **_: client)
        self.assertEqual(result.text, "Add Matt O'Riley to my watchlist")
        self.assertEqual(client.audio.transcriptions.create.call_args.kwargs["model"], "gpt-transcribe")

    def test_ogg_is_sent_directly_and_oversized_normalized_text_is_rejected(self):
        client = Mock()
        client.audio.transcriptions.create.return_value = Mock(text="Spoken request")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "voice.ogg"
            path.write_bytes(b"audio")
            result = normalize_attachment(path, filename="voice.ogg", content_type="audio/ogg", api_key="key", audio_model="gpt-4o-mini-transcribe", document_model="gpt-4.1-mini", client_factory=lambda **_: client)
            self.assertEqual(result.text, "Spoken request")
            text_path = Path(temporary) / "large.txt"
            text_path.write_text("x" * (MAX_NORMALIZED_CHARS + 1), encoding="utf-8")
            with self.assertRaisesRegex(AttachmentIntakeError, "split"):
                normalize_attachment(text_path, filename="large.txt", content_type="text/plain", api_key="", audio_model="gpt-transcribe", document_model="gpt-4.1-mini")

    def test_rendered_attachment_keeps_caption_and_source(self):
        from fantasy_advisor.attachment_intake import NormalizedAttachment
        rendered = render_attachment_message("Assess this", NormalizedAttachment("Player notes", "notes.txt", "text", "text/plain"))
        self.assertIn("Assess this", rendered)
        self.assertIn("Attachment (text; notes.txt)", rendered)


if __name__ == "__main__":
    unittest.main()
