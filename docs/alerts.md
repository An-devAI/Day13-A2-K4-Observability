# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

Định nghĩa máy đọc được nằm ở [`config/alert_rules.yaml`](../config/alert_rules.yaml); ngưỡng và error budget nằm ở [`config/slo.yaml`](../config/slo.yaml). Ba bước kiểm tra đầu tiên của cả ba runbook đều đi theo cùng một luồng **Metrics → Traces → Logs**: metrics cho biết *có chuyện gì*, traces cho biết *ở đâu*, logs chứng minh *tại sao*.

Lệnh dùng chung để lấy log của một request sau khi có `correlation_id` từ trace:

```powershell
Select-String -Path data/logs.jsonl -Pattern "req-xxxxxxxx"
```

---

## Alert 1

- **Tên:** HighLatencyP95
- **Severity:** critical
- **SLI/SLO liên quan:** `latency_p95_ms` — objective 3000 ms, target 99.5% trong 28 ngày (error budget 0.5%). Baseline đo được là 151 ms.
- **Điều kiện và thời gian duy trì:** `p95(latency_ms)` trên event `response_sent` vượt 3000 ms và **duy trì 5 phút**. Chọn 5 phút để một đợt load test ngắn hoặc cold start không gây báo giả.
- **Ảnh hưởng tới người dùng:** Người dùng chờ hơn 3 giây mới có câu trả lời. Phần lớn sẽ bỏ ngang hoặc bấm gửi lại, làm tải tăng thêm và kéo p95 lên tiếp.

- **Ba bước kiểm tra đầu tiên:**
  1. **Metrics** — mở panel `latency` và so p50 với p95. Nếu **p50 cũng tăng** thì mọi request đều chậm, nghi ngờ một bước nằm trên đường đi chung. Nếu **chỉ p95/p99 tăng** còn p50 bình thường thì là tail latency, nghi ngờ tranh chấp tài nguyên hoặc một nhóm input cụ thể. Đối chiếu panel `traffic` để loại trừ khả năng chỉ là tăng tải.
  2. **Traces** — trên Langfuse lọc trace của cửa sổ đang cảnh báo, sắp xếp theo latency giảm dần, mở waterfall của trace chậm nhất và xác định span nào chiếm phần lớn thời gian. Ghi lại trace ID.
  3. **Logs** — lấy `correlation_id` từ trace rồi tra trong `data/logs.jsonl` để lấy `feature`, `session_id`, `model` và `prompt_version`. So nhóm request chậm với nhóm bình thường: nếu tất cả cùng một `feature` thì phạm vi ảnh hưởng hẹp lại đúng feature đó.

- **Mitigation tạm thời:**
  1. Kiểm tra `GET /health` xem có incident nào đang bật không; nếu có, tắt bằng `python scripts/inject_incident.py --scenario <tên> --disable`.
  2. Nếu độ chậm bắt đầu ngay sau một lần đổi prompt, rollback label `production` về version trước theo [PROMPT_VERSIONING.md](PROMPT_VERSIONING.md) rồi đo lại p95.
  3. Nếu chỉ một `feature` bị ảnh hưởng, tạm thời hạ tải feature đó thay vì tắt toàn bộ API.
- **Owner:** Dashboard, SLO & Alert

> **Điểm mù đã biết của SLI này — đọc trước khi tin vào con số p95.**
> `latency_ms` trong log được đo bên trong `LabAgent.run` ([app/agent.py](../app/agent.py)),
> tức là **chỉ tính từ lúc request được xử lý**, không tính thời gian nằm chờ. Thời gian
> end-to-end có được middleware tính ([app/middleware.py](../app/middleware.py)) nhưng chỉ
> ghi vào header `x-response-time-ms`, **không ghi vào log** — nên dashboard và alert này
> không nhìn thấy nó.
>
> Đo thực tế ngày 2026-08-11 khi bật `rag_slow` với `--concurrency 5`:
>
> | | Log ghi (`latency_ms`) | Client đo (end-to-end) |
> |---|---|---|
> | p95 | 2651 ms → **dưới ngưỡng 3000, alert KHÔNG nổ** | 13299 ms → gấp 4,4 lần ngưỡng |
>
> Nguyên nhân khoảng cách: `time.sleep(2.5)` là lệnh chờ đồng bộ nằm trong handler
> `async def`, nên nó chặn event loop và làm các request đồng thời xếp hàng nối đuôi.
> Phần xếp hàng đó rơi hoàn toàn ra ngoài phạm vi đo của `latency_ms`.
>
> **Hệ quả:** ở trạng thái hiện tại, một sự cố khiến người dùng chờ 13 giây vẫn để
> `HighLatencyP95` im lặng. **Việc cần làm:** ghi `duration_ms` của middleware vào log
> `response_sent` rồi chuyển SLI `latency_p95_ms` sang đo trên trường đó. Thay đổi này
> nằm trong `app/middleware.py`, thuộc phạm vi vai Logging & PII — cần phối hợp.

