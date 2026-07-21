"""Pure-logic tests for the redline-crop block detection (no PDF/Word needed).

These lock the rules Eduardo gave on 2026-07-17: a determinant's crop takes the
whole formula (IF/THEN/ELSE included), stops at a "Where", and drops prose —
while a footnote sitting between a formula's two halves is jumped over.
"""
from src.settlement import screenshots as S


def _line(page, top, text, det=None):
    # `bottom` only needs to be below `top`; geometry isn't exercised here.
    return {"page": page, "top": float(top), "bottom": float(top) - 8, "text": text, "def": det}


def test_is_prose_vs_formula():
    assert S._is_prose("(a.1) Based on the results of a Settlement Location deviation test")
    assert S._is_prose("1 Note that this charge type will almost always produce a charge")
    # Formula lines open with an operator or keyword even when they carry
    # lowercase tokens like "dir"/"rsg" — never prose.
    assert not S._is_prose("+RtMinLimitDevHrlyQty a, s, b, h")
    assert not S._is_prose("Min ( 0, RtImpExp5minQty a, s, b, i, t, dir, rsg(null) )")
    assert not S._is_prose("RtSlPosDev5minFct a, s, b, i = 0")


def test_looks_like_formula_paren_prose_is_not_formula():
    assert S._looks_like_formula("+RtStatusDevHrlyQty a, s, b, h")
    assert S._looks_like_formula("(RtDevHrlyQty a, s, b, h + RtDcTieMwpDistAdjHrlyQty a, s, b, h)")
    assert S._looks_like_formula("ELSE")
    # A paren that opens prose is NOT a formula (no CamelCase, no '=').
    assert not S._looks_like_formula("(a.1) Based on the results of a deviation test")


def test_det_matches_absorbs_glued_subscript():
    assert S._det_matches("RtSlPosDev5minFcta", "rtslposdev5minfct")   # trailing 'a' subscript
    assert S._det_matches("RtDevHrlyQty", "rtdevhrlyqty")
    assert not S._det_matches("RtDevHrlyQtyExtraLong", "rtdevhrlyqty")  # +>2 chars, no match


def test_block_stops_at_where():
    # #Det = ... \n (continuation) \n Where, \n (a) OtherDet = ...
    lines = [
        _line(0, 300, "#RtMwpDistHrlyAmt a, s, b, h = RtMwpBaaSppDistRate b, dd *", det="RtMwpDistHrlyAmt"),
        _line(0, 280, "(RtDevHrlyQty a, s, b, h + RtDcTieMwpDistAdjHrlyQty a, s, b, h)"),
        _line(0, 260, "Where,"),
        _line(0, 240, "(a) RtDevHrlyQty a, s, b, h = RtSlDevIncHrlyQty a, s, b, h", det="RtDevHrlyQty"),
    ]
    kept = S._block_lines(lines, 0, "rtmwpdisthrlyamt")
    assert kept == [0, 1]  # the Where and the next determinant are excluded


def test_block_keeps_else_value_of_same_determinant():
    # IF/THEN branch, ELSE, then "<same det> = 0" — all one formula.
    lines = [
        _line(0, 300, "#RtSlDevInc5minQty a, s, b, i =", det="RtSlDevInc5minQty"),
        _line(0, 280, "Min[ Max( RtNetSlIncDev5minQty a, s, b, i , 0),"),
        _line(1, 300, "RtSlPosDev5minFct a, s, b, i * RtSlDevTst5minQty s, b, i ]"),
        _line(1, 280, "ELSE"),
        _line(1, 260, "RtSlDevInc5minQty a, s, b, i = 0", det="RtSlDevInc5minQty"),
        _line(1, 240, "Where,"),
    ]
    kept = S._block_lines(lines, 0, "rtsldevinc5minqty")
    assert kept == [0, 1, 2, 3, 4]  # ELSE and the "= 0" value kept; stops at Where


def test_block_includes_if_then_header_above_definition():
    # "IF <cond> THEN <det> = … ELSE …": the IF/THEN sit ABOVE the def line and
    # must be part of the crop; the preceding Where is excluded.
    lines = [
        _line(0, 300, "Where,"),
        _line(0, 280, "IF RtSlDevTst5minQty s, b, i > 0"),
        _line(0, 260, "THEN"),
        _line(0, 240, "#RtSlDevInc5minQty a, s, b, i =", det="RtSlDevInc5minQty"),
        _line(0, 220, "Min[ Max( RtNetSlIncDev5minQty a, s, b, i , 0),"),
    ]
    kept = S._block_lines(lines, 3, "rtsldevinc5minqty")
    assert kept == [1, 2, 3, 4]  # IF, THEN, def, continuation — Where excluded


def test_compound_if_with_equals_is_not_read_as_a_definition():
    # "IF <det> = 1 and <det> < 0 THEN <det> = …": the IF line contains '=', so a
    # naive def regex reads "IF" as a determinant and the header is dropped. The
    # IF/THEN must still be prepended (RR728 item 17).
    doc_lines = [
        ("Where,", None),
        ("IF RtRucComStat5minFlg a,s,i,c = 1 and RtMwpDlyAmt a,s,b,d < 0", "IF"),
        ("THEN", None),
        ("#RtVirtReplace5minQty a, s, b, i =", "RtVirtReplace5minQty"),
        ("Max{ Min(0, RtBillMtr5minQty a,s,b,i), …", None),
    ]
    # _all_lines drops keyword "defs"; emulate by running the same guard here.
    lines = []
    for i, (text, raw_def) in enumerate(doc_lines):
        det = None if (raw_def and S._FORMULA_OPENER.match(raw_def)) else raw_def
        lines.append({"page": 0, "top": 300 - i * 20, "bottom": 300 - i * 20 - 8, "text": text, "def": det})
    kept = S._block_lines(lines, 3, "rtvirtreplace5minqty")
    assert kept == [1, 2, 3, 4]  # IF, THEN, def, continuation — not broken by the IF's '='


