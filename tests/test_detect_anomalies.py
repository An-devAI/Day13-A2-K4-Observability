from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.detect_anomalies import (
    analyse,
    detect_hygiene,
    detect_pii,
    detect_slo,
    load_objectives,
)

SLO_PATH = REPO_ROOT / "config" / "slo.yaml"


def stamp(offset_seconds: int = 0) -> str:
    moment = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return moment.isoformat().replace("+00:00", "Z")


def api_record(event: str, **fields) -> dict:
    return {
        "ts": stamp(),
        "level": "info",
        "service": "api",
        "event": event,
        "correlation_id": "req-0000beef",
        "user_id_hash": "abc123",
        "session_id": "s1",
        "feature": "qa",
        "model": "claude-sonnet-4-5",
        **fields,
    }


def test_objectives_come_from_slo_yaml_not_hardcoded() -> None:
    objectives = load_objectives(SLO_PATH)
    declared = yaml.safe_load(SLO_PATH.read_text(encoding="utf-8"))["slis"]

    assert set(objectives) == set(declared)
    for name, spec in declared.items():
        assert objectives[name] == float(spec["objective"])


def test_detects_email_left_in_a_log_record() -> None:
    records = [api_record("request_received", payload={"message_preview": "mail a@b.com"})]

    findings = detect_pii(records)

    assert len(findings) == 1
    assert findings[0]["severity"] == "critical"
    assert "email" in findings[0]["types"]


def test_vietnamese_prose_is_not_reported_as_an_address_leak() -> None:
    """address_vn cố tình bị loại khỏi bộ quét: nó khớp cả văn bản thường."""
    records = [api_record("request_received", payload={"message_preview": "Quận 1 Phường 5"})]

    assert detect_pii(records) == []


def test_latency_breach_maps_to_the_declared_alert() -> None:
    objectives = load_objectives(SLO_PATH)
    records = [api_record("response_sent", latency_ms=99000) for _ in range(5)]

    findings = [f for f in detect_slo(records, objectives) if f.get("sli") == "latency_p95_ms"]

    assert len(findings) == 1
    assert findings[0]["severity"] == "critical"
    assert findings[0]["alert"] == "HighLatencyP95"


def test_latency_within_objective_produces_no_finding() -> None:
    objectives = load_objectives(SLO_PATH)
    records = [api_record("response_sent", latency_ms=150) for _ in range(5)]

    assert [f for f in detect_slo(records, objectives) if f.get("sli") == "latency_p95_ms"] == []


def test_error_rate_breach_includes_the_breakdown() -> None:
    objectives = load_objectives(SLO_PATH)
    records = [api_record("request_received") for _ in range(10)]
    records += [api_record("request_failed", error_type="RuntimeError") for _ in range(3)]

    findings = [f for f in detect_slo(records, objectives) if f.get("sli") == "error_rate_pct"]

    assert len(findings) == 1
    assert findings[0]["breakdown"] == {"RuntimeError": 3}
    assert findings[0]["alert"] == "HighErrorRate"


def test_missing_correlation_id_is_critical() -> None:
    records = [{"ts": stamp(), "service": "api", "event": "request_received", "correlation_id": "MISSING"}]

    findings = detect_hygiene(records)

    assert findings[0]["kind"] == "log_hygiene"
    assert findings[0]["severity"] == "critical"


def test_clean_log_produces_no_findings(tmp_path: Path) -> None:
    log = tmp_path / "logs.jsonl"
    records = [api_record("request_received") for _ in range(3)]
    records += [
        api_record("response_sent", latency_ms=150, tokens_in=40, tokens_out=100,
                   cost_usd=0.0015, quality_score=0.9)
        for _ in range(3)
    ]
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    assert analyse(log, SLO_PATH, minutes=60) == []


def test_window_with_no_traffic_is_flagged(tmp_path: Path) -> None:
    """Cửa sổ rỗng phải được báo, vì dashboard rỗng dễ bị đọc nhầm là hệ thống khoẻ."""
    log = tmp_path / "logs.jsonl"
    log.write_text(json.dumps({"ts": stamp(), "event": "app_started", "level": "info"}) + "\n", encoding="utf-8")

    findings = analyse(log, SLO_PATH, minutes=60)

    assert [f["kind"] for f in findings] == ["traffic_gap"]
