from datetime import UTC, datetime, timedelta

import pytest

from soar.tools.triage_policy import TriagePolicyError
from soar.tools.watermark import WatermarkStore
from soar.workflows.alert_triage import (
    AlertTriageWorkflow,
    calculate_verdict,
    make_source_ref,
)

NOW = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)


def _policies(**overrides):
    return {
        "whitelist": [],
        "blacklist": [],
        "critical_assets": [],
        "count_threshold": 3,
        "severity_gate": 3,
        **overrides,
    }


class FakePolicyCache:
    def __init__(self, policies=None, error=None):
        self._policies = policies or _policies()
        self._error = error

    def get(self):
        if self._error:
            raise self._error
        return self._policies


class FakeIRP:
    """Records call order and ingest payloads."""

    def __init__(self, ingest_actions=None, fail_on_call=None):
        self.calls = []
        self.ingested = []
        self._actions = list(ingest_actions or [])
        self._fail_on_call = fail_on_call

    def send_heartbeat(self):
        self.calls.append("heartbeat")
        return True

    def ingest_alert(self, **kwargs):
        self.calls.append("ingest")
        if self._fail_on_call is not None and len(self.ingested) + 1 == self._fail_on_call:
            raise ConnectionError("IRP down mid-chunk")
        self.ingested.append(kwargs)
        action = self._actions.pop(0) if self._actions else "created"
        return {"id": len(self.ingested), "action": action}


class FakeElastic:
    def __init__(self, docs=None, docs_per_chunk=None):
        self._docs = docs or []
        self._docs_per_chunk = docs_per_chunk  # callable(start_iso, end_iso) -> docs
        self.queries = []

    def query(self, index, dsl):
        rng = dsl["query"]["range"]["@timestamp"]
        self.queries.append((rng["gte"], rng["lt"]))
        if self._docs_per_chunk is not None:
            return self._docs_per_chunk(rng["gte"], rng["lt"])
        return [d for d in self._docs if rng["gte"] <= d["@timestamp"] < rng["lt"]]


def _doc(rule="Suspicious login", host="srv01", sev="high", ts=None, **extra):
    return {
        "@timestamp": (ts or (NOW - timedelta(minutes=5)).isoformat()),
        "kibana.alert.rule.name": rule,
        "host.name": host,
        "kibana.alert.severity": sev,
        "_id": f"doc-{len(extra)}",
        **extra,
    }


@pytest.fixture
def settings(tmp_path):
    return {
        "enabled": True,
        "shadow": True,
        "alerts_index": ".internal.alerts-*",
        "watermark_path": str(tmp_path / "wm.json"),
        "time_window_minutes": 10,
        "overlap_minutes": 5,
        "fetch_size": 1000,
    }


def _wf(settings, irp, elastic, policies=None, policy_error=None, **kwargs):
    return AlertTriageWorkflow(
        irp=irp,
        elastic=elastic,
        policy_cache=FakePolicyCache(policies, policy_error),
        watermark=WatermarkStore(settings["watermark_path"]),
        settings=settings,
        now=NOW,
        **kwargs,
    )


# ── cycle basics ──────────────────────────────────────────────────────────

def test_heartbeat_sent_before_ingest(settings):
    irp = FakeIRP()
    wf = _wf(settings, irp, FakeElastic([_doc(sev="critical")]))
    wf.run({})
    assert irp.calls[0] == "heartbeat"
    assert "ingest" in irp.calls


def test_first_run_single_window_not_epoch(settings):
    irp = FakeIRP()
    elastic = FakeElastic([])
    wf = _wf(settings, irp, elastic)
    result = wf.run({})
    assert elastic.queries == [((NOW - timedelta(minutes=10)).isoformat(), NOW.isoformat())]
    assert result["backfill_chunks"] == 0
    assert result["watermark"] == NOW.isoformat()


def test_policy_error_aborts_cycle_before_fetch(settings):
    irp = FakeIRP()
    elastic = FakeElastic([_doc()])
    wf = _wf(settings, irp, elastic, policy_error=TriagePolicyError("no cache"))
    outcome = wf.execute({})
    assert outcome.success is False
    assert elastic.queries == []
    assert irp.ingested == []


def test_disabled_integration_skips(settings):
    settings["enabled"] = False
    irp = FakeIRP()
    wf = _wf(settings, irp, FakeElastic([_doc()]))
    assert wf.run({}) == {"skipped": "irp integration disabled"}
    assert irp.calls == []


# ── triage gates (every drop counted, never silent) ───────────────────────

def test_whitelist_drop_counted(settings):
    irp = FakeIRP()
    wf = _wf(settings, irp, FakeElastic([_doc(rule="Known scanner", sev="critical")]),
             policies=_policies(whitelist=["Known*"]))
    result = wf.run({})
    assert result["dropped"]["whitelist"] == 1
    assert irp.ingested == []


