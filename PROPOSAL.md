# Architecture Proposal

> Fill this out and commit it by **Friday, July 24 · 11:59 PM IST**. This file *is*
> your Ideation-Phase submission — no separate form. Keep it living; update it as
> your design evolves.

- **Team name:** _AI Fortune_
- **Team code:** _Team-382_
- **Track:** _<!-- AI for Good Health & Well-being / Zero Hunger & Economic Growth / Sustainable Cities & Climate Action / Strong Institutions --> AI for Zero Hunger & Economic Growth deletethis_
- **Members:** _<!-- Name (GitHub @handle), Name (@handle), … --> Kirubasagar V (GitHub [@sagarv2522](https://github.com/sagarv2522)), Arjun PV (GitHub [@arjunpv1312](https://github.com/arjunpv1312)), Gokula krishnan (GitHub [@gokulakrishna-cyber](https://github.com/gokulakrishna-cyber)) , Kishore M (GitHub [@kishorethedev-lab](https://github.com/kishorethedev-lab))_

## 1. Problem

Erode is India's leading turmeric cultivation and trading hub, with nearly **14,500 hectares** under turmeric cultivation, accounting for about **24% of Tamil Nadu's turmeric cultivation area and over 33% of the state's turmeric production**. The district is also home to one of India's largest turmeric markets, making it a critical contributor to the domestic and export supply chain. For this MVP, we focus on the two most commonly traded turmeric varieties in the region—**Finger (Virali) and Bulb (Kizhangu)**—which are frequently sold through direct farm-gate transactions. At the same time, over **80% of agricultural holdings belong to small and marginal farmers (below 2 hectares)**, who often lack the bargaining power and timely access to verified market prices. This information asymmetry allows price negotiations to be driven by traders rather than transparent market data, reducing farmers' ability to secure a fair market value for their produce.


> ### **Community Impact**
>
> Every harvest season, thousands of smallholder turmeric farmers across Erode face the same dilemma. A trader arrives at the farm and offers a price for Finger (Virali) or Bulb (Kizhangu) turmeric, but the farmer has only a few minutes to decide without knowing the latest verified market rate. With limited access to real-time market information and lower digital literacy, many rely on the trader's quotation rather than objective market evidence. Even a price difference of ₹800–₹1,200 per quintal across a harvest of 10–30 quintals can significantly reduce seasonal income and weaken farmers' negotiating power.
>
> *Remark: This summary is synthesized from field reports on smallholder turmeric farmers in Erode; it is a direct quote from few individual farmers.*

## 2. Who it helps

Primary Users:

Smallholder turmeric farmers in Erode. ( need to add numbers or metrics)

Tamil-speaking farmers with limited digital literacy. ( numbers )

Farmers selling directly to local traders. ( quantity range number )

## 3. Proposed solution

Ermozhi is a WhatsApp-based, multilingual AI assistant that empowers smallholder turmeric farmers to make informed selling decisions through natural voice conversations. Instead of searching multiple websites or relying solely on traders, farmers can simply ask a question in Tamil or English, and receive an evidence-based recommendation backed by verified government market data.

The MVP focuses exclusively on Erode district, Turmeric, and its two most actively traded varieties—Finger (Virali) and Bulb (Kizhangu)—allowing the solution to be developed, validated, and demonstrated within the hackathon timeline while solving a real-world problem.

### 3.1 Workflow

#### <u>Step 1 — Ask in Your Own Words</u>

The farmer sends a WhatsApp voice or text message in Tamil or English describing the trader's offer.

>**Example:**
>_"A trader is offering ₹15,800 per quintal for Virali turmeric. Should I sell or negotiate?"_

No mobile application, registration, or technical knowledge is required.

#### <u>Step 2 — AI Understands the Request</u>

Gemini 2.5 Flash understands the conversation, identifies the turmeric variety, extracts the offered price, quantity (if mentioned), and determines the farmer's intent. If essential information is missing, the AI asks a follow-up question before proceeding.

#### <u>Step 3 — Verify with Market Intelligence</u>

The extracted information is passed to our Market Price Decision Engine, which compares the trader's quotation against the latest verified government market prices for Erode. Using a configurable price deviation threshold, the engine classifies the offer into one of three categories. Each recommendation includes the latest verified market price, the percentage difference, and a concise explanation, enabling farmers to negotiate using transparent market evidence rather than assumptions.

| Category         | Rule                                                       |
| ---------------- | ---------------------------------------------------------- |
| **Fair Price** | Trader's offer is **≥ 78%** of the verified market price.  |
| **Negotiate** | Trader's offer is **70–78%** of the verified market price. |
| **Too Low**    | Trader's offer is **< 70%** of the verified market price.  |



### 3.2 AI Responsibilities

- Understand multilingual conversations by processing voice or text messages in Tamil (default), with optional support for English.
- Identify the turmeric variety (Finger/Virali or Bulb/Kizhangu) from natural conversations with confidence scoring.
- Extract key trading information, including the offered price, quantity (if provided), and farmer's intent.
- Retrieve and compare the trader's offer against verified daily government market prices for the corresponding turmeric variety.
- Generate an explainable recommendation (Fair Price, Negotiate, or Too Low) with the latest market price and supporting evidence.
- Deliver the recommendation through a simple Tamil voice response accompanied by an optional WhatsApp text summary.

### 3.3 Why This MVP Can Be Built in 24 Hours

By focusing on one district, one crop, two turmeric varieties, one communication channel, and one verified government dataset, the project significantly reduces implementation complexity and integration effort, enabling the team to build, validate, and demonstrate a complete AI-powered decision support system within the 24-hour hackathon while providing a scalable foundation for future expansion.

### 3.4 Primary Users

- Small and marginal turmeric farmers in Erode holding less than 2.02 hectares (5 acres), representing over 80% of agricultural holdings, who rely on farm-gate sales for their livelihood.
- Tamil-speaking rural farming communities who benefit from Tamil-first voice interactions, making verified market information accessible without requiring users to navigate text-heavy market portals.
- Farmers selling Finger (Virali) and Bulb (Kizhangu) turmeric directly to local traders, typically marketing their harvest in 10–30 quintal batches during each harvesting season, where even small price differences significantly affect seasonal income.

### 3.5 Pilot After Hackathon

We plan to validate Ermozhi through a pilot in Erode district with local Farmer Producer Organizations (FPOs) and smallholder turmeric farmers. The pilot will evaluate the solution under real trading scenarios using verified government market prices.

**Pilot Success Criteria**
- Verify AI recommendation accuracy against daily government market prices.
- Deliver recommendations within **60 seconds**.
- Validate usability of the Tamil voice interface with farmers.
- Collect qualitative feedback on negotiation confidence and ease of use.
- Identify improvements before scaling to additional crops and districts.

### 3.6 Future Expansion

Ermozhi is designed using a modular, dataset-driven architecture that enables seamless expansion beyond the MVP. After validating the solution in Erode, the same AI workflow can be extended to additional crops, districts, and regional languages by integrating verified government market datasets and crop-specific metadata, without redesigning the core decision engine. This approach provides a scalable foundation for building a multilingual AI-powered agricultural decision support platform that empowers smallholder farmers across India with trusted market intelligence.

## 4. Expected Impact

- Increase farmers' seasonal income by 5.8–8.7% per hectare by enabling negotiations based on verified daily market prices. Even an improvement of ₹200–₹300 per quintal can generate an additional ₹6,650–₹9,975 per hectare for the average turmeric farmer in Erode.
- Reduce information barriers through native Tamil voice interaction, allowing farmers to obtain verified market prices and AI-powered recommendations without navigating government websites or interpreting market reports. This makes market intelligence accessible to farmers regardless of their literacy or digital experience.
- Enable price verification in under one minute using WhatsApp, a communication platform already familiar to millions of Indians. Farmers can verify a trader's offer through a simple voice message without installing a new mobile application, reducing the time and effort required to make informed selling decisions.

| Success Measure | Target (MVP) |
|-----------------|--------------|
| Additional farmer income | **+₹200–₹300 per quintal** (~**5.8–8.7%** increase in seasonal income per hectare) |
| Price verification time | **< 60 seconds** |
| User interaction | **100% Tamil voice-enabled** with optional text responses |
| Platform adoption | **0 additional mobile applications** (WhatsApp only) |
| Recommendation quality | Evidence-backed recommendations using **verified government market price datasets** |
| MVP Coverage | **1 district (Erode), 1 crop (Turmeric), 2 varieties (Finger/Virali & Bulb/Kizhangu)** |

## 5. High-Level Architecture
![Ermozhi High-Level Architecture](docs/images/architecture.png)

## 6. Tech Stack

Language: Python

Backend: FastAPI

AI Model: Gemini 2.5 / 3.5 Flash Lite

Messaging: Meta WhatsApp Cloud API

Data Processing: Pandas / PyArrow Parquet

Dataset: Verified e-NAM / data.gov.in Market Ingestion & Snapshot Store

Voice Response: Azure Speech Services / Edge TTS (Tamil)

Deployment: Azure Container Apps (ACA)

Database / Storage: Azure Blob Storage (Immutable Event Log & Inbox Leases)

## 7. Milestones to Hackathon Day

- [x] Problem validation and solution ideation
- [x] Finalize system architecture and technical design
- [x] Prepare verified government market price dataset for Erode turmeric markets

### Day 1 – Core Development
- [x] Set up WhatsApp Business (Meta Cloud API) and FastAPI backend
- [x] Integrate Gemini API for multilingual voice understanding
- [x] Build the Market Price Decision Engine using government market price data
- [x] Implement AI recommendation generation with explainable outputs

### Day 2 – Integration & Demo
- [x] Generate Tamil voice responses using Azure Speech Services
- [x] Deploy the application on Azure Container Apps
- [x] Perform end-to-end testing and latency optimization
- [x] Validate recommendation accuracy with sample market scenarios
- [x] Prepare the final demo, presentation, and judge Q&A

## 8. Open questions / help needed
None at the moment. We would appreciate mentor feedback on our architecture, AI workflow, and scalability.
