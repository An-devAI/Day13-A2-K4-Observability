from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_dashboard import build, compute_panels, percentile, threshold_ok
from scripts.validate_dashboard import DashboardConfigError

CONTRACT = REPO_ROOT / "config" / "dashboard.yaml"


def write_logs(path: Path, count: int = 4, latency_ms: int = 150) -> Path:
    """Ghi một đợt log tối thiểu nhưng đủ trường cho cả 6 panel."""
    base = datetime.now(timezone.utc) - timedelta(minutes=2)
    lines = []
    for index in range(count):
        stamp = (base + timedelta(seconds=index)).isoformat().replace("+00:00", "Z")
        common = {"ts": stamp, "level": "info", "service": "api", "correlation_id": f"req-{index:08x}"}
        lines.append({**common, "event": "request_received"})
        lines.append(
            {
                **common,
                "event": "response_sent",
                "latency_ms": latency_ms + index,
                "tokens_in": 40,
                "tokens_out": 100,
                "cost_usd": 0.0015,
                "quality_score": 0.9,
            }
        )
    path.write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
        encoding="utf-8",
    )
    return path


def test_percentile_uses_nearest_rank() -> None:
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 100
    assert percentile([], 95) == 0.0


@pytest.mark.parametrize(
    ("value", "operator", "limit", "expected"),
    [
        (2999, "lte", 3000, True),
        (3001, "lte", 3000, False),
        (0.9, "gte", 0.75, True),
        (0.5, "gte", 0.75, False),
    ],
)
def test_threshold_respects_contract_operator(
    value: float, operator: str, limit: float, expected: bool
) -> None:
    assert threshold_ok(value, operator, limit) is expected


def test_error_rate_counts_failed_over_received() -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    records = [
        {"ts": now, "event": "request_received"},
        {"ts": now, "event": "request_received"},
        {"ts": now, "event": "request_received"},
        {"ts": now, "event": "request_received"},
        {"ts": now, "event": "request_failed", "error_type": "RuntimeError"},
    ]

    errors = compute_panels(records)["errors"]

    assert errors["metric"] == pytest.approx(25.0)
    assert errors["bars"] == [("RuntimeError", 1)]


def test_build_renders_every_panel_declared_in_contract(tmp_path: Path) -> None:
    out = tmp_path / "dashboard.html"

    result = build(CONTRACT, write_logs(tmp_path / "logs.jsonl"), out)

    rendered = out.read_text(encoding="utf-8")
    for panel in result["config"]["dashboard"]["panels"]:
        assert panel["title"] in rendered
        assert panel["unit"] in rendered
        assert f'<span class="pid">{panel["id"]}</span>' in rendered
    assert rendered.count('<section class="panel"') == 6


def test_build_reports_a_panel_that_breaches_its_threshold(tmp_path: Path) -> None:
    """latency vượt 3000 ms phải hiện chip vượt ngưỡng, không phải chip đạt."""
    out = tmp_path / "dashboard.html"

    build(CONTRACT, write_logs(tmp_path / "logs.jsonl", latency_ms=9000), out)

    rendered = out.read_text(encoding="utf-8")
    assert 'class="chip bad"' in rendered


def test_build_refuses_to_render_from_an_invalid_contract(tmp_path: Path) -> None:
    """Dashboard không được phép lệch contract: contract hỏng thì không có ảnh."""
    payload = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    payload["dashboard"]["panels"][0].pop("threshold")
    broken = tmp_path / "dashboard.yaml"
    broken.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    out = tmp_path / "dashboard.html"

    with pytest.raises(DashboardConfigError):
        build(broken, write_logs(tmp_path / "logs.jsonl"), out)

    assert not out.exists()
