# Ermozhi — Repository Hygiene & Final State Walkthrough

## 1. Executive Summary
All legacy prototype files, unversioned CSVs, synchronous scripts, local media artifacts, and ad-hoc test files have been permanently deleted from the repository. The entire codebase is organized into modular packages under `src/` and tested via **automated tests** across 10 domain suites in `tests/`.

---

## 2. Deleted Legacy & Prototype Artifacts

| Category | Deleted Files | Replacement / Superseding Module |
|---|---|---|
| **Monolithic Modules (`src/`)** | `src/main.py`<br>`src/input_process_layer.py`<br>`src/gemini_intelligence_layer.py`<br>`src/market_data_layer.py`<br>`src/decision_engine_layer.py`<br>`src/response_generation_layer.py`<br>`src/twilio_webhook_layer.py`<br>`src/twilio_logger.py`<br>`src/README.md` | Domain packages:<br>- [`src/gateway/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/src/gateway/)<br>- [`src/intelligence/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/src/intelligence/)<br>- [`src/decision_engine/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/src/decision_engine/)<br>- [`src/data/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/src/data/)<br>- [`src/language/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/src/language/)<br>- [`src/worker/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/src/worker/)<br>- [`src/channels/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/src/channels/) |
| **Node.js & Diagnostic Scripts** | `server.js`<br>`package.json`<br>`package-lock.json`<br>`verify_connection.py`<br>`test.py`<br>`test_layer2.py` | Native Python FastAPI Gateway and [`src/channels/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/src/channels/) adapters. |
| **Manual / Ad-hoc Test Scripts** | `tests/curl_test_suite.ps1`<br>`tests/test_signature.py`<br>`tests/test_error_simulation.py`<br>`tests/test_e2e.py`<br>`tests/test_decision_engine.py` | Automated domain test suites under `tests/` (`tests/security/`, `tests/decision/`, etc.). |
| **Prototype Artifacts** | `data/fallBackData.csv` (9 MB unversioned)<br>`output_audio/` (local mp3s) | Azure Blob Storage tiered layout (`market/`, `media/`, `events/`, `work/`) and in-memory byte streams. |

---

## 3. Active Repository Layout

```text
├── deploy/azure/               # Declarative ACA Bicep & YAML manifests
│   ├── environment.bicep       # Log Analytics, ACA Environment, Key Vault, Storage Account
│   ├── gateway.yaml            # ermozhi-gateway (public HTTPS, minReplicas=0, readOnlyRootFilesystem)
│   ├── worker.yaml             # ermozhi-worker (private worker pool, minReplicas=0)
│   └── jobs/                   # Container Apps Jobs (market-ingestion, reconciliation, cleanup)
├── docs/                       # Architectural documentation & operational runbooks
│   └── operations/             # DEPLOYMENT_AND_REPLAY.md
├── src/                        # Domain packages
│   ├── app.py                  # Production FastAPI gateway (/api/v1/ and compatibility aliases)
│   ├── channels/               # Outbound messaging adapters (Meta WhatsApp Cloud API)
│   ├── contracts/v1/           # Versioned canonical schemas (events, intelligence, decision, market, language)
│   ├── data/                   # Storage repo, scheduled ingestion runner, snapshots, reader
│   ├── decision_engine/        # Pure zero-IO decision engine (SELL >= 0.90, NEGOTIATE 0.80-0.90, HOLD, WAIT)
│   ├── gateway/                # Ingress routes, HMAC security validators, sliding-window rate limiters
│   ├── intelligence/           # Gemini 3.5 Flash Lite multimodal extraction, dialect validator
│   ├── language/               # Rural-first Tamil template engine, Edge TTS adapter (SAS URLs)
│   ├── platform/               # Durable EventStore, telemetry PII masking filter, context tracer
│   ├── tools/                  # Event replay & DLQ management CLI (replay.py)
│   └── worker/                 # WorkLeaseManager, 6-stage WorkerPipeline, reconciliation, cleanup jobs
├── tests/                      # Automated test suites (158 tests, 100% green)
│   ├── channels/               # Meta outbound tests, status callback webhooks
│   ├── contracts/              # Contract validation tests
│   ├── data/                   # Ingestion, snapshot publishing, reader, storage layout tests
│   ├── decision/               # Pure Decision Engine policy tests
│   ├── fixtures/               # Test fixtures (mandi observations)
│   ├── gateway/                # Async webhook ingress, HMAC verification, health probes
│   ├── intelligence/           # Dialect normalization, structured JSON extraction
│   ├── language/               # Fact-binding, TTS fallback, Tamil prompts
│   ├── platform/               # Telemetry PII redaction, replay tool, deployment manifest validation
│   ├── security/               # Security sanitization & HMAC validation
│   └── worker/                 # Lease management, pipeline execution, reconciliation loop
├── Dockerfile                  # Production container packaging
├── pytest.ini                  # Configured domain testpaths
├── README.md                   # Project overview & architectural guide
└── requirements.txt            # Locked production dependencies
```

---

## 4. Automated Verification Matrix

```
======================= 172 passed, 1 warning in 10.70s =======================
```

All 172 automated domain tests pass with 100% green status.
