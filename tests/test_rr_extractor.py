from src.documents.rr_extractor import candidate_initiative, extract_rr_mentions, normalize_rr_number


def test_candidate_initiative_finds_nearby_named_effort():
    # RR750's real SUF context: no seasonal bundle, but a named project nearby.
    ctx = ["...implemented with RTO Expansion Project effective on 4/1/2026. Calculation changes..."]
    assert candidate_initiative(ctx) == "RTO Expansion Project"
    assert candidate_initiative(["nothing capitalized or named here"]) == ""
    assert candidate_initiative([]) == ""


def test_normalize_rr_number_variants():
    assert normalize_rr_number("RR782") == "782"
    assert normalize_rr_number("RR 782") == "782"
    assert normalize_rr_number("RR-0782") == "782"
    assert normalize_rr_number("0782") == "782"


def test_extract_rr_mentions_with_nearby_dates():
    text = "The group discussed RR 0782 with a comment deadline of 06/15/2026. RR-781 follows."
    mentions = extract_rr_mentions(text, source="sample.pdf")
    by_rr = {mention.rr_number: mention for mention in mentions}
    assert "782" in by_rr
    assert "06/15/2026" in by_rr["782"].dates
    assert by_rr["782"].source == "sample.pdf"
    assert "781" in by_rr
