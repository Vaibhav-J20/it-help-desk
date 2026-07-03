"""Unit tests — PDF Parser (pdfminer.six)"""

import hashlib
from unittest.mock import patch

import pytest
from pdfminer.layout import LTTextBox

from app.ingestion.pdf_parser import ParseResult, PageRecord, parse_pdf, PARSER_VERSION


def _make_text_element(text: str) -> LTTextBox:
    """
    Create a real LTTextBox (subclass of LTTextContainer) so isinstance checks pass.
    LTTextBox.get_text() returns the text we set on its internal storage.
    """
    box = LTTextBox()
    box._objs = []          # pdfminer internals — we override get_text directly
    box.get_text = lambda: text   # type: ignore[method-assign]
    return box


class TestParsePdf:

    def _run_parse(self, page_texts: list[list[str]], source_uri: str = "local://docs/test.pdf"):
        """
        Helper: patch extract_pages with real LTTextBox elements, run parse_pdf.

        page_texts: list of pages; each page is a list of text strings.
        """
        mock_page_layouts = []
        for texts in page_texts:
            elements = [_make_text_element(t) for t in texts]
            mock_page_layouts.append(elements)

        with patch("app.ingestion.pdf_parser.extract_pages", return_value=mock_page_layouts):
            return parse_pdf(b"fake-pdf-bytes", source_uri)

    def test_returns_parse_result_type(self):
        """parse_pdf must return a ParseResult."""
        result = self._run_parse([["Sample text on page one."]])
        assert isinstance(result, ParseResult)

    def test_page_numbers_are_one_based(self):
        """Page numbers must start at 1, not 0."""
        result = self._run_parse([
            ["Text on page 1"],
            ["Text on page 2"],
            ["Text on page 3"],
        ])
        page_numbers = [p.page_number for p in result.pages]
        assert page_numbers == [1, 2, 3]

    def test_total_pages_matches_input(self):
        """total_pages must equal number of pages in the PDF."""
        result = self._run_parse([["Page 1"], ["Page 2"]])
        assert result.total_pages == 2

    def test_content_hash_is_sha256_prefixed(self):
        """content_hash must be 'sha256:' + hex digest of concatenated page text."""
        result = self._run_parse([["Hello world"]])
        assert result.content_hash.startswith("sha256:")
        expected = "sha256:" + hashlib.sha256("Hello world".encode()).hexdigest()
        assert result.content_hash == expected

    def test_empty_page_included_with_zero_char_count(self):
        """Pages with no extractable text must appear with char_count=0."""
        result = self._run_parse([
            ["Some text"],
            [],          # empty page — no LTTextContainer elements
        ])
        assert len(result.pages) == 2
        assert result.pages[0].char_count > 0
        assert result.pages[1].char_count == 0
        assert result.pages[1].text == ""

    def test_invalid_pdf_raises_value_error(self):
        """Non-PDF bytes must raise ValueError."""
        with pytest.raises(ValueError, match="Cannot open PDF"):
            parse_pdf(b"not a pdf at all", "local://docs/bad.pdf")

    def test_parser_version_is_set(self):
        """parser_version must equal PARSER_VERSION constant."""
        result = self._run_parse([["Any text."]])
        assert result.parser_version == PARSER_VERSION

    def test_source_uri_preserved(self):
        """source_uri on result must match the argument passed in."""
        uri = "local://docs/specific-test.pdf"
        result = self._run_parse([["text"]], source_uri=uri)
        assert result.source_uri == uri

    def test_page_text_is_stripped(self):
        """Leading/trailing whitespace on page text must be stripped."""
        result = self._run_parse([["  text with spaces  "]])
        assert result.pages[0].text == "text with spaces"

    def test_char_count_matches_text_length(self):
        """char_count must equal len(text) after stripping."""
        result = self._run_parse([["hello world"]])
        page = result.pages[0]
        assert page.char_count == len(page.text)
