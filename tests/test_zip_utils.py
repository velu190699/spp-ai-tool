from zipfile import ZipFile

from src.documents.zip_utils import extract_first_recommendation_report


def test_extract_first_exact_recommendation_report(tmp_path):
    archive = tmp_path / "rr.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr("RR 782 Recommendation Report.docx", b"first")
        zf.writestr("RR 782 Recommendation Report copy.docx", b"wrong")

    result = extract_first_recommendation_report(archive, "0782", tmp_path / "out")
    assert result is not None
    assert result.name == "RR 782 Recommendation Report.docx"
    assert result.read_bytes() == b"first"


def test_missing_recommendation_report_returns_none(tmp_path):
    archive = tmp_path / "rr.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr("RR 782 Other Document.docx", b"nope")

    assert extract_first_recommendation_report(archive, "782", tmp_path / "out") is None
