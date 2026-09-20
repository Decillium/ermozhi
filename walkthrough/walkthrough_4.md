# Phase 4: Private Worker Orchestrator, Multimodal AI & Language/TTS

## Overview
Phase 4 implements the asynchronous processing worker pipeline (`uzhavan-worker`). The worker leases work items from `inbox/` using exclusive Azure Blob leases, streams media directly from object storage to Gemini 3.5 Flash Lite for multimodal entity extraction, executes the pure Decision Engine against precomputed market snapshots, and synthesizes localized voice responses directly to `media/outbound/` in Blob Storage using short-lived SAS URLs.

---

## Deliverables Completed

### 1. Work Leasing Engine ([`src/worker/lease_manager.py`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/src/worker/lease_manager.py))
- **`WorkLeaseManager`**:
  - **Backlog Ingestion**: Scans `inbox/` for pending, unleased work items.
  - **Exclusive Lease Acquisition**: Leases `inbox/{message_id}.json` with a 60-second lock and registers active state in `work/active/{message_id}.json`.
  - **Heartbeat Renewal**: Renews active leases during long-running processing cycles.
  - **Terminal Lifecycle Management**:
    - Purges both `inbox/` and `work/active/` upon successful completion.
    - Routes unrecoverable poison messages to `work/dead-letter/{message_id}.json` with structured error diagnostics and release of active locks.

### 2. Multimodal Intelligence Adapter & Post-Validation ([`src/intelligence/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/src/intelligence/))
- **`DeterministicValidator` (`validator.py`)**:
  - Normalizes Tamil and English dialect aliases (`விரலி`, `விரலி மஞ்சள்`, `நாட்டு மஞ்சள்`, `virali`, `salem` $\rightarrow$ `Finger`; `கிழங்கு`, `முட்டை`, `kizhangu`, `gatta` $\rightarrow$ `Bulb`).
  - Coerces prices and units.
  - Enforces fail-closed clarification triggers (`ExtractionIntent.CLARIFICATION_NEEDED` with `missing_fields`) when variety or offered price is absent.
- **`GeminiIntelligenceAdapter` (`adapter.py`)**:
  - Direct multimodal single-hop extraction with Gemini 3.5 Flash Lite.
  - Inbound media streaming: downloads voice notes directly into in-memory byte buffers and persists to `media/inbound/{YYYY}/{MM}/{DD}/{message_id}.ogg` in Blob Storage (zero local disk I/O).

### 3. Orchestration Pipeline ([`src/worker/pipeline.py`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/src/worker/pipeline.py))
- **`WorkerPipeline`**:
  1. **Stage 1 (Extraction)**: Calls `GeminiIntelligenceAdapter` for structured entity extraction.
  2. **Stage 2 (Clarification Branch)**: Bypasses the Decision Engine if required parameters are missing, routing directly to the Language Layer for a targeted question.
  3. **Stage 3 (Market Lookup)**: Retrieves precomputed `MarketDataSnapshot` via `MarketSnapshotReader` in $< 50\text{ms}$.
  4. **Stage 4 (Decision Evaluation)**: Evaluates offer using pure `DecisionEngine` (`SELL \ge 0.90`, `NEGOTIATE 0.80 - 0.90`, `HOLD < 0.80`, `WAIT`).
  5. **Stage 5 (Language & Voice)**: Hands off decision DTO to the Language Layer for text rendering and TTS synthesis.

### 4. Resilient Language Layer & TTS ([`src/language/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/src/language/))
- **`LanguageTemplateEngine` (`templates.py`)**:
  - Localizes `SELL`, `NEGOTIATE`, `HOLD`, `WAIT`, and clarification messages in rural-first Tamil (`ta-IN`) and English (`en-IN`).
  - Formulates concise recommendations without financial guarantees, citing mandi source provenance and observed dates.
- **`TTSAdapter` (`tts.py`)**:
  - Synthesizes Tamil male voice notes (`ta-IN-ValluvarNeural`) using in-memory streaming directly to `media/outbound/{YYYY}/{MM}/{DD}/{response_id}.mp3` in Blob Storage.
  - Generates secure Shared Access Signature (SAS) URLs (1-hour TTL).
  - Graceful degradation to `FallbackStatus.TEXT_ONLY` on TTS outage or timeouts.
- **`LanguageEngine` (`engine.py`)**:
  - Coordinates template selection and voice synthesis.

---

## Automated Test Verification

156 tests passing with 100% green status across all suites:
- [`tests/worker/test_lease_manager.py`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/tests/worker/test_lease_manager.py) (5 tests): Lease acquisition, heartbeats, clean completion, and dead-letter routing.
- [`tests/intelligence/test_intelligence_adapter.py`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/tests/intelligence/test_intelligence_adapter.py) (20 tests): Dialect normalization, structured JSON extraction, and zero-disk media streaming.
- [`tests/language/test_language_tts.py`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/tests/language/test_language_tts.py) (8 tests): Fact-binding, targeted questions, and graceful degradation to `TEXT_ONLY`.
- [`tests/worker/test_pipeline.py`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/tests/worker/test_pipeline.py) (3 tests): Full end-to-end processing across text, clarification, and voice flows.
- [`tests/gateway/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/tests/gateway/) (17 tests).
- [`tests/data/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/tests/data/) (42 tests).
- [`tests/contracts/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/tests/contracts/) (15 tests).
- [`tests/decision/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/tests/decision/) & [`tests/test_decision_engine.py`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/tests/test_decision_engine.py) (27 tests).
- [`tests/security/`](file:///e:/Program%20Files/vs%20code/Decillium_farmerProduct/tests/security/) (21 tests).
