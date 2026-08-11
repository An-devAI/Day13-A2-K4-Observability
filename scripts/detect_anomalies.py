"""Quét data/logs.jsonl và báo anomaly — chạy được trong CI hoặc pre-commit.

Ngưỡng KHÔNG hard-code: đọc thẳng từ config/slo.yaml nên detector luôn khớp với
SLO và alert rules của nhóm. Đổi objective trong slo.yaml là detector đổi theo.

Bốn nhóm phát hiện:
  1. pii_leak      — dữ liệu cá nhân lọt vào log (critical, luôn quét toàn file)
  2. slo_breach    — latency p95 / error rate / cost / quality vượt objective
  3. log_hygiene   — bản ghi service=api thiếu correlation_id hoặc thiếu enrichment
  4. traffic_gap   — cửa sổ không có request nào (dashboard sẽ rỗng, dễ tưởng là ổn)

Exit code 0 nếu không có phát hiện mức critical, 1 nếu có — để CI chặn được.

Ví dụ:
    python scripts/detect_anomalies.py
    python scripts/detect_anomalies.py --window-minutes 0 --json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.pii import PII_PATTERNS

# Chỉ dùng các mẫu định danh chặt chẽ. Cố ý bỏ 'address_vn' vì mẫu đó khớp cả
# những từ thông thường như "Quận"/"Phường" trong văn bản tiếng Việt bình
# thường, dùng để quét log sẽ báo giả liên tục.
LEAK_PATTERNS = {
    name: re.compile(pattern)
    for name, pattern in PII_PATTERNS.items()
    if name in {"email", "phone_vn", "cccd", "credit_card", "passport"}
}

ENRICHMENT_FIELDS = {"user_id_hash", "session_id", "feature", "model"}
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


class Finding(dict):
    def __init__(self, kind: str, severity: str, summary: str, **extra: Any) -> None:
        super().__init__(kind=kind, severity=severity, summary=summary, **extra)


# --------------------------------------------------------------------------- #
def load_objectives(slo_path: Path) -> dict[str, float]:
    payload = yaml.safe_load(slo_path.read_text(encoding="utf-8"))
    slis = (payload or {}).get("slis") or {}
    return {name: float(spec["objective"]) for name, spec in slis.items() if "objective" in spec}


def load_records(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.exists():
        raise SystemExit(f"Không tìm thấy {log_path}. Chạy API và load test trước.")
    records = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def parse_ts(record: dict[str, Any]) -> datetime | None:
    raw = record.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def scope(records: list[dict], minutes: int) -> list[dict]:
    """minutes <= 0 nghĩa là lấy toàn bộ file."""
    if minutes <= 0:
        return records
    stamps = [ts for ts in (parse_ts(r) for r in records) if ts is not None]
    if not stamps:
        return records
    cutoff = max(stamps) - timedelta(minutes=minutes)
    return [r for r in records if (parse_ts(r) or cutoff) >= cutoff]


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return sorted(values)[min(len(values) - 1, max(0, math.ceil(q / 100 * len(values)) - 1))]


# --------------------------------------------------------------------------- #
def detect_pii(records: list[dict]) -> list[Finding]:
    """Quét PII trên TOÀN BỘ file, không giới hạn cửa sổ: một lần rò rỉ đã là rò rỉ."""
    hits: Counter[str] = Counter()
    samples: dict[str, str] = {}
    events: set[str] = set()
    for record in records:
        raw = json.dumps(record, ensure_ascii=False)
        for name, detector in LEAK_PATTERNS.items():
            found = detector.search(raw)
            if found:
                hits[name] += 1
                events.add(str(record.get("event", "unknown")))
                samples.setdefault(name, found.group(0)[:4] + "…")
    if not hits:
        return []
    return [
        Finding(
            "pii_leak",
            "critical",
            f"{sum(hits.values())} bản ghi chứa PII chưa che ({', '.join(sorted(hits))})",
            types=dict(hits),
            events=sorted(events),
            redacted_samples=samples,
        )
    ]


def detect_slo(records: list[dict], objectives: dict[str, float]) -> list[Finding]:
    sent = [r for r in records if r.get("event") == "response_sent"]
    received = [r for r in records if r.get("event") == "request_received"]
    failed = [r for r in records if r.get("event") == "request_failed"]
    findings: list[Finding] = []

    def nums(rows: list[dict], field: str) -> list[float]:
        return [r[field] for r in rows if isinstance(r.get(field), (int, float))]

    if sent and "latency_p95_ms" in objectives:
        p95 = percentile(nums(sent, "latency_ms"), 95)
        if p95 > objectives["latency_p95_ms"]:
            findings.append(
                Finding(
                    "slo_breach",
                    "critical",
                    f"latency p95 {p95:.0f} ms vượt objective {objectives['latency_p95_ms']:.0f} ms",
                    sli="latency_p95_ms",
                    measured=p95,
                    objective=objectives["latency_p95_ms"],
                    alert="HighLatencyP95",
                )
            )

    if received and "error_rate_pct" in objectives:
        rate = len(failed) / len(received) * 100
        if rate > objectives["error_rate_pct"]:
            findings.append(
                Finding(
                    "slo_breach",
                    "critical",
                    f"error rate {rate:.1f}% vượt objective {objectives['error_rate_pct']:.1f}%",
                    sli="error_rate_pct",
                    measured=round(rate, 2),
                    objective=objectives["error_rate_pct"],
                    alert="HighErrorRate",
                    breakdown=dict(Counter(r.get("error_type", "unknown") for r in failed)),
                )
            )

    if sent and "daily_cost_usd" in objectives:
        by_day: Counter[str] = Counter()
        for record in sent:
            ts = parse_ts(record)
            if ts and isinstance(record.get("cost_usd"), (int, float)):
                by_day[ts.strftime("%Y-%m-%d")] += record["cost_usd"]
        for day, total in sorted(by_day.items()):
            if total > objectives["daily_cost_usd"]:
                findings.append(
                    Finding(
                        "slo_breach",
                        "warning",
                        f"cost ngày {day} là ${total:.4f}, vượt ngân sách ${objectives['daily_cost_usd']:.2f}",
                        sli="daily_cost_usd",
                        measured=round(total, 6),
                        objective=objectives["daily_cost_usd"],
                        alert="DailyCostBudgetBurn",
                    )
                )

    if sent and "quality_score_avg" in objectives:
        scores = nums(sent, "quality_score")
        if scores:
            avg = sum(scores) / len(scores)
            if avg < objectives["quality_score_avg"]:
                findings.append(
                    Finding(
                        "slo_breach",
                        "warning",
                        f"quality trung bình {avg:.3f} dưới objective {objectives['quality_score_avg']:.2f}",
                        sli="quality_score_avg",
                        measured=round(avg, 4),
                        objective=objectives["quality_score_avg"],
                        alert=None,
                    )
                )
    return findings


def detect_hygiene(records: list[dict]) -> list[Finding]:
    api = [r for r in records if r.get("service") == "api"]
    if not api:
        return []
    no_cid = [r for r in api if not r.get("correlation_id") or r.get("correlation_id") == "MISSING"]
    no_enrich = [r for r in api if not ENRICHMENT_FIELDS.issubset(r.keys())]
    findings: list[Finding] = []
    if no_cid:
        findings.append(
            Finding(
                "log_hygiene",
                "critical",
                f"{len(no_cid)}/{len(api)} bản ghi API thiếu correlation_id — không nối được trace với log",
                affected=len(no_cid),
                total=len(api),
            )
        )
    if no_enrich:
        missing = Counter()
        for record in no_enrich:
            missing.update(ENRICHMENT_FIELDS - record.keys())
        findings.append(
            Finding(
                "log_hygiene",
                "warning",
                f"{len(no_enrich)}/{len(api)} bản ghi API thiếu enrichment ({', '.join(sorted(missing))})",
                affected=len(no_enrich),
                total=len(api),
                missing_fields=dict(missing),
            )
        )
    return findings


def detect_traffic_gap(records: list[dict], minutes: int) -> list[Finding]:
    received = [r for r in records if r.get("event") == "request_received"]
    if received:
        return []
    window = "toàn bộ file" if minutes <= 0 else f"{minutes} phút gần nhất"
    return [
        Finding(
            "traffic_gap",
            "warning",
            f"không có request nào trong {window} — dashboard sẽ rỗng chứ không phải khoẻ mạnh",
        )
    ]


def analyse(log_path: Path, slo_path: Path, minutes: int) -> list[Finding]:
    records = load_records(log_path)
    scoped = scope(records, minutes)
    objectives = load_objectives(slo_path)
    findings = (
        detect_pii(records)  # PII quét toàn file, không theo cửa sổ
        + detect_slo(scoped, objectives)
        + detect_hygiene(scoped)
        + detect_traffic_gap(scoped, minutes)
    )
    return sorted(findings, key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))


# --------------------------------------------------------------------------- #
def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Phát hiện anomaly trong log quan sát được")
    parser.add_argument("--logs", type=Path, default=REPO_ROOT / "data" / "logs.jsonl")
    parser.add_argument("--slo", type=Path, default=REPO_ROOT / "config" / "slo.yaml")
    parser.add_argument(
        "--window-minutes", type=int, default=60, help="0 = quét toàn bộ file (mặc định 60)"
    )
    parser.add_argument("--json", action="store_true", help="In JSON để máy khác đọc")
    args = parser.parse_args()

    findings = analyse(args.logs, args.slo, args.window_minutes)
    critical = [f for f in findings if f["severity"] == "critical"]

    if args.json:
        print(json.dumps({"findings": findings, "critical": len(critical)}, ensure_ascii=False, indent=2))
    else:
        window = "toàn bộ file" if args.window_minutes <= 0 else f"{args.window_minutes} phút gần nhất"
        print(f"--- Anomaly scan: {args.logs.as_posix()} ({window}) ---")
        print(f"Ngưỡng đọc từ {args.slo.as_posix()}\n")
        if not findings:
            print("Không phát hiện anomaly nào.")
        for finding in findings:
            mark = "[CRITICAL]" if finding["severity"] == "critical" else "[ warning]"
            print(f"{mark} {finding['kind']}: {finding['summary']}")
            if finding.get("alert"):
                print(f"            -> khớp alert {finding['alert']} (docs/alerts.md)")
        print(f"\nTổng: {len(findings)} phát hiện, {len(critical)} ở mức critical.")

    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