def test_below_threshold_drop_counted(settings):
    irp = FakeIRP()
    docs = [_doc(sev="low"), _doc(sev="low")]
    wf = _wf(settings, irp, FakeElastic(docs), policies=_policies(count_threshold=3))
    result = wf.run({})
    assert result["dropped"]["below_threshold"] == 1
    assert irp.ingested == []


def test_gate_passes_on_count_even_if_low_severity(settings):
    """Legacy gate (assumption Д-1): sev >= 3 OR count >= threshold."""
    irp = FakeIRP()
    docs = [_doc(sev="low") for _ in range(3)]
    wf = _wf(settings, irp, FakeElastic(docs), policies=_policies(count_threshold=3))
    result = wf.run({})
    assert result["ingested_created"] == 1
    assert irp.ingested[0]["event_count"] == 3


def test_blacklist_escalates_to_sev4(settings):
    irp = FakeIRP()
    wf = _wf(settings, irp, FakeElastic([_doc(host="dmz-gw", sev="low")]),
             policies=_policies(blacklist=[{"entity": "dmz-*"}]))
    result = wf.run({})
    assert result["ingested_created"] == 1
    alert = irp.ingested[0]
    assert alert["severity"] == 4
    assert "priority:critical" in alert["tags"]
    assert "blacklist match" in alert["description"]


def test_critical_asset_escalates(settings):
    irp = FakeIRP()
    wf = _wf(settings, irp, FakeElastic([_doc(host="dc01", sev="medium")]),
             policies=_policies(critical_assets=["dc01"]))
    wf.run({})
    assert irp.ingested[0]["severity"] == 4
    assert "critical asset" in irp.ingested[0]["description"]


def test_cve_patched_drop_visible(settings):
    irp = FakeIRP()
    checker_calls = []

    def cve_checker(entity, cves):
        checker_calls.append((entity, cves))
        return True  # patched

    wf = _wf(settings, irp, FakeElastic([_doc(rule="Exploit CVE-2024-12345", sev="critical")]),
             cve_checker=cve_checker)
    result = wf.run({})
    assert result["dropped"]["cve_patched"] == 1
    assert checker_calls == [("srv01", ["CVE-2024-12345"])]
    assert irp.ingested == []


def test_cve_without_checker_still_ingested(settings):
    irp = FakeIRP()
    wf = _wf(settings, irp, FakeElastic([_doc(rule="Exploit CVE-2024-12345", sev="critical")]))
    result = wf.run({})
    assert result["ingested_created"] == 1


def test_ti_enricher_raises_verdict(settings):
    irp = FakeIRP()
    wf = _wf(settings, irp, FakeElastic([_doc(sev="high")]),
             ti_enricher=lambda observables: 2)
    wf.run({})
    alert = irp.ingested[0]
    assert alert["verdict_text"] == "malicious"
    assert alert["verdict_score"] >= 70


# ── ingest contract fields ────────────────────────────────────────────────

def test_shadow_mode_tags(settings):
    irp = FakeIRP()
    wf = _wf(settings, irp, FakeElastic([_doc(sev="critical")]))
    wf.run({})
    assert "soar:shadow" in irp.ingested[0]["tags"]
    assert "sys:soar" in irp.ingested[0]["tags"]


def test_no_shadow_tag_after_cutover(settings):
    settings["shadow"] = False
    irp = FakeIRP()
    wf = _wf(settings, irp, FakeElastic([_doc(sev="critical")]))
    wf.run({})
    assert "soar:shadow" not in irp.ingested[0]["tags"]


def test_observables_only_public_ip_and_hashes(settings):
    irp = FakeIRP()
    doc = _doc(sev="critical")
    doc["source.ip"] = "10.0.0.5"       # private — must be excluded
    doc["destination.ip"] = "8.8.8.8"   # public — included
    doc["file.hash.sha256"] = "a" * 64
    wf = _wf(settings, irp, FakeElastic([doc]))
    wf.run({})
    observables = irp.ingested[0]["observables"]
    assert {"dataType": "ip", "data": "8.8.8.8"} in observables
    assert {"dataType": "hash", "data": "a" * 64} in observables
    assert not any(o["data"] == "10.0.0.5" for o in observables)


def test_all_three_ingest_actions_counted(settings):
    irp = FakeIRP(ingest_actions=["created", "merged", "skipped"])
    docs = [
        _doc(rule="R1", sev="critical"),
        _doc(rule="R2", sev="critical"),
        _doc(rule="R3", sev="critical"),
    ]
    wf = _wf(settings, irp, FakeElastic(docs))
    result = wf.run({})
    assert result["ingested_created"] == 1
    assert result["ingested_merged"] == 1
    assert result["skipped_irp"] == 1


