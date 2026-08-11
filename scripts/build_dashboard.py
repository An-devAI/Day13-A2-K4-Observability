"""Render dashboard 6 panel từ config/dashboard.yaml + data/logs.jsonl.

Dashboard được sinh thẳng từ contract: tiêu đề, đơn vị, phép tổng hợp và
threshold của mỗi panel đều đọc từ config/dashboard.yaml qua chính validator
(scripts/validate_dashboard.py). Nhờ vậy ảnh dashboard không thể lệch contract —
contract sai thì script dừng ngay, không render.

Ví dụ:
    python scripts/build_dashboard.py
    python scripts/build_dashboard.py --out submission/evidence/dashboard_incident.html
    python scripts/build_dashboard.py --watch
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from scripts.validate_dashboard import DashboardConfigError, load_dashboard_config

# Palette: 3 slot categorical đầu tiên + status, đã chạy qua validator
# (worst all-pairs CVD ΔE 9.2, normal-vision ΔE 24.0 trên nền sáng).
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")
STATUS = {"good": "#0ca30c", "critical": "#d03b3b"}

CHART_W, CHART_H = 320.0, 132.0
PAD_L, PAD_R, PAD_T, PAD_B = 4.0, 4.0, 12.0, 18.0


# --------------------------------------------------------------------------- #
# Đọc dữ liệu
# --------------------------------------------------------------------------- #
def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"Không tìm thấy {path}. Chạy API và scripts/load_test.py trước.")
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not records:
        raise SystemExit(f"{path} không có bản ghi JSON hợp lệ nào.")
    return records


def parse_ts(record: dict[str, Any]) -> datetime | None:
    raw = record.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def within_window(records: list[dict], minutes: int) -> tuple[list[dict], datetime, datetime]:
    """Cắt cửa sổ time_range_minutes, neo vào bản ghi mới nhất.

    Neo theo bản ghi mới nhất thay vì đồng hồ hệ thống để ảnh evidence render
    lại sau vẫn hiển thị đúng đợt chạy đó.
    """
    stamped = [(parse_ts(r), r) for r in records]
    stamped = [(ts, r) for ts, r in stamped if ts is not None]
    if not stamped:
        raise SystemExit("Không bản ghi nào có trường 'ts' hợp lệ.")
    end = max(ts for ts, _ in stamped)
    start = end - timedelta(minutes=minutes)
    return [r for ts, r in stamped if ts >= start], start, end


# --------------------------------------------------------------------------- #
# Phép tổng hợp
# --------------------------------------------------------------------------- #
def percentile(values: list[float], q: float) -> float:
    """Nearest-rank; ổn định với n nhỏ hơn so với nội suy."""
    if not values:
        return 0.0
    rank = math.ceil(q / 100 * len(values))
    return sorted(values)[min(len(values) - 1, max(0, rank - 1))]


def by_minute(records: list[dict], value: Callable[[dict], float]) -> list[tuple[str, float]]:
    buckets: dict[str, float] = defaultdict(float)
    for record in records:
        ts = parse_ts(record)
        if ts is None:
            continue
        buckets[ts.strftime("%H:%M")] += value(record)
    return sorted(buckets.items())


def events(records: list[dict], name: str) -> list[dict]:
    return [r for r in records if r.get("event") == name]


def numbers(records: list[dict], field: str) -> list[float]:
    return [r[field] for r in records if isinstance(r.get(field), (int, float))]


def compute_panels(records: list[dict]) -> dict[str, dict[str, Any]]:
    sent = events(records, "response_sent")
    received = events(records, "request_received")
    failed = events(records, "request_failed")

    latency = numbers(sent, "latency_ms")
    traffic_series = by_minute(received, lambda _: 1.0)
    cost_series = by_minute(sent, lambda r: float(r.get("cost_usd", 0.0)))
    tokens_in, tokens_out = sum(numbers(sent, "tokens_in")), sum(numbers(sent, "tokens_out"))
    quality = numbers(sent, "quality_score")
    error_rate = (len(failed) / len(received) * 100) if received else 0.0
    breakdown = Counter(r.get("error_type", "unknown") for r in failed)

    return {
        "latency": {
            "metric": percentile(latency, 95),
            "headline": f"{percentile(latency, 95):.0f}",
            "bars": [
                ("p50", percentile(latency, 50)),
                ("p95", percentile(latency, 95)),
                ("p99", percentile(latency, 99)),
            ],
            "note": f"n = {len(latency)} response_sent",
        },
        "traffic": {
            # threshold rate_per_minute đọc trên bucket cao nhất của "count() by 1m",
            # không phải trung bình cả cửa sổ — cửa sổ 60 phút chứa một đợt chạy ngắn
            # sẽ cho trung bình gần 0 dù traffic thực tế vẫn có.
            "metric": max((v for _, v in traffic_series), default=0.0),
            "headline": f"{len(received)}",
            "series": traffic_series,
            "note": f"đỉnh {max((v for _, v in traffic_series), default=0):.0f} req/phút · tổng {len(received)} request",
        },
        "errors": {
            "metric": error_rate,
            "headline": f"{error_rate:.1f}",
            "bars": sorted(breakdown.items(), key=lambda kv: -kv[1]),
            "note": f"{len(failed)} lỗi / {len(received)} request"
            + ("" if breakdown else " · chưa có error_type nào"),
        },
        "cost": {
            "metric": sum(v for _, v in cost_series),
            "headline": f"{sum(v for _, v in cost_series):.4f}",
            "series": cost_series,
            "note": f"{len(sent)} response · trung bình ${(sum(v for _, v in cost_series) / len(sent) if sent else 0):.6f}/request",
        },
        "tokens": {
            "metric": max(tokens_in, tokens_out),
            "headline": f"{tokens_in + tokens_out:.0f}",
            "bars": [("tokens_in", tokens_in), ("tokens_out", tokens_out)],
            "note": f"in {tokens_in:.0f} · out {tokens_out:.0f} (threshold áp cho field lớn hơn)",
        },
        "quality": {
            "metric": (sum(quality) / len(quality)) if quality else 0.0,
            "headline": f"{(sum(quality) / len(quality)) if quality else 0:.3f}",
            "bars": [("mean", (sum(quality) / len(quality)) if quality else 0.0)],
            "note": f"n = {len(quality)} · proxy heuristic, không phải đánh giá thật",
        },
    }


def threshold_ok(value: float, operator: str, limit: float) -> bool:
    return value <= limit if operator == "lte" else value >= limit


# --------------------------------------------------------------------------- #
# SVG
# --------------------------------------------------------------------------- #
def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def bar_path(x: float, y: float, w: float, h: float, r: float = 4.0) -> str:
    """Cột bo tròn đầu mút, chân neo vào baseline."""
    r = max(0.0, min(r, w / 2, h))
    return (
        f"M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
        f"L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
        f"L{x + w:.1f},{y + h:.1f} Z"
    )


def _frame(limit_y: float | None) -> str:
    grid = "".join(
        f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{CHART_W - PAD_R}" y2="{y:.1f}" class="grid"/>'
        for y in (PAD_T, PAD_T + (CHART_H - PAD_T - PAD_B) / 2)
    )
    rule = ""
    if limit_y is not None:
        rule = (
            f'<line x1="{PAD_L}" y1="{limit_y:.1f}" x2="{CHART_W - PAD_R}" y2="{limit_y:.1f}" class="limit"/>'
            f'<text x="{CHART_W - PAD_R}" y="{limit_y - 4:.1f}" class="lbl limit-lbl" text-anchor="end">threshold</text>'
        )
    base = f'<line x1="{PAD_L}" y1="{CHART_H - PAD_B:.1f}" x2="{CHART_W - PAD_R}" y2="{CHART_H - PAD_B:.1f}" class="axis"/>'
    return grid + rule + base


def svg_bars(items: list[tuple[str, float]], limit: float | None, unit: str) -> str:
    if not items:
        return '<div class="empty">Chưa có dữ liệu trong cửa sổ này</div>'
    plot_h = CHART_H - PAD_T - PAD_B
    peak = max([v for _, v in items] + ([limit] if limit else []) + [1e-9])
    scale = plot_h / (peak * 1.15)
    limit_y = (CHART_H - PAD_B) - limit * scale if limit is not None else None

    slot = (CHART_W - PAD_L - PAD_R) / len(items)
    gap = 2.0  # 2px surface gap giữa các cột kề nhau
    width = min(56.0, slot - gap)
    marks = []
    for index, (label, value) in enumerate(items):
        x = PAD_L + index * slot + (slot - width) / 2
        h = max(1.0, value * scale)
        y = (CHART_H - PAD_B) - h
        color = SERIES[index % len(SERIES)]
        num = f"{value:,.3f}".rstrip("0").rstrip(".") if value < 10 else f"{value:,.0f}"
        marks.append(
            f'<g class="mark"><title>{esc(label)}: {esc(num)} {esc(unit)}</title>'
            f'<path d="{bar_path(x, y, width, h)}" fill="{color}"/>'
            f'<text x="{x + width / 2:.1f}" y="{y - 4:.1f}" class="val" text-anchor="middle">{esc(num)}</text>'
            f'<text x="{x + width / 2:.1f}" y="{CHART_H - 5:.1f}" class="lbl" text-anchor="middle">{esc(label)}</text>'
            "</g>"
        )
    return (
        f'<svg viewBox="0 0 {CHART_W:.0f} {CHART_H:.0f}" role="img" preserveAspectRatio="xMidYMid meet">'
        + _frame(limit_y)
        + "".join(marks)
        + "</svg>"
    )


def svg_series(points: list[tuple[str, float]], limit: float | None, unit: str) -> str:
    if not points:
        return '<div class="empty">Chưa có dữ liệu trong cửa sổ này</div>'
    if len(points) == 1:
        return svg_bars(points, limit, unit)
    plot_h = CHART_H - PAD_T - PAD_B
    peak = max([v for _, v in points] + ([limit] if limit else []) + [1e-9])
    scale = plot_h / (peak * 1.15)
    limit_y = (CHART_H - PAD_B) - limit * scale if limit is not None else None
    step = (CHART_W - PAD_L - PAD_R) / max(1, len(points) - 1)

    coords = [
        (PAD_L + i * step, (CHART_H - PAD_B) - v * scale) for i, (_, v) in enumerate(points)
    ]
    line = "L".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = (
        f'<path d="M{coords[0][0]:.1f},{CHART_H - PAD_B:.1f} L{line} '
        f'L{coords[-1][0]:.1f},{CHART_H - PAD_B:.1f} Z" fill="{SERIES[0]}" opacity="0.12"/>'
    )
    stroke = f'<path d="M{line}" fill="none" stroke="{SERIES[0]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
    dots = "".join(
        f'<g class="mark"><title>{esc(points[i][0])}: {esc(f"{points[i][1]:,.4f}".rstrip("0").rstrip("."))} {esc(unit)}</title>'
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{SERIES[0]}" stroke="var(--surface)" stroke-width="2"/></g>'
        for i, (x, y) in enumerate(coords)
    )
    ticks = ""
    for i in (0, len(points) - 1):
        anchor = "start" if i == 0 else "end"
        ticks += (
            f'<text x="{coords[i][0]:.1f}" y="{CHART_H - 5:.1f}" class="lbl" '
            f'text-anchor="{anchor}">{esc(points[i][0])}</text>'
        )
    return (
        f'<svg viewBox="0 0 {CHART_W:.0f} {CHART_H:.0f}" role="img" preserveAspectRatio="xMidYMid meet">'
        + _frame(limit_y)
        + area
        + stroke
        + dots
        + ticks
        + "</svg>"
    )


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
OPERATOR_TEXT = {"lte": "≤", "gte": "≥"}

STYLE = """
:root{--surface:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--good:#0ca30c;--bad:#d03b3b}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--surface:#1a1a19;--plane:#0d0d0d;
--ink:#fff;--ink-2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10)}}
*{box-sizing:border-box}
body{margin:0;padding:28px;background:var(--plane);color:var(--ink);
font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5}
header{max-width:1180px;margin:0 auto 20px}
h1{font-size:21px;margin:0 0 6px;letter-spacing:-.01em}
.meta{font-size:13px;color:var(--ink-2)}
.meta b{color:var(--ink);font-variant-numeric:tabular-nums}
.grid-6{max-width:1180px;margin:0 auto;display:grid;gap:14px;
grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}
.panel{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:16px 16px 8px}
.ptop{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.ptitle{font-size:14px;font-weight:600;margin:0}
.pid{font-size:11px;color:var(--muted);font-family:ui-monospace,monospace}
.hero{font-size:30px;font-weight:600;letter-spacing:-.02em;margin:6px 0 0}
.unit{font-size:13px;font-weight:400;color:var(--ink-2);margin-left:5px}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:600;
padding:2px 8px;border-radius:999px;border:1px solid currentColor}
.ok{color:var(--good)}.bad{color:var(--bad)}
.thr{font-size:12px;color:var(--ink-2);margin:8px 0 2px;font-variant-numeric:tabular-nums}
.note{font-size:11.5px;color:var(--muted);margin:2px 0 6px}
svg{width:100%;height:auto;display:block;overflow:visible}
.grid line,line.grid{stroke:var(--grid);stroke-width:1}
line.axis{stroke:var(--axis);stroke-width:1}
line.limit{stroke:var(--bad);stroke-width:1.5;stroke-dasharray:4 3}
.limit-lbl{fill:var(--bad);font-weight:600}
.lbl{font-size:10px;fill:var(--muted)}
.val{font-size:11px;fill:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
.mark{cursor:default}.mark:hover path,.mark:hover circle{opacity:.78}
.empty{font-size:12px;color:var(--muted);padding:34px 0 40px;text-align:center;
border:1px dashed var(--grid);border-radius:8px;margin-bottom:10px}
table{max-width:1180px;margin:22px auto 0;width:100%;border-collapse:collapse;
background:var(--surface);border:1px solid var(--ring);border-radius:12px;overflow:hidden;font-size:12.5px}
caption{text-align:left;font-size:12px;color:var(--ink-2);padding:0 0 7px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--grid)}
th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600}
td.num{font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:none}
footer{max-width:1180px;margin:14px auto 0;font-size:11.5px;color:var(--muted)}
"""


def render(config: dict, panels: dict, start: datetime, end: datetime, source: Path) -> str:
    dash = config["dashboard"]
    refresh = dash["refresh_seconds"]
    cards, rows = [], []

    for spec in dash["panels"]:
        pid = spec["id"]
        data = panels[pid]
        thr = spec["threshold"]
        limit, operator = float(thr["value"]), thr["operator"]
        passed = threshold_ok(data["metric"], operator, limit)
        chip = (
            '<span class="chip ok">✓ ĐẠT</span>'
            if passed
            else '<span class="chip bad">✕ VƯỢT NGƯỠNG</span>'
        )
        # Threshold line chỉ vẽ khi cùng thang với dữ liệu đang hiển thị.
        drawable = limit if limit <= max([data["metric"], 1e-9]) * 6 else None
        chart = (
            svg_series(data["series"], drawable, spec["unit"])
            if "series" in data
            else svg_bars(data["bars"], drawable, spec["unit"])
        )
        cards.append(
            f'<section class="panel"><div class="ptop"><h2 class="ptitle">{esc(spec["title"])}</h2>'
            f'<span class="pid">{esc(pid)}</span></div>'
            f'<p class="hero">{esc(data["headline"])}<span class="unit">{esc(spec["unit"])}</span></p>'
            f'<p class="thr">{chip} &nbsp;{esc(thr["aggregation"])} {OPERATOR_TEXT[operator]} '
            f'{esc(f"{limit:g}")} {esc(spec["unit"])}</p>'
            f'<p class="note">{esc(data["note"])}</p>{chart}</section>'
        )
        measured = f"{data['metric']:,.4f}".rstrip("0").rstrip(".")
        rows.append(
            f"<tr><td>{esc(spec['title'])}</td><td class='pid'>{esc(pid)}</td>"
            f"<td class='num'>{esc(measured)}</td>"
            f"<td>{esc(spec['unit'])}</td>"
            f"<td class='num'>{esc(thr['aggregation'])} {OPERATOR_TEXT[operator]} {esc(f'{limit:g}')}</td>"
            f"<td class='{'ok' if passed else 'bad'}'>{'✓ ĐẠT' if passed else '✕ VƯỢT'}</td></tr>"
        )

    fmt = "%Y-%m-%d %H:%M:%S UTC"
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>{esc(dash['title'])}</title><style>{STYLE}</style></head><body>
<header><h1>{esc(dash['title'])}</h1>
<p class="meta">Time range <b>{dash['time_range_minutes']} phút</b>
({esc(start.strftime(fmt))} → {esc(end.strftime(fmt))}) ·
refresh <b>{refresh}s</b> · nguồn <b>{esc(source.as_posix())}</b> ·
contract <b>config/dashboard.yaml</b> (schema v{dash['schema_version']})</p></header>
<main class="grid-6">{''.join(cards)}</main>
<table><caption>Bảng dữ liệu — relief cho các mark có contrast thấp và là bản đọc được của 6 panel.</caption>
<thead><tr><th>Panel</th><th>ID</th><th>Giá trị đo</th><th>Đơn vị</th><th>Threshold</th><th>Trạng thái</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<footer>Sinh bởi scripts/build_dashboard.py — mọi tiêu đề, đơn vị, phép tổng hợp và threshold đọc trực tiếp
từ config/dashboard.yaml sau khi qua scripts/validate_dashboard.py.</footer>
</body></html>"""


def build(config_path: Path, log_path: Path, out_path: Path) -> dict:
    config = load_dashboard_config(config_path)
    records = load_records(log_path)
    scoped, start, end = within_window(records, config["dashboard"]["time_range_minutes"])
    panels = compute_panels(scoped)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(config, panels, start, end, log_path), encoding="utf-8")
    return {"config": config, "panels": panels, "scoped": len(scoped), "total": len(records)}


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Render dashboard 6 panel từ dashboard contract")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "dashboard.yaml")
    parser.add_argument("--logs", type=Path, default=REPO_ROOT / "data" / "logs.jsonl")
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "submission" / "evidence" / "dashboard.html"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Render lại mỗi refresh_seconds giây để trang tự cập nhật dữ liệu mới.",
    )
    args = parser.parse_args()

    try:
        result = build(args.config, args.logs, args.out)
    except DashboardConfigError as exc:
        print(f"KHÔNG HỢP LỆ: {exc}")
        return 1

    dash = result["config"]["dashboard"]
    failing = [
        spec["id"]
        for spec in dash["panels"]
        if not threshold_ok(
            result["panels"][spec["id"]]["metric"],
            spec["threshold"]["operator"],
            float(spec["threshold"]["value"]),
        )
    ]
    print(f"Đã render 6/6 panel -> {args.out}")
    print(f"  {result['scoped']}/{result['total']} bản ghi nằm trong {dash['time_range_minutes']} phút gần nhất")
    print(f"  Panel vượt ngưỡng: {', '.join(failing) if failing else 'không'}")

    if args.watch:
        print(f"  --watch: render lại mỗi {dash['refresh_seconds']}s (Ctrl+C để dừng)")
        try:
            while True:
                time.sleep(dash["refresh_seconds"])
                build(args.config, args.logs, args.out)
                print(f"  refreshed {datetime.now():%H:%M:%S}")
        except KeyboardInterrupt:
            print("  đã dừng.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
