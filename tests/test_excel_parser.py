from openpyxl import Workbook

from src.documents.excel_parser import read_open_rrs


def test_read_open_rrs_filters_status_and_hyperlink(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Number", "Link", "Title", "Status", "Primary Working Group", "Impacted Documents"])
    sheet.append(["0782", "rr782", "Open title", "Open", "MWG", "Tariff"])
    sheet["B2"].hyperlink = "https://www.spp.org/search?q=rr782"
    sheet.append(["0781", "rr781", "Closed title", "Closed", "TWG", "Protocols"])
    path = tmp_path / "rr.xlsx"
    workbook.save(path)

    open_rrs = read_open_rrs(path)
    assert list(open_rrs) == ["782"]
    assert open_rrs["782"].title == "Open title"
    assert open_rrs["782"].search_url == "https://www.spp.org/search?q=rr782"
