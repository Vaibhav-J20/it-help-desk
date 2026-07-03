"""Unit tests — PDF Parser"""

import hashlib
import io
from unittest.mock import MagicMock, patch

import pytest

from app.ingestion.pdf_parser import ParseResult, parse_pdf, PARSER_VERSION


def _make_fake_pdf_bytes(page_texts: list[str]) -> bytes:
    """Build a minimal in-memory PDF using pypdf's writer."""
    import pypdf
    writer = pypdf.PdfWriter()
    for _ in page_texts:
        writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestParsePdf:

    def test_returns_parse_result_type(self):
        """parse_pdf must return a ParseResult."""
        # Patch PdfReader to avoid needing a real PDF
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Sample text on page one."
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with patch("app.ingestion.pdf_parser.pypdf.PdfReader", return_value=mock_reader):
            result = parse_pdf(b"fake-pdf-bytes", "local://docs/test.pdf")

        assert isinstance(result, ParseResult)

    def test_page_numbers_are_one_based(self):
        """Page numbers must start at 1, not 0."""
        mock_pages = [MagicMock() for _ in range(3)]
        for i, p in enumerate(mock_pages):
            p.extract_text.return_value = f"Text on page {i + 1}"
        mock_reader = MagicMock()
        mock_reader.pages = mock_pages

        with patch("app.ingestion.pdf_parser.pypdf.PdfReader", return_value=mock_reader):
            result = parse_pdf(b"fake", "local://docs/test.pdf")

        page_numbers = [p.page_number for p in result.pages]
        assert page_numbers == [1, 2, 3]

    def test_content_hash_is_sha256_prefixed(self):
        """content_hash must be 'sha256:' + hex digest."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Hello world"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with patch("app.ingestion.pdf_parser.pypdf.PdfReader", return_value=mock_reader):
            result = parse_pdf(b"fake", "local://docs/test.pdf")

        assert result.content_hash.startswith("sha256:")
        expected = "sha256:" + hashlib.sha256("Hello world".encode()).hexdigest()
        assert result.content_hash == expected

    def test_empty_page_included_with_zero_char_count(self):
        """Pages with no extractable text must still appear with char_count=0."""
        mock_pages = [MagicMock(), MagicMock()]
        mock_pages[0].extract_text.return_value = "Some text"
        mock_pages[1].extract_text.return_value = ""
        mock_reader = MagicMock()
        mock_reader.pages = mock_pages

        with patch("app.ingestion.pdf_parser.pypdf.PdfReader", return_value=mock_reader):
            result = parse_pdf(b"fake", "local://docs/test.pdf")

        assert result.pages[1].char_count == 0
        assert result.pages[1].text == ""

    def test_invalid_pdf_raises_value_error(self):
        """Non-PDF bytes must raise ValueError."""
        with pytest.raises(ValueError, match="Cannot open PDF"):
            parse_pdf(b"not a pdf", "local://docs/bad.pdf")

    def test_parser_version_is_set(self):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "text"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with patch("app.ingestion.pdf_parser.pypdf.PdfReader", return_value=mock_reader):
            result = parse_pdf(b"fake", "local://docs/test.pdf")

        assert result.parser_version == PARSER_VERSION
