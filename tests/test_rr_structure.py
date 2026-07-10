import io
import zipfile

from lxml import etree

from src.settlement.rr_structure import (
    DEFAULT_BANNERS,
    extract,
    heading_is_new,
    norm_banner,
    para_marked,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def _p(xml_fragment: str) -> etree._Element:
    """Parse a single <w:p> fragment with the real word/math namespaces bound."""
    wrapped = (
        f'<w:p xmlns:w="{W}" xmlns:m="{M}">{xml_fragment}</w:p>'
    )
    return etree.fromstring(wrapped)


def _docx_bytes(paragraphs: list[str]) -> bytes:
    """Build a minimal .docx (zip containing only word/document.xml) from raw
    <w:p>...</w:p> fragments, so extract() can be exercised without a real
    Word file or the python-docx dependency."""
    body = "".join(paragraphs)
    document_xml = (
        f'<w:document xmlns:w="{W}" xmlns:m="{M}"><w:body>{body}</w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def _plain(text: str) -> str:
    return f'<w:r><w:t>{text}</w:t></w:r>'


def _bold(text: str) -> str:
    return f'<w:r><w:rPr><w:b/></w:rPr><w:t>{text}</w:t></w:r>'


def _inserted(text: str) -> str:
    return f'<w:ins><w:r><w:t>{text}</w:t></w:r></w:ins>'


def test_norm_banner_merges_market_protocols_and_settlement_user_guide():
    assert norm_banner("Market Protocols") == "Market Protocols / Settlement User Guide"
    assert norm_banner("Settlement User Guide") == "Market Protocols / Settlement User Guide"
    assert norm_banner("Tariff") == "Tariff"


def test_heading_is_new_true_only_inside_tracked_insertion():
    inserted = _p(_inserted("4.5.19 New Section"))
    unchanged = _p(_plain("4.5.12 Existing Section"))
    assert heading_is_new(inserted) is True
    assert heading_is_new(unchanged) is False


def test_para_marked_preserves_equation_and_redlines():
    fragment = (
        '<w:r><w:t>Formula: </w:t></w:r>'
        f'<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>'
        '<w:ins><w:r><w:t> added</w:t></w:r></w:ins>'
        '<w:del><w:r><w:delText> removed</w:delText></w:r></w:del>'
    )
    marked = para_marked(_p(fragment))
    assert "[[EQ: x ]]" in marked
    assert "{{INS: added}}" in marked
    assert "{{DEL: removed}}" in marked


def _settlement_calc_docx(second_section_in_body: bool = True) -> bytes:
    paragraphs = [
        f'<w:p>{_plain("RR900 Sample Settlement Test RR")}</w:p>',
        f'<w:p>{_plain("Impacted SPP Documents: Market Protocols Section: 4.5.12, (New) 4.5.19 Version 68")}</w:p>',
        f'<w:p>{_plain("☒ Market Protocols")}</w:p>',
        f'<w:p>{_bold("MARKET PROTOCOLS")}</w:p>',
        f'<w:p>{_plain("4.5.12 Revenue Neutrality Uplift Distribution Amount")}</w:p>',
    ]
    if second_section_in_body:
        paragraphs.append(f'<w:p>{_inserted("4.5.19 SSR Distribution Amount")}</w:p>')
    return _docx_bytes(paragraphs)


def test_extract_settlement_calc_pass_when_all_listed_sections_found(tmp_path):
    docx = tmp_path / "RR900.docx"
    docx.write_bytes(_settlement_calc_docx(second_section_in_body=True))

    report, marked, hard_fail = extract(str(docx), DEFAULT_BANNERS, sharepoint_url="https://sp/RR900")

    assert report["rr_id"] == "RR900"
    assert report["rr_class"] == "SETTLEMENT_CALC"
    assert report["reconciliation"]["status"] == "PASS"
    assert hard_fail is False
    sections = {i["section"] for i in report["charge_type_index"]}
    assert sections == {"4.5.12", "4.5.19"}
    # The 4.5.19 heading was inserted inside a tracked change -> is_new True.
    new_flags = {i["section"]: i["is_new"] for i in report["charge_type_index"]}
    assert new_flags["4.5.19"] is True
    assert new_flags["4.5.12"] is False
    assert report["citations"]["rr_document"][0]["sharepoint_url"] == "https://sp/RR900"


def test_extract_hard_fail_when_listed_section_missing_from_body(tmp_path):
    docx = tmp_path / "RR900.docx"
    docx.write_bytes(_settlement_calc_docx(second_section_in_body=False))

    report, marked, hard_fail = extract(str(docx), DEFAULT_BANNERS)

    assert report["rr_class"] == "SETTLEMENT_CALC"
    assert report["reconciliation"]["status"] == "HARD_FAIL"
    assert "4.5.19" in report["reconciliation"]["missing_from_body"]
    assert hard_fail is True


def test_extract_tariff_governance_when_no_settlement_signal(tmp_path):
    docx = tmp_path / "RR901.docx"
    docx.write_bytes(_docx_bytes([
        f'<w:p>{_plain("RR901 Definitions Cleanup")}</w:p>',
        f'<w:p>{_plain("This RR clarifies a defined term in the Tariff with no charge type impact.")}</w:p>',
    ]))

    report, marked, hard_fail = extract(str(docx), DEFAULT_BANNERS)

    assert report["rr_class"] == "TARIFF_GOVERNANCE"
    assert report["reconciliation"]["status"] == "NO_CHARGE_CODES"
    assert hard_fail is False
    assert report["charge_type_index"] == []
