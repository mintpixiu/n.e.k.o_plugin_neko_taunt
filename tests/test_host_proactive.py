"""Tests for the host proactive-chat probe (no real network in CI)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

host_proactive = pytest.importorskip("host_proactive")


def test_loopback_url_validation() -> None:
    assert host_proactive.is_loopback_base_url("http://127.0.0.1:48911")
    assert host_proactive.is_loopback_base_url("http://localhost:48911")
    assert host_proactive.is_loopback_base_url("http://[::1]:48911")
    for bad in (
        "https://127.0.0.1:48911",
        "http://example.com:48911",
        "http://127.0.0.1.evil:48911",
        "http://user:pass@127.0.0.1:48911",
        "http://127.0.0.1:48911/other",
        "http://127.0.0.1:48911?x=1",
    ):
        assert not host_proactive.is_loopback_base_url(bad), bad


def test_parse_payload_reads_switch_and_interval() -> None:
    state = host_proactive.parse_host_proactive_payload({
        "success": True,
        "mode": "normal",
        "settings": {"proactiveChatEnabled": True, "proactiveChatInterval": 120},
    })
    assert state.available is True
    assert state.enabled is True
    assert state.interval_seconds == 120
    assert state.mode == "normal"
    assert state.as_dict()["enabled"] is True


def test_parse_payload_handles_disabled_and_bad_shapes() -> None:
    disabled = host_proactive.parse_host_proactive_payload({
        "success": True,
        "mode": "off",
        "settings": {"proactiveChatEnabled": False, "proactiveChatInterval": 0},
    })
    assert disabled.available is True
    assert disabled.enabled is False
    assert disabled.interval_seconds == 0

    for bad in (None, [], {}, {"success": False}, {"success": True, "settings": []}):
        state = host_proactive.parse_host_proactive_payload(bad)
        assert state.available is False
        assert state.enabled is False


def test_non_loopback_fetch_is_refused_without_network() -> None:
    state = host_proactive.fetch_host_proactive("http://example.com:48911")
    assert state.available is False
    assert state.error == "non_loopback_url"


def test_probe_caches_and_can_be_forced() -> None:
    calls = {"n": 0}
    now = {"t": 100.0}

    def fake_fetch() -> host_proactive.HostProactiveState:
        calls["n"] += 1
        return host_proactive.HostProactiveState(True, True, 120, "normal")

    probe = host_proactive.HostProactiveProbe(
        fetcher=fake_fetch,
        ttl_seconds=30.0,
        clock=lambda: now["t"],
    )
    first = probe.get()
    second = probe.get()
    assert first == second
    assert calls["n"] == 1

    now["t"] += 31
    probe.get()
    assert calls["n"] == 2

    probe.get(force=True)
    assert calls["n"] == 3


def test_fetch_parses_a_fake_response(monkeypatch) -> None:
    body = json.dumps({
        "success": True,
        "mode": "frequent",
        "settings": {"proactiveChatEnabled": True, "proactiveChatInterval": 60},
    }).encode("utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit: int) -> bytes:
            return body

    def fake_urlopen(request, timeout):  # noqa: ANN001
        assert request.full_url == "http://127.0.0.1:48911/api/proactive/mode"
        assert timeout > 0
        return FakeResponse()

    monkeypatch.setattr(host_proactive, "urlopen", fake_urlopen)
    state = host_proactive.fetch_host_proactive()
    assert state.available is True
    assert state.enabled is True
    assert state.interval_seconds == 60
    assert state.mode == "frequent"


def test_probe_is_loopback_only_by_construction() -> None:
    text = (ROOT / "host_proactive.py").read_text(encoding="utf-8")
    assert "http://127.0.0.1:48911" in text
    assert "example.com" not in text
    assert "https://" not in text