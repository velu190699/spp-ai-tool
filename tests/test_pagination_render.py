"""Retry behavior for the Word COM render (no real COM / pywin32 needed).

Locks the 2026-07-20 hardening: a transient COM rejection (RPC_E_CALL_REJECTED,
observed on a cold Word start) is retried instead of silently skipping the
screenshot tab, while a genuine error still fails fast.
"""
import sys
import types

import pytest

from src.settlement import pagination as P

RPC_E_CALL_REJECTED = -2147418111
CO_E_SERVER_EXEC_FAILURE = -2146959355


@pytest.fixture(autouse=True)
def _fake_pywin32(monkeypatch):
    # render_pdf_with_word import-guards on pywin32; inject stub modules so the
    # guard passes on machines/CI without pywin32 and the retry loop is reached.
    for name in ("pythoncom", "win32com", "win32com.client"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    yield


def _com_error(hresult):
    exc = Exception("Call was rejected by callee.")
    exc.hresult = hresult
    exc.args = (hresult, "Call was rejected by callee.", None, None)
    return exc


def test_transient_error_classification():
    assert P._is_transient_com_error(_com_error(RPC_E_CALL_REJECTED))
    assert P._is_transient_com_error(_com_error(CO_E_SERVER_EXEC_FAILURE))
    # A plain error with a transient HRESULT only in args[0] still counts.
    assert P._is_transient_com_error(Exception(RPC_E_CALL_REJECTED))
    # Non-transient COM error (e.g. a real "file not found" HRESULT) does not.
    assert not P._is_transient_com_error(_com_error(-2147024894))
    assert not P._is_transient_com_error(ValueError("nope"))


def test_retries_transient_then_succeeds(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_once(docx, pdf, with_markup):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _com_error(RPC_E_CALL_REJECTED)
        pdf.write_bytes(b"%PDF-1.7\n")  # third attempt "renders"
        return True

    monkeypatch.setattr(P, "_render_pdf_once", fake_once)
    ok = P.render_pdf_with_word(tmp_path / "d.docx", tmp_path / "out.pdf",
                                with_markup=True, max_attempts=3, backoff_seconds=0)
    assert ok is True
    assert calls["n"] == 3


def test_gives_up_after_max_attempts(monkeypatch, tmp_path):
    calls = {"n": 0}

    def always_reject(docx, pdf, with_markup):
        calls["n"] += 1
        raise _com_error(RPC_E_CALL_REJECTED)

    monkeypatch.setattr(P, "_render_pdf_once", always_reject)
    ok = P.render_pdf_with_word(tmp_path / "d.docx", tmp_path / "out.pdf",
                                max_attempts=3, backoff_seconds=0)
    assert ok is False
    assert calls["n"] == 3  # exhausted, not infinite


def test_non_transient_fails_fast_without_retry(monkeypatch, tmp_path):
    calls = {"n": 0}

    def hard_fail(docx, pdf, with_markup):
        calls["n"] += 1
        raise _com_error(-2147024894)  # ERROR_FILE_NOT_FOUND HRESULT — not transient

    monkeypatch.setattr(P, "_render_pdf_once", hard_fail)
    ok = P.render_pdf_with_word(tmp_path / "d.docx", tmp_path / "out.pdf",
                                max_attempts=3, backoff_seconds=0)
    assert ok is False
    assert calls["n"] == 1  # no retry on a genuine error


def test_com_call_retries_transient_then_returns(monkeypatch):
    # A post-Open call (ActiveWindow.View) rejected while Word lays out the doc
    # is retried in place and eventually returns, without relaunching Word.
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _com_error(RPC_E_CALL_REJECTED)
        return "view-set"

    assert P._com_call(flaky, attempts=6, backoff_seconds=0) == "view-set"
    assert calls["n"] == 2


def test_com_call_reraises_non_transient(monkeypatch):
    monkeypatch.setattr(P.time, "sleep", lambda s: None)

    def bad():
        raise _com_error(-2147024894)  # not transient

    with pytest.raises(Exception):
        P._com_call(bad, attempts=6, backoff_seconds=0)


def test_empty_result_is_retried(monkeypatch, tmp_path):
    # _render_pdf_once returning False (no exception, but no PDF on disk) is also
    # retried — a half-started server can return without writing the file.
    calls = {"n": 0}

    def flaky(docx, pdf, with_markup):
        calls["n"] += 1
        if calls["n"] < 2:
            return False
        pdf.write_bytes(b"%PDF-1.7\n")
        return True

    monkeypatch.setattr(P, "_render_pdf_once", flaky)
    ok = P.render_pdf_with_word(tmp_path / "d.docx", tmp_path / "out.pdf",
                                max_attempts=3, backoff_seconds=0)
    assert ok is True
    assert calls["n"] == 2
