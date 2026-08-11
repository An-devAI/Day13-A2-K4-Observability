"""Đo chi phí của một đợt request qua API và ghi lại snapshot để so before/after.

Đo trực tiếp trên `cost_usd` trong response body của /chat nên con số chỉ thuộc
đúng đợt chạy này, không bị lẫn với dữ liệu cũ trong data/logs.jsonl.

Ví dụ:
    python scripts/cost_benchmark.py --label before
    python scripts/cost_benchmark.py --label after --compare
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio

BASE_URL = "http://127.0.0.1:8000"
QUERIES = REPO_ROOT / "data" / "sample_queries.jsonl"
SNAPSHOTS = REPO_ROOT / "submission" / "evidence" / "cost_benchmark.json"


def run(repeat: int) -> dict:
    payloads = [
        json.loads(line)
        for line in QUERIES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    totals = {"requests": 0, "cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0, "failed": 0}
    with httpx.Client(timeout=60.0) as client:
        for _ in range(repeat):
            for payload in payloads:
                response = client.post(f"{BASE_URL}/chat", json=payload)
                if response.status_code != 200:
                    totals["failed"] += 1
                    continue
                body = response.json()
                totals["requests"] += 1
                totals["cost_usd"] += body["cost_usd"]
                totals["tokens_in"] += body["tokens_in"]
                totals["tokens_out"] += body["tokens_out"]
    totals["cost_usd"] = round(totals["cost_usd"], 6)
    if totals["requests"]:
        totals["avg_cost_usd"] = round(totals["cost_usd"] / totals["requests"], 8)
        totals["avg_tokens_out"] = round(totals["tokens_out"] / totals["requests"], 1)
    return totals


def health() -> dict:
    return httpx.get(f"{BASE_URL}/health", timeout=10.0).json()


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Đo chi phí một đợt request để so before/after")
    parser.add_argument("--label", required=True, help="Tên snapshot, ví dụ before hoặc after")
    parser.add_argument("--repeat", type=int, default=3, help="Số vòng lặp qua sample_queries")
    parser.add_argument("--compare", action="store_true", help="So với snapshot 'before' đã lưu")
    parser.add_argument("--out", type=Path, default=SNAPSHOTS)
    args = parser.parse_args()

    state = health()
    totals = run(args.repeat)
    snapshot = {
        "label": args.label,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "incidents": state.get("incidents", {}),
        **totals,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    stored = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    stored[args.label] = snapshot
    args.out.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"--- Cost benchmark: {args.label} ---")
    print(f"incidents      : {snapshot['incidents']}")
    print(f"requests       : {totals['requests']} (lỗi: {totals['failed']})")
    print(f"tokens_out     : {totals['tokens_out']} (tb {totals.get('avg_tokens_out', 0)}/request)")
    print(f"total_cost_usd : ${totals['cost_usd']:.6f}")
    print(f"avg_cost_usd   : ${totals.get('avg_cost_usd', 0):.8f}/request")

    if args.compare and "before" in stored and args.label != "before":
        before = stored["before"]
        saved = before["cost_usd"] - totals["cost_usd"]
        pct = (saved / before["cost_usd"] * 100) if before["cost_usd"] else 0.0
        print("\n--- So sánh với 'before' ---")
        print(f"before : ${before['cost_usd']:.6f}  ({before['tokens_out']} output tokens)")
        print(f"after  : ${totals['cost_usd']:.6f}  ({totals['tokens_out']} output tokens)")
        print(f"tiết kiệm: ${saved:.6f}  =  {pct:.1f}%")

    print(f"\nSnapshot đã ghi vào {args.out.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
