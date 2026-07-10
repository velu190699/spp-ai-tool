from openpyxl import load_workbook

from src.settlement.settlement_report import build

SAMPLE_REPORT = {
    "rr_id": "RR900",
    "rr_title": "Sample Settlement Test RR",
    "sharepoint_url": "https://sp/RR900",
    "total_pages": 12,
    "rr_class": "SETTLEMENT_CALC",
    "charge_type_index": [
        {"banner": "Market Protocols / Settlement User Guide", "section": "4.5.12",
         "title": "Revenue Neutrality Uplift Distribution Amount", "is_new": False, "page": 3},
        {"banner": "Market Protocols / Settlement User Guide", "section": "4.5.19",
         "title": "SSR Distribution Amount", "is_new": True, "page": 4},
    ],
    "reconciliation": {"status": "PASS"},
}


def test_build_writes_rr_summary_and_settlement_stories_sheets(tmp_path):
    out_path = tmp_path / "SPP_RR_Report_Summary.xlsx"
    results = [{"report": SAMPLE_REPORT, "stories": None}]

    build(results, str(out_path))

    wb = load_workbook(out_path)
    assert wb.sheetnames == ["RR Summary", "Settlement Stories"]

    summary_row = next(wb["RR Summary"].iter_rows(min_row=3, max_row=3, values_only=True))
    assert summary_row[0] == "RR900"
    assert summary_row[2] == "Settlement Calc"
    assert summary_row[3] == "Pass"

    stories_rows = list(wb["Settlement Stories"].iter_rows(min_row=3, values_only=True))
    assert len(stories_rows) == 2  # one row per charge type in the index
    sections = {row[2] for row in stories_rows}
    assert sections == {"4.5.12", "4.5.19"}


def test_build_skips_settlement_stories_for_non_calc_rrs(tmp_path):
    out_path = tmp_path / "SPP_RR_Report_Summary.xlsx"
    non_calc_report = dict(SAMPLE_REPORT, rr_class="TARIFF_GOVERNANCE", charge_type_index=[],
                            reconciliation={"status": "NO_CHARGE_CODES"})
    results = [{"report": non_calc_report, "stories": None}]

    build(results, str(out_path))

    wb = load_workbook(out_path)
    stories_rows = list(wb["Settlement Stories"].iter_rows(min_row=3, values_only=True))
    assert stories_rows == []


def test_build_escapes_leading_equals_sign_to_prevent_formula_injection(tmp_path):
    out_path = tmp_path / "SPP_RR_Report_Summary.xlsx"
    malicious_report = dict(SAMPLE_REPORT, rr_title="=cmd|'/c calc'!A1")
    results = [{"report": malicious_report, "stories": None}]

    build(results, str(out_path))

    wb = load_workbook(out_path)
    title_cell = list(wb["RR Summary"].iter_rows(min_row=3, max_row=3, values_only=True))[0][1]
    assert not title_cell.startswith("=")