---

## Alert 2

- **Tên:** HighErrorRate
- **Severity:** critical
- **SLI/SLO liên quan:** `error_rate_pct` — objective 2%, target 99.0% trong 28 ngày (error budget 1.0%). Baseline đo được là 0.0%.
- **Điều kiện và thời gian duy trì:** `count(request_failed) / count(request_received) * 100` vượt 2% và **duy trì 5 phút**.
- **Ảnh hưởng tới người dùng:** Request trả về HTTP 500, người dùng không nhận được câu trả lời nào. Đây là hỏng hoàn toàn chứ không phải suy giảm — khi nổ cùng lúc với Alert 1 thì xử lý alert này trước.

- **Ba bước kiểm tra đầu tiên:**
  1. **Metrics** — mở panel `errors`, đọc breakdown `count_by(error_type)`. Một loại lỗi chiếm gần hết nghĩa là một điểm hỏng duy nhất; lỗi rải đều nhiều loại nghĩa là vấn đề nằm ở tầng thấp hơn (mạng, tài nguyên). Đối chiếu panel `traffic` xem lỗi có đi kèm tăng tải đột ngột không.
  2. **Traces** — lọc trace bị lỗi trên Langfuse, mở một trace và xác định span nào ném exception, xem span đó dừng ở bước nào trong chuỗi retrieve → prompt → generate.
  3. **Logs** — lọc `data/logs.jsonl` lấy các bản ghi `event == "request_failed"`, đọc `error_type` và `payload.detail`. Dùng `correlation_id` để ghép ngược lên trace tương ứng làm bằng chứng.

- **Mitigation tạm thời:**
  1. Kiểm tra `GET /health` và tắt incident đang bật nếu có.
  2. Nếu lỗi tập trung ở bước truy hồi tài liệu, cho phép trả lời bằng fallback không có tài liệu thay vì ném 500 — người dùng nhận câu trả lời chất lượng thấp hơn còn hơn không có gì. Chấp nhận `quality_score` giảm trong thời gian này.
  3. Nếu lỗi tiếp tục sau khi đã tắt incident, thông báo trạng thái degraded và giữ nguyên hiện trường để điều tra thay vì restart liên tục.
- **Owner:** Incident, Report & Demo

---

## Alert 3

- **Tên:** DailyCostBudgetBurn
- **Severity:** warning
- **SLI/SLO liên quan:** `daily_cost_usd` — objective 2.5 USD/ngày, target 100% (không có error budget). Baseline là 0.0166 USD cho 10 request.
- **Điều kiện và thời gian duy trì:** `sum(cost_usd)` của ngày hiện tại vượt **2.0 USD** (80% ngân sách) và duy trì 15 phút. Cảnh báo ở 80% chứ không phải 100% để còn thời gian xử lý trước khi chạm trần cứng; 15 phút vì chi phí là chỉ số tích luỹ, không cần phản ứng theo giây.
- **Ảnh hưởng tới người dùng:** Không ảnh hưởng trực tiếp. Đây là alert bảo vệ ngân sách — mức severity là `warning` chứ không phải `critical`, không đánh thức người trực ban đêm.

- **Ba bước kiểm tra đầu tiên:**
  1. **Metrics** — mở panel `cost` xem `sum(cost_usd) by 1m` để xác định chi phí tăng đều hay nhảy bậc, rồi đối chiếu panel `tokens`. Nếu **traffic không tăng mà cost tăng** thì chi phí mỗi request đã tăng; nếu **cả hai cùng tăng** thì đơn thuần là nhiều request hơn.
  2. **Traces** — sắp xếp trace theo `cost_details.total` giảm dần trên Langfuse, mở trace đắt nhất và đọc `usage_details` để xem token phình ở đầu vào (prompt/context dài) hay đầu ra (câu trả lời dài).
  3. **Logs** — cộng `tokens_in` và `tokens_out` theo `feature` và theo `prompt_version` trong `data/logs.jsonl`. Nếu chi phí tập trung vào một `prompt_version` mới, đó là nghi phạm chính.

- **Mitigation tạm thời:**
  1. Nếu chi phí tăng ngay sau khi đổi prompt, rollback label `production` về version trước và xác nhận `tokens_in` trung bình trở lại mức baseline.
  2. Nếu do một feature tiêu thụ bất thường, giới hạn tạm thời số tài liệu đưa vào context của feature đó.
  3. Ghi lại mốc chi phí trước/sau khi xử lý để đưa vào phần cost optimization của báo cáo.
- **Owner:** Dashboard, SLO & Alert
