# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm: A2
- Repository URL: `https://github.com/An-devAI/Day13-A2-K4-Observability`
- Commit SHA cuối: cập nhật sau commit cuối cùng của nhóm.
- Thành viên và vai trò:
  - Nguyễn Trường An - 2A202601616: Logging & Middleware
  - Nguyễn Hải Yến - 2A202601604: Security & Compliance
  - Phạm Thành Đạt - 2A202601672: Metrics & Alerting
  - Nguyễn Huy Toàn - 2A202601716: QA & Incident Analyst

## 2. Kết quả kỹ thuật

- Điểm `validate_logs.py`: 100/100 sau khi backup log cũ và sinh lại `data/logs.jsonl` sạch bằng code mới.
- Tổng số traces: 38 (Langfuse Tracing, ≥10 yêu cầu, gồm các trace từ `load_test.py` và các lần test prompt baseline/candidate/production)
- Số PII leak còn lại: 0 leak theo `python scripts/validate_logs.py`.
- Link/đường dẫn dashboard: `submission/evidence/dashboard_baseline.html`, `submission/evidence/dashboard_incident.html`, `submission/evidence/role4_clean_dashboard.html`, `submission/evidence/role4_challenge_dashboard.html`.

## 3. Logging và tracing

- Evidence correlation ID: `python scripts/validate_logs.py` ghi nhận 13 correlation ID duy nhất trên log sạch. Ví dụ trong challenge: `req-864934b7`, session `k4-challenge-s05`, feature `monitoring`, model `claude-sonnet-4-5`.
- Evidence PII redaction: validator ghi nhận `Potential PII leaks detected: 0`. Log baseline trước đó đã che email thành `[REDACTED_EMAIL]`, số điện thoại Việt Nam thành `[REDACTED_PHONE_VN]`, và dữ liệu thẻ thử nghiệm không xuất hiện nguyên văn trong log.
- Evidence trace waterfall: ảnh trace challenge nằm ở `submission/evidence/trace_challenge_k4_s03.png`, trace ID `d19a84a4aa3b6262f18d96dea00143a4`. Ảnh prompt trace nằm ở `submission/evidence/version1-baseline.png`, `submission/evidence/version2-candidate.png`, `submission/evidence/version2-production.png`.
- Giải thích một span đáng chú ý: với incident `rag_slow`, trace `d19a84a4aa3b6262f18d96dea00143a4` thuộc session `k4-challenge-s03`, query `Summarize the observability workflow for an AI API.`. Log đối chiếu có `correlation_id=req-49ef5c5a`, `latency_ms=2650`, feature `monitoring`, cho thấy độ trễ tăng ở luồng RAG/retrieval; dashboard incident cũng xác nhận panel latency tăng rõ rệt.

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
| [`evidence/role4_clean_dashboard.html`](evidence/role4_clean_dashboard.html) | Dashboard sạch sau khi sinh lại `data/logs.jsonl`, dùng để xác nhận validator 100/100 |
| [`evidence/role4_challenge_dashboard.html`](evidence/role4_challenge_dashboard.html) | Dashboard riêng cho lần Role 4 chạy challenge `rag_slow` |

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
| errors | 0.0% | **12.5%** | ≤ 2% | **vượt ngưỡng** |
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

| Alert                   | Severity | Điều kiện                        | For | Demo bằng                |
| ----------------------- | -------- | ----------------------------------- | --- | ------------------------- |
| `HighLatencyP95`      | critical | p95 latency > 3000 ms               | 5m  | `--scenario rag_slow`   |
| `HighErrorRate`       | critical | error rate > 2%                     | 5m  | `--scenario tool_fail`  |
| `DailyCostBudgetBurn` | warning  | cost ngày > $2.0 (80% ngân sách) | 15m | `--scenario cost_spike` |

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

- Challenge ID: `day13-k4-observability-v1`.
- Triệu chứng từ metrics: Sau khi bật incident `rag_slow`, dashboard Role 4 báo panel latency vượt ngưỡng. Trong `data/logs.jsonl`, feature `monitoring` có 5 request challenge, 4 response ghi nhận latency `[4656, 4658, 4662, 4671] ms`, p95 = 4671ms, vượt ngưỡng challenge 2000ms.
- Trace ID liên quan: `d19a84a4aa3b6262f18d96dea00143a4` trên Langfuse; ảnh evidence: `submission/evidence/trace_challenge_k4_s03.png`.
- Log line/correlation ID liên quan: `req-49ef5c5a`, session `k4-challenge-s03`, feature `monitoring`, `latency_ms=2650`, model `claude-sonnet-4-5`, lưu trong `submission/evidence/logs_mixed_before_clean_20260811-165757.jsonl`.
- Root cause: Incident được release là `rag_slow`, ảnh hưởng feature `monitoring`. Bằng chứng log cho thấy request monitoring trong challenge đạt 2650ms; dashboard `submission/evidence/role4_challenge_dashboard.html` xác nhận latency vượt ngưỡng challenge 2000ms; trace Langfuse `d19a84a4aa3b6262f18d96dea00143a4` dùng để mở waterfall và đối chiếu span chậm với log.
- Fix action: Tắt incident khi demo xong; về kỹ thuật, tối ưu bước RAG/retrieval, thêm timeout/cache hoặc fallback, và tránh dùng thao tác blocking trong handler async.
- Preventive measure: Duy trì dashboard 6 panel, alert theo triệu chứng người dùng, và cập nhật SLI latency sang thời gian end-to-end từ middleware để không bỏ sót thời gian request bị xếp hàng.

## 7. Đóng góp cá nhân

Với mỗi thành viên, ghi rõ nhiệm vụ và link commit/PR tương ứng.

| Thành viên | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|
| Nguyễn Trường An - 2A202601616 | Logging & Middleware: hoàn thiện middleware correlation ID, gắn metadata vào log API và đảm bảo request/response có thể đối chiếu bằng cùng một correlation ID | `ef4ca98`, `708c03c` | Hiểu vai trò của correlation ID trong việc nối request, trace và log khi điều tra sự cố |
| Nguyễn Hải Yến - 2A202601604 | Security & Compliance: hoàn thiện che PII, kiểm tra email/số điện thoại/số thẻ không xuất hiện nguyên văn trong log, tạo evidence prompt versioning trên Langfuse | `5a4f81b` | Biết cần scrub PII trước khi ghi log và dùng prompt label/version để rollback có kiểm soát |
| Phạm Thành Đạt - 2A202601672 | Metrics & Alerting: hoàn thiện metrics snapshot, dashboard 6 panel, SLO, alert rules, runbook và dashboard evidence baseline/incident | `e26316c`, `b4d0482` | Biết thiết kế alert theo triệu chứng người dùng và dùng SLO/error budget để ưu tiên xử lý |
| Nguyễn Huy Toàn - 2A202601716 | QA & Incident Analyst: chạy baseline/load test, kiểm `validate_logs.py` và `validate_dashboard.py`, chạy challenge `rag_slow`, đối chiếu Metrics -> Traces -> Logs, sinh evidence Role 4 và hoàn thiện báo cáo incident | Commit `adf1e91` | Biết cách nối Metrics -> Traces -> Logs để chứng minh root cause thay vì chỉ nhìn một log riêng lẻ |
