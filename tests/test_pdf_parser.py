from pypdf import PdfWriter

from src.documents.pdf_parser import parse_pdf


def test_parse_pdf_warns_on_no_extractable_text(tmp_path):
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)

    result = parse_pdf(path)
    assert result.path == path
    assert result.warnings
