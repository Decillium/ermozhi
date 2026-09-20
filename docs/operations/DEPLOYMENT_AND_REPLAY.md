# Ermozhi — Production Operations & Deployment Runbook

## 1. Overview & Cloud Topology
Ermozhi is deployed as an event-driven microservice system on **Azure Container Apps (ACA)** in Central India:
- **`ermozhi-gateway` (Public HTTPS Ingress)**:
  - Validates HMAC webhook signatures (Meta WhatsApp).
  - Persists immutable canonical events directly to `events/` and enqueues to `inbox/` in Azure Blob Storage.
  - Acknowledges with HTTP 200 within $< 500\text{ms}$.
  - Strictly configured with `minReplicas = 0` (cost-optimized) to eliminate cold-start webhook dropouts.
- **`ermozhi-worker` (Private Worker Pool)**:
  - Leases messages from `inbox/` using 60-second exclusive Azure Blob Leases.
  - Streams audio into Gemini 3.5 Flash Lite with zero local disk writes (`readOnlyRootFilesystem: true`).
  - Evaluates pure Decision Engine against precomputed market snapshots.
  - Synthesizes Tamil voice output (`ta-IN-ValluvarNeural`) and streams MP3 directly to `media/outbound/`.
  - Dispatches WhatsApp responses via Meta WhatsApp Cloud API.
- **Scheduled Container Apps Jobs**:
  - `ermozhi-job-market-ingestion`: Hourly mandi data ingestion during market hours (06:00–18:00 IST).
  - `ermozhi-job-reconciliation`: Runs every 15 minutes to recover orphaned inbox blobs.
  - `ermozhi-job-media-cleanup`: Nightly job purging audio blobs older than 30 days.

---

## 2. Zero-Trust Security & RBAC
All containers run with **System-Assigned Managed Identity**; zero credentials exist in environment variables:
1. **Azure Blob Storage**: Managed Identity assigned `Storage Blob Data Contributor`.
2. **Azure Key Vault**: Managed Identity assigned `Key Vault Secrets User`.
3. **Container Security**: `readOnlyRootFilesystem: true` and `allowPrivilegeEscalation: false`.

---

## 3. Deployment Guide

### Step 1: Provision Cloud Infrastructure
```bash
az group create --name rg-ermozhi-prod --location centralindia

az deployment group create \
  --resource-group rg-ermozhi-prod \
  --template-file deploy/azure/environment.bicep \
  --parameters environmentName=prod
```

### Step 2: Build & Push Container Images
```bash
az acr build --registry acrermozhiprod --image ermozhi-gateway:v1.0.0 --file Dockerfile .
az acr build --registry acrermozhiprod --image ermozhi-worker:v1.0.0 --file Dockerfile .
```

### Step 3: Deploy Container Apps and Jobs
```bash
az containerapp create --resource-group rg-ermozhi-prod --yaml deploy/azure/gateway.yaml
az containerapp create --resource-group rg-ermozhi-prod --yaml deploy/azure/worker.yaml

az containerapp job create --resource-group rg-ermozhi-prod --yaml deploy/azure/jobs/market-ingestion-job.yaml
az containerapp job create --resource-group rg-ermozhi-prod --yaml deploy/azure/jobs/reconciliation-job.yaml
az containerapp job create --resource-group rg-ermozhi-prod --yaml deploy/azure/jobs/cleanup-job.yaml
```

---

## 4. Operator Replay & DLQ Management

If an unrecoverable failure or poison payload is sent to `work/dead-letter/{message_id}.json`, operators can inspect and replay it:

### List Dead-Letter Queue
```bash
python -m src.tools.replay --list-dlq
```

### Replay Dead-Letter Message
```bash
python -m src.tools.replay \
  --replay-dlq msg_1234567890 \
  --operator "admin_saravanan" \
  --reason "Upstream Gemini quota reset"
```

### Replay Historical Event from Event Store
```bash
python -m src.tools.replay \
  --replay-event "events/2026/09/20/msg_1234567890.json" \
  --operator "admin_saravanan" \
  --reason "Farmer requested recommendation re-evaluation"
```

---

## 5. Monitoring, Alerting & PII Redaction

### Automated PII Redaction
All log streams and telemetry automatically pass through `PIIMaskingFilter`:
- Phone numbers are masked: `+919876543210` $\rightarrow$ `+91XXXXXX3210`.
- API keys, access tokens, and passwords are redacted.
- Raw audio binary buffers are replaced with byte summaries (`<bytes len=N>`).

### Production Alert Rules
1. **Ingress Webhook Error Rate Alert**:
   - Condition: HTTP 5xx responses on `ermozhi-gateway` $> 2\%$ over 5 minutes.
   - Severity: Sev 1.
2. **Dead-Letter Queue Alert**:
   - Condition: Blobs present in `work/dead-letter/` $> 0$.
   - Severity: Sev 2.
3. **Stale Market Snapshot Alert**:
   - Condition: Latest snapshot `latest_observation_date` $> 72\text{ hours}$ old.
   - Severity: Sev 2.
