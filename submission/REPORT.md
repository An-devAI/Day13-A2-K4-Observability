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

- Kết quả `validate_dashboard.py`:
- Evidence dashboard:
- SLO đã chọn và lý do:
- Alert rules và runbook:

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