# ── watermark / backfill (contract §4.3) ──────────────────────────────────

def test_six_hours_downtime_chunked_replay(settings):
    """6h of downtime → 36 chunks of 10 min (+1 for the 5-min overlap),
    watermark advances chunk by chunk, all ingests flagged backfill."""
    WatermarkStore(settings["watermark_path"]).set(
        "siem_alerts", (NOW - timedelta(hours=6)).isoformat()
    )
    irp = FakeIRP()
    elastic = FakeElastic(docs_per_chunk=lambda s, e: [_doc(sev="critical", ts=s)])
    wf = _wf(settings, irp, elastic)
    result = wf.run({})
    assert len(elastic.queries) == 37  # 6h05m / 10m
    assert result["backfill_chunks"] == 37
    assert result["watermark"] == NOW.isoformat()
    assert all(a["backfill"] is True for a in irp.ingested)
    # chunk boundaries are contiguous
    assert elastic.queries[0][0] == (NOW - timedelta(hours=6, minutes=5)).isoformat()
    assert all(elastic.queries[i][1] == elastic.queries[i + 1][0] for i in range(36))


def test_single_window_lag_is_not_backfill(settings):
    WatermarkStore(settings["watermark_path"]).set(
        "siem_alerts", (NOW - timedelta(minutes=5)).isoformat()
    )
    irp = FakeIRP()
    wf = _wf(settings, irp, FakeElastic([_doc(sev="critical")]))
    result = wf.run({})
    assert result["backfill_chunks"] == 0
    assert irp.ingested[0]["backfill"] is False


def test_failed_ingest_does_not_advance_watermark(settings):
    """Ingest dies mid-chunk → the watermark stays at the previous chunk."""
    start_wm = (NOW - timedelta(minutes=25)).isoformat()
    store = WatermarkStore(settings["watermark_path"])
    store.set("siem_alerts", start_wm)
    # 3 chunks: [-30,-20), [-20,-10), [-10, now); one alert each; die on 2nd ingest
    irp = FakeIRP(fail_on_call=2)
    elastic = FakeElastic(docs_per_chunk=lambda s, e: [_doc(sev="critical", ts=s)])
    wf = _wf(settings, irp, elastic)
    outcome = wf.execute({})
    assert outcome.success is False
    # first chunk completed → watermark = its end; second chunk failed → frozen
    assert store.get("siem_alerts") == (NOW - timedelta(minutes=20)).isoformat()


def test_replay_after_failure_is_idempotent(settings):
    """Re-run after a failure sends the same source_ref → merged on IRP side."""
    store = WatermarkStore(settings["watermark_path"])
    store.set("siem_alerts", (NOW - timedelta(minutes=5)).isoformat())
    ts = (NOW - timedelta(minutes=3)).isoformat()

    irp1 = FakeIRP()
    wf1 = _wf(settings, irp1, FakeElastic([_doc(sev="critical", ts=ts)]))
    wf1.run({})

    # watermark moved; next cycle re-reads the overlap and sees the same doc
    irp2 = FakeIRP(ingest_actions=["merged"])
    wf2 = AlertTriageWorkflow(
        irp=irp2, elastic=FakeElastic([_doc(sev="critical", ts=ts)]),
        policy_cache=FakePolicyCache(), watermark=store, settings=settings,
        now=NOW + timedelta(minutes=1),
    )
    result = wf2.run({})
    assert irp2.ingested[0]["source_ref"] == irp1.ingested[0]["source_ref"]
    assert result["ingested_merged"] == 1


# ── helpers ───────────────────────────────────────────────────────────────

def test_make_source_ref_event_time_bucket():
    ref1 = make_source_ref("Rule", "host", datetime(2026, 7, 5, 10, 41, tzinfo=UTC), 10)
    ref2 = make_source_ref("Rule", "host", datetime(2026, 7, 5, 10, 49, tzinfo=UTC), 10)
    ref3 = make_source_ref("Rule", "host", datetime(2026, 7, 5, 10, 51, tzinfo=UTC), 10)
    assert ref1 == ref2          # same 10-min bucket
    assert ref1 != ref3          # next bucket
    assert ref1.endswith("-20260705-1040")
    assert make_source_ref("Other", "host", datetime(2026, 7, 5, 10, 41, tzinfo=UTC), 10) != ref1


def test_calculate_verdict_bands():
    assert calculate_verdict(1, 1, None)[1] == "informational"
    assert calculate_verdict(3, 5, None)[1] == "suspicious"
    assert calculate_verdict(4, 10, 2)[1] == "malicious"
    assert calculate_verdict(4, 1000, 100)[0] == 100
