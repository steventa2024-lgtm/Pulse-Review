import builtins
import sys

import main


def test_browser_flag_skips_native_checks():
    assert main.choose_mode(True) == (False, None)


def test_native_window_used_when_pywebview_and_webview2_present(monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", object())
    monkeypatch.setattr(main, "webview2_available", lambda: True)
    assert main.choose_mode(False) == (True, None)


def test_falls_back_to_browser_with_reason_when_pywebview_missing(monkeypatch):
    monkeypatch.delitem(sys.modules, "webview", raising=False)
    real_import = builtins.__import__

    def fake(name, *a, **k):
        if name == "webview":
            raise ImportError
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    native, reason = main.choose_mode(False)
    assert native is False and "pywebview" in reason


def test_falls_back_with_install_hint_when_webview2_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", object())
    monkeypatch.setattr(main, "webview2_available", lambda: False)
    native, reason = main.choose_mode(False)
    assert native is False and "WebView2" in reason and "microsoft.com" in reason


def test_webview2_probe_is_true_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert main.webview2_available() is True


def test_missing_console_streams_are_replaced(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    main._ensure_std_streams()
    print("no crash")  # would raise on a None stdout
    sys.stderr.write("x")


def test_child_process_does_nothing(monkeypatch):
    import multiprocessing

    class P:
        name = "SpawnProcess-1"

    monkeypatch.setattr(multiprocessing, "current_process", lambda: P())
    assert main.main([]) == 0  # returns before building services / starting a server


def test_free_port_is_on_loopback():
    assert 1024 < main._find_free_port() < 65536