def test_no_header_prepended_without_an_if():
    # A determinant def directly under a previous formula's tail (no IF) must NOT
    # pull the tail in — the header is prepended only for a real conditional.
    lines = [
        _line(0, 300, "RtOther a, s, b, h = A + B", det="RtOther"),
        _line(0, 280, "+ C a, s, b, h"),
        _line(0, 260, "RtDevHrlyQty a, s, b, h = D + E", det="RtDevHrlyQty"),
    ]
    kept = S._block_lines(lines, 2, "rtdevhrlyqty")
    assert kept == [2]  # nothing above prepended


def test_def_name_distinguishes_defs_from_labels_and_conditions():
    # Real definitions (with dotted / double labels) return the determinant;
    # keyword openers and IF-conditions (comparison or trailing AND/OR) do not.
    assert S._def_name("(a) RtDevHrlyQty a, s, b, h = X + Y") == "RtDevHrlyQty"
    assert S._def_name("(b.2.3) RtMwpBaaDistHrlyQty b, h = Z") == "RtMwpBaaDistHrlyQty"
    assert S._def_name("(a) (b.2.5) RtDcTieBaaSinkHrlyQty b, h = Q") == "RtDcTieBaaSinkHrlyQty"
    assert S._def_name('IF RtRucComStat5minFlg a,s,i,c = 1 and X < 0') is None      # keyword
    assert S._def_name('DispInstrucMinHrlyFlg a, s, h = "1" AND') is None           # trailing AND
    assert S._def_name("RtBillMtr5minQty a, s, b, i <= 0") is None                  # comparison


def test_block_includes_bare_if_directly_above_def_without_then():
    # "(c) IF <cond> = 1 / <det> = … / ELSE / <det> = …": the IF sits directly
    # above the def with NO separate THEN line — still prepend it.
    lines = [
        ("(b.2.4) RtDcTieSppHrlyQty h = ABS(Z)", "RtDcTieSppHrlyQty"),
        ("(c) IF RtDcTieBaaSinkHrlyFlg b, h = 1", None),          # def nulled: keyword IF
        ("RtDcTieMwpDistAdjHrlyQty a, s, b, h =", "RtDcTieMwpDistAdjHrlyQty"),
        ("RtMwpBaaDistHrlyRatio a,s,b,h * RtDcTieSppHrlyQty b,h", None),
        ("ELSE", None),
        ("RtDcTieMwpDistAdjHrlyQty a, s, b, h =", "RtDcTieMwpDistAdjHrlyQty"),
    ]
    L = [{"page": 0, "top": 300 - i * 20, "bottom": 300 - i * 20 - 8, "text": t, "def": d}
         for i, (t, d) in enumerate(lines)]
    kept = S._block_lines(L, 2, "rtdctiemwpdistadjhrlyqty")
    assert kept[0] == 1 and S._IF_TOKEN.search(L[kept[0]]["text"])  # IF prepended
    assert 0 not in kept                                           # prior det excluded


def test_text_defines_matches_definitions_not_usages():
    # The text fallback (for Σ-image defs with no parsable '=') must accept a
    # real definition but reject a usage or a glossary row, so a determinant this
    # RR only references is skipped instead of cropping an unrelated fragment.
    d = lambda t: {"text": t}
    assert S._text_defines(d("RtNetSlDevHrlyQty a, s, b, h = ABS(x)"), "rtnetsldevhrlyqty")
    assert not S._text_defines(d("RtMwpCpAmt a, s, b, c * RtLrMwpFct a, s, sa, c"), "rtmwpcpamt")
    assert not S._text_defines(d("Represented by the product RtMwpCpAmt a, s, b, c *"), "rtmwpcpamt")
    assert not S._text_defines(d("RtMwpCpAmt a, s, b, c $ Eligibility RUC Make Whole Payment"), "rtmwpcpamt")


def test_block_jumps_footnote_between_formula_halves():
    # Formula continues on the next page AFTER a page-foot footnote; the footnote
    # (and page number) are skipped, the page-2 continuation is kept, and the
    # trailing prose paragraph ends the block.
    lines = [
        _line(0, 300, "(a) RtDevHrlyQty a, s, b, h = RtSlDevIncHrlyQty a, s, b, h", det="RtDevHrlyQty"),
        _line(0, 280, "+RtMinLimitDevHrlyQty a, s, b, h"),
        _line(0, 120, "1 Note that this charge type will almost always produce a charge"),
        _line(0, 60, "16"),
        _line(1, 300, "+RtStatusDevHrlyQty a, s, b, h + RtRucScDevHrlyQty a, s, b, h"),
        _line(1, 280, "(a.1) Based on the results of a Settlement Location deviation test that"),
        _line(1, 260, "determines the difference between the Day-Ahead and Real-Time quantities"),
    ]
    kept = S._block_lines(lines, 0, "rtdevhrlyqty")
    assert kept == [0, 1, 4]  # footnote + page number skipped; (a.1) prose excluded
