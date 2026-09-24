"""PM decision store for the RR Control app (src/control_app/decisions.py)."""
import pytest

from src.control_app.decisions import DecisionStore, stale_decision


@pytest.fixture()
def store(tmp_path):
    return DecisionStore(tmp_path / "decisions.db")


def test_saving_a_judgement_stamps_author_and_tool_class(store):
    store.save("623", {"applies": "Yes", "reviewed": True}, domain="BO",
               tool_class="SETTLEMENT_CALC", user="pm")
    d = store.get("623")
    assert d["applies"] == "Yes" and d["reviewed"] == 1
    assert d["reviewed_by"] == "pm" and d["reviewed_at"]
    # The tool's verdict AT THE TIME is what makes a later reclassification visible.
    assert d["class_when_decided"] == "SETTLEMENT_CALC"
    assert d["domain"] == "BO"


def test_unticking_review_releases_the_claim(store):
    store.save("623", {"reviewed": True}, tool_class="SETTLEMENT_CALC", user="pm")
    store.save("623", {"reviewed": False}, tool_class="SETTLEMENT_CALC", user="pm")
    d = store.get("623")
    assert d["reviewed"] == 0
    # A name left behind on an unreviewed row would be a lie about who vouched for it.
    assert d["reviewed_by"] == "" and d["reviewed_at"] == ""


def test_edits_merge_instead_of_replacing(store):
    store.save("728", {"applies": "Yes"}, tool_class="SETTLEMENT_CALC")
    store.save("728", {"note": "waiting on SME"}, tool_class="SETTLEMENT_CALC")
    d = store.get("728")
    assert d["applies"] == "Yes" and d["note"] == "waiting on SME"


def test_tool_owned_fields_are_rejected(store):
    # The app must never be able to write the tool's half of a row.
    with pytest.raises(ValueError):
        store.save("623", {"rr_class": "SETTLEMENT_CALC"})


def test_stale_only_when_a_judged_row_was_reclassified(store):
    store.save("786", {"applies": "Yes", "reviewed": True}, tool_class="SETTLEMENT_CALC")
    judged = store.get("786")
    assert stale_decision(judged, "SETTLEMENT_CALC") is False
    assert stale_decision(judged, "TARIFF_GOVERNANCE") is True
    # A row nobody judged cannot be stale, however the tool reclassifies it.
    store.save("795", {"note": "just a note"}, tool_class="SETTLEMENT_CALC")
    assert stale_decision(store.get("795"), "TARIFF_GOVERNANCE") is False
    assert stale_decision({}, "TARIFF_GOVERNANCE") is False


def test_decisions_survive_reopening_the_file(tmp_path):
    path = tmp_path / "decisions.db"
    DecisionStore(path).save("623", {"applies": "No"}, tool_class="TARIFF_GOVERNANCE")
    assert DecisionStore(path).get("623")["applies"] == "No"


def test_initiative_catalog_add_retire_and_revive(store):
    assert store.add_initiative("2026 Settlements Fall Bundle", note="CUF Aug p.7") is True
    # Adding the same name twice is a no-op, not an error: two PMs may try.
    assert store.add_initiative("2026 Settlements Fall Bundle") is False
    assert [i["name"] for i in store.initiatives()] == ["2026 Settlements Fall Bundle"]

    store.set_initiative_active("2026 Settlements Fall Bundle", False)
    assert store.initiatives() == []                       # hidden from the dropdown
    assert len(store.initiatives(active_only=False)) == 1   # but still resolvable
    # Re-adding a retired name revives it instead of failing.
    assert store.add_initiative("2026 Settlements Fall Bundle") is True
    assert len(store.initiatives()) == 1


def test_initiative_usage_counts_validated_rrs(store):
    store.add_initiative("Fall Bundle")
    store.save("623", {"initiative_validated": "Fall Bundle"}, tool_class="SETTLEMENT_CALC")
    store.save("728", {"initiative_validated": "Fall Bundle"}, tool_class="SETTLEMENT_CALC")
    store.save("750", {"initiative_validated": ""}, tool_class="SETTLEMENT_CALC")
    assert store.initiative_usage() == {"Fall Bundle": 2}


def test_an_initiative_needs_a_name(store):
    import pytest as _pytest
    with _pytest.raises(ValueError):
        store.add_initiative("   ")
