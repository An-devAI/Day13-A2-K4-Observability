from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import audit


@pytest.fixture()
def audit_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(target))
    return target


def test_record_writes_one_json_object_per_line(audit_file: Path) -> None:
    audit.record(audit.INCIDENT_ENABLE, actor="coach", details={"name": "rag_slow"})
    audit.record(audit.INCIDENT_DISABLE, actor="coach", details={"name": "rag_slow"})

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["action"] == audit.INCIDENT_ENABLE
    assert first["actor"] == "coach"
    assert first["event"] == "audit"
    assert first["outcome"] == "success"
    assert first["ts"].endswith("Z")


def test_record_appends_rather_than_truncating(audit_file: Path) -> None:
    """Audit log phải giữ lại lịch sử; một lần ghi mới không được xoá cái cũ."""
    audit.record(audit.APP_START)
    audit.record(audit.APP_START)
    audit.record(audit.CONFIG_CHANGE, details={"key": "MAX_OUTPUT_TOKENS"})

    assert len(audit.read_all()) == 3


def test_pii_in_details_is_scrubbed_before_writing(audit_file: Path) -> None:
    """Audit log không được trở thành đường rò PII mới."""
    audit.record(
        audit.CONFIG_CHANGE,
        details={"note": "lien he a.nguyen@example.com hoac 0912345678", "nested": ["0912345678"]},
    )

    raw = audit_file.read_text(encoding="utf-8")
    assert "a.nguyen@example.com" not in raw
    assert "0912345678" not in raw
    assert "[REDACTED_EMAIL]" in raw
    assert raw.count("[REDACTED_PHONE_VN]") == 2


def test_rejected_outcome_is_recorded(audit_file: Path) -> None:
    """Cố đổi một incident không tồn tại cũng phải để lại dấu vết."""
    audit.record(
        audit.INCIDENT_ENABLE,
        actor="someone",
        outcome="rejected",
        details={"name": "khong_ton_tai"},
    )

    entry = audit.read_all()[0]
    assert entry["outcome"] == "rejected"
    assert entry["details"]["name"] == "khong_ton_tai"


def test_read_all_returns_empty_when_file_missing(audit_file: Path) -> None:
    assert not audit_file.exists()
    assert audit.read_all() == []
