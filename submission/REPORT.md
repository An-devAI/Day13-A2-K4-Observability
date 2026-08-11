# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm:
- Repository URL:
- Commit SHA cuối:
- Thành viên và vai trò:

## 2. Kết quả kỹ thuật

- Điểm `validate_logs.py`:
- Tổng số traces: 38 (Langfuse Tracing, ≥10 yêu cầu, gồm các trace từ `load_test.py` và các lần test prompt baseline/candidate/production)
- Số PII leak còn lại:
- Link/đường dẫn dashboard:

## 3. Logging và tracing

- Evidence correlation ID:
- Evidence PII redaction:
- Evidence trace waterfall:
- Giải thích một span đáng chú ý:

## 4. Prompt versioning

- Prompt name: `day13-chat` (biến `feature`, `docs`, `message`)
- Version/label baseline: version 1, labels `baseline` + `production` (ban đầu)
- Version/label candidate: version 2, label `candidate` (điều chỉnh format/độ dài câu trả lời)
- Trace ID của mỗi version:
  - Version 1 (`baseline`): `27e1083f487d9271090e1d607c99ad9e`
  - Version 2 (`candidate`): `b01c20bf2b82f479a8093d954d3cf169`
- Bằng chứng đổi label hoặc rollback:
  - `submission/evidence/version1-baseline.png` — danh sách version ban đầu, version 1 có label `baseline` + `production`.
  - `submission/evidence/version2-candidate.png` — version 2 tạo mới với label `candidate`.
  - `submission/evidence/version2-production.png` — sau khi chuyển label `production` sang version 2; trace mới xác nhận `prompt_version: 2`.
  - `submission/evidence/version1-rollback.png` — sau khi rollback `production` về version 1; version 1 có lại `baseline` + `production`, version 2 chỉ còn `candidate`.

## 5. Dashboard, SLO và alerts

**Kết quả `validate_dashboard.py`:** `HỢP LỆ: 6/6 panel có trong dashboard contract.`
Ngoài ra `python -m pytest -q` → `31 passed`, trong đó 9 test mới ở
[`tests/test_build_dashboard.py`](../tests/test_build_dashboard.py).

**Evidence dashboard:**

| File | Nội dung |
|---|---|
| [`evidence/dashboard_baseline.html`](evidence/dashboard_baseline.html) | 6 panel ở trạng thái bình thường, 50 request |
| [`evidence/dashboard_incident.html`](evidence/dashboard_incident.html) | 6 panel sau khi inject `rag_slow` và `tool_fail` |

Dashboard được sinh bằng [`scripts/build_dashboard.py`](../scripts/build_dashboard.py), đọc
`data/logs.jsonl` làm nguồn và lấy **toàn bộ** tiêu đề, đơn vị, phép tổng hợp và threshold
từ `config/dashboard.yaml` thông qua chính `scripts/validate_dashboard.py`. Contract không
hợp lệ thì script raise và không sinh ra file nào — hành vi này được khoá bằng test
`test_build_renders_every_panel_declared_in_contract` và
`test_build_refuses_to_render_from_an_invalid_contract`. Nhờ vậy ảnh dashboard không thể
lệch khỏi contract. Trang giữ time range 60 phút và tự refresh 30 giây đúng như contract quy định.

**So sánh baseline và incident** (cùng cửa sổ 60 phút, cùng `--concurrency 5`):

| Panel | Baseline | Sau incident | Threshold | Kết quả |
|---|---|---|---|---|
| latency (p95) | 151 ms | 2651 ms | ≤ 3000 ms | đạt — xem điểm mù bên dưới |
| traffic | 50 req | 80 req | ≥ 1 req/phút | đạt |
| errors | 0.0 % | **12.5 %** | ≤ 2 % | **vượt ngưỡng** |
| cost | $0.1049 | $0.1482 | ≤ $2.5 | đạt |
| tokens | 8718 | 12294 | ≤ 50000 | đạt |
| quality | 0.880 | 0.880 | ≥ 0.75 | đạt |

`rag_slow` và `tool_fail` phải chạy tách hai pha: [`app/mock_rag.py`](../app/mock_rag.py) kiểm tra
`tool_fail` trước rồi mới tới `rag_slow`, nên bật đồng thời thì mọi request đều lỗi và panel
latency không có dữ liệu nào để đo.

**SLO đã chọn và lý do:** đầy đủ trong [`config/slo.yaml`](../config/slo.yaml) kèm error budget
và lý do từng SLI. Tóm tắt lựa chọn:

- `latency_p95_ms` 3000 ms / 99.5% — API tương tác trực tiếp, baseline 151 ms nên biên rất rộng.
- `error_rate_pct` 2% / 99.0% — lỗi là hỏng hoàn toàn, nhưng để dư budget cho sự cố ngắn tự hồi phục.
- `daily_cost_usd` 2.5 USD / 100% — ngân sách cứng, không có error budget.
- `quality_score_avg` 0.75 / 95% — target lỏng nhất vì đây là proxy heuristic, dùng theo dõi xu hướng.

**Alert rules và runbook:** 3 alert trong [`config/alert_rules.yaml`](../config/alert_rules.yaml),
runbook tương ứng trong [`docs/alerts.md`](../docs/alerts.md).

| Alert | Severity | Điều kiện | For | Demo bằng |
|---|---|---|---|---|
| `HighLatencyP95` | critical | p95 latency > 3000 ms | 5m | `--scenario rag_slow` |
| `HighErrorRate` | critical | error rate > 2% | 5m | `--scenario tool_fail` |
| `DailyCostBudgetBurn` | warning | cost ngày > $2.0 (80% ngân sách) | 15m | `--scenario cost_spike` |

Cả ba điều kiện viết theo triệu chứng người dùng, không nhắc tên thành phần nội bộ. Ba bước
kiểm tra đầu tiên của mỗi runbook đi theo Metrics → Traces → Logs. Cố ý **không** tạo alert
paging cho `quality_score_avg` vì đây là proxy heuristic dễ báo giả; theo dõi qua panel và
review theo tuần.

**Điểm mù đã phát hiện — SLI latency đang đo sai chỗ.** Khi bật `rag_slow`, log ghi p95 = 2651 ms
(dưới ngưỡng 3000, alert **không** nổ) trong khi client thực đo 13299 ms. Nguyên nhân:
`latency_ms` được đo bên trong `LabAgent.run` nên không tính thời gian request nằm chờ, còn
thời gian end-to-end thì middleware có tính nhưng chỉ đặt vào header `x-response-time-ms` chứ
không ghi vào log. Khoảng cách bị khuếch đại vì `time.sleep(2.5)` là lệnh chờ đồng bộ nằm trong
handler `async def`, chặn event loop và làm request đồng thời xếp hàng nối đuôi.
Đề xuất khắc phục: ghi `duration_ms` của middleware vào log `response_sent` rồi chuyển SLI sang
đo trên trường đó. Thay đổi nằm ở `app/middleware.py` nên cần phối hợp với vai Logging & PII.
Chi tiết và số đo trong phần ghi chú của Alert 1.

## 6. Điều tra challenge

- Challenge ID:
- Triệu chứng từ metrics:
- Trace ID liên quan:
- Log line/correlation ID liên quan:
- Root cause:
- Fix action:
- Preventive measure:

## 7. Đóng góp cá nhân

Với mỗi thành viên, ghi rõ nhiệm vụ và link commit/PR tương ứng.

| Thành viên | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|
| | | | |
