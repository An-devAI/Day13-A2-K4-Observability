"""Audit log tách riêng — ai đã đổi gì, lúc nào.

Vì sao không dùng chung data/logs.jsonl: log ứng dụng phục vụ gỡ lỗi, bị xoay
vòng và lọc theo mức, còn audit log phải giữ lại nguyên vẹn và chỉ chứa các sự
kiện thay đổi trạng thái hệ thống. Trộn hai loại vào một file thì một lần dọn
log để lấy baseline sạch sẽ xoá luôn dấu vết thay đổi cấu hình.

Ghi vào AUDIT_LOG_PATH (mặc định data/audit.jsonl), một JSON object mỗi dòng,
chỉ append. Mọi giá trị chuỗi trong `details` đều đi qua bộ scrub PII trước khi
ghi, để audit log không trở thành đường rò dữ liệu mới.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .pii import scrub_text

AUDIT_PATH = Path(os.getenv("AUDIT_LOG_PATH", "data/audit.jsonl"))

# Chỉ những hành động làm thay đổi trạng thái hệ thống mới được vào audit log.
INCIDENT_ENABLE = "incident.enable"
INCIDENT_DISABLE = "incident.disable"
APP_START = "app.start"
CONFIG_CHANGE = "config.change"


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def record(
    action: str,
    *,
    actor: str = "system",
    outcome: str = "success",
    correlation_id: str | None = None,
    details: dict[str, Any] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Ghi một mục audit và trả lại chính mục đó (tiện cho test và cho caller)."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event": "audit",
        "action": action,
        "actor": actor,
        "outcome": outcome,
        "service": os.getenv("APP_NAME", "day13-observability-lab"),
        "env": os.getenv("APP_ENV", "dev"),
    }
    if correlation_id:
        entry["correlation_id"] = correlation_id
    if details:
        entry["details"] = _scrub(details)

    target = path or Path(os.getenv("AUDIT_LOG_PATH", str(AUDIT_PATH)))
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_all(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or Path(os.getenv("AUDIT_LOG_PATH", str(AUDIT_PATH)))
    if not target.exists():
        return []
    entries = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries
