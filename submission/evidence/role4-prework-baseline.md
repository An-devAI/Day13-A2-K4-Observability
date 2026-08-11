# Role 4 prework baseline

Owner role: QA & Incident Analyst
Date: 2026-08-11

## What was prepared

- Generated baseline runtime logs by starting the API locally and running:

```powershell
python scripts/load_test.py --concurrency 5
```

- Confirmed `data/logs.jsonl` exists after the load test.
- Ran public tests with workspace-local temp directory:

```powershell
$env:TEMP=(Resolve-Path .pytest_tmp).Path
$env:TMP=$env:TEMP
python -m pytest -q
```

Earlier pre-pull result:

```text
22 passed, 2 warnings
```

After pulling teammates' dashboard work, the full test suite result is:

```text
31 passed, 2 warnings
```

## Dashboard validator baseline

Command:

```powershell
python scripts/validate_dashboard.py
```

Result:

```text
HOP LE: 6/6 panel co trong dashboard contract.
```

Dashboard contract requires these 6 panels:

- Latency percentiles: p50, p95, p99, unit `ms`, p95 <= 3000.
- Request traffic: count/rate per minute, unit `requests_per_minute`, rate >= 1.
- Error rate and breakdown: unit `percent`, error rate <= 2.
- Cost over time: unit `usd`, total <= 2.5.
- Input and output tokens: unit `tokens`, total per field <= 50000.
- Quality proxy: unit `score_0_to_1`, mean >= 0.75.

## Log validator baseline

Command:

```powershell
python scripts/validate_logs.py
```

Earlier pre-pull result before Team A/B finish logging enrichment:

```text
Total log records analyzed: 16
Records with missing required fields: 14
Records with missing enrichment (context): 14
Unique correlation IDs found: 0
Potential PII leaks detected: 0
Estimated Score: 30/100
```

After running the official K4 challenge with `rag_slow` on a mixed log file, the validator result was:

```text
Total log records analyzed: 27
Records with missing required fields: 14
Records with missing enrichment (context): 14
Unique correlation IDs found: 6
Potential PII leaks detected: 0
Estimated Score: 50/100
```

Optimal cleanup performed afterward:

- Backed up the mixed log file into `submission/evidence/logs_mixed_before_clean_*.jsonl`.
- Removed `data/logs.jsonl`.
- Disabled all incidents.
- Ran a clean baseline load test with the latest teammate code:

```powershell
python scripts/load_test.py --concurrency 5
python scripts/validate_logs.py
python scripts/validate_dashboard.py
```

Clean validator result:

```text
Total log records analyzed: 23
Records with missing required fields: 0
Records with missing enrichment (context): 0
Unique correlation IDs found: 13
Potential PII leaks detected: 0
Estimated Score: 100/100
```

Clean dashboard evidence:

```text
submission/evidence/role4_clean_dashboard.html
```

Interpretation:

- PII redaction baseline is already working for sampled email input.
- Correlation ID propagation is not ready yet.
- Required metadata enrichment is not ready yet.
- This is expected prework status and must be rerun after Team A/B complete CP1.

## Challenge details prepared

Challenge file: `config/challenge.json`

```text
challenge_id: day13-k4-observability-v1
incident: rag_slow
affected_feature: monitoring
latency_threshold_ms: 2000
```

Final CP3 command sequence after Team A/B/C are ready:

```powershell
python scripts/inject_incident.py
python scripts/load_test.py --challenge --concurrency 5
python scripts/validate_logs.py
python scripts/validate_dashboard.py
```

Evidence completed later:

- Challenge trace screenshot: `submission/evidence/trace_challenge_k4_s03.png`.
- Challenge trace ID: `d19a84a4aa3b6262f18d96dea00143a4`.
- Challenge log correlation ID used for trace/log matching: `req-49ef5c5a`.
- Challenge dashboard evidence: `submission/evidence/role4_challenge_dashboard.html`.
- Clean validator dashboard evidence: `submission/evidence/role4_clean_dashboard.html`.
- Role 4 commit: `adf1e91`.
