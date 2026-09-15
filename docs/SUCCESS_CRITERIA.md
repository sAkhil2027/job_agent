# Job Matcher & Resume Parser System Success Criteria

This document outlines the success criteria and validation expectations for each major component of the system.

---

## 1. Resume Parser

### Goal
Extract structured JSON representation from raw PDF resume uploads.

### Acceptance Criteria
- **Formatting**: Output must conform strictly to the target JSON schema.
- **Accuracy**: 
  - Extract $\ge$ 95% of listed skills correctly.
  - Correctly extract years of experience and education degree level.
  - Parse contact details (emails, phone numbers, GitHub/LinkedIn URLs) with 100% accuracy using local regex overrides.
- **Robustness**: Never crash on malformed, image-only, or encrypted PDFs. Instead, return a clean error payload.
- **Speed**: Complete local extraction and structured Groq extraction in under 10 seconds.

### Status
- [x] Pass

---

## 2. Job Discovery & Parser

### Goal
Scrape remote IT job feeds, extract job details, and normalize job requirements.

### Acceptance Criteria
- **Feed Extraction**: Fetch and parse jobs successfully from Jobicy and WeWorkRemotely RSS feeds.
- **Skill Normalization**: Extract and map job description skills to the central skill registry (including context validation rules like distinguishing the language "R" from surrounding punctuation).
- **Graceful Parsing**: Fallback to programmatic/regex-based keyword matching when LLM parser calls fail or rate limits are reached.

### Status
- [x] Pass

---

## 3. Capability Matching Engine

### Goal
Perform semantic, graph-based, and rule-based skill alignment between candidate skills and job description requirements.

### Acceptance Criteria
- **Exact & Alias Matching**: Match identical skills and case-insensitive/alias variants (e.g., JS $\to$ JavaScript, Postgres $\to$ PostgreSQL).
- **Transferable Skill Mapping**: Correctly map related candidate skills to JD requirements (e.g., candidate has GCP, matches AWS required with a high transferability score).
- **Capability Graph Navigation**: Graph search matches advanced concepts via BFS paths (e.g., candidate has LangChain, matches required LLM Engineering via graph path).
- **Local Semantic Matching**: Use local `sentence-transformers` embeddings to match semantic evidence within a similarity threshold ($\ge$ 0.75).
- **LLM Reasoning Fallback**: Run LLM batched reasoning on unresolved skills, enforcing strict verification that LLM-matched evidence literally exists in the resume raw text.

### Status
- [x] Pass

---

## 4. Scoring Pipeline & Confidence Router

### Goal
Synthesize matching signals into a final score and confidence percentage, routing to LLM for review only when necessary.

### Acceptance Criteria
- **Deterministic Base Score**: Combine weighted scores (required skills, preferred skills, experience, responsibilities, title, education, domain) where weights sum to exactly 1.0.
- **Confidence Signal**: Calculate confidence based on matching signals.
- **Confidence Routing**: Skip expensive LLM review when confidence is high ($\ge$ 0.90) or score is extremely high/low, and route for review only when ambiguities exist.
- **Caching**: 
  - Level 1 Cache: Retrieve matches from matches table in under 50ms on cache hit.
  - Level 2 Cache: Store/load LLM adjustments in under 50ms on cache hit.

### Status
- [x] Pass

---

## 5. Application Queue & Decision Engine

### Goal
Atomically evaluate final scores to queue eligible applications.

### Acceptance Criteria
- **Decision mapping**: Correctly assign decisions (`AUTO_APPLY` for score $\ge$ 85 and confidence $\ge$ 0.90, `REVIEW` for score $\ge$ 75, `REJECT` otherwise).
- **Auto-Enqueue**: Automatically insert `AUTO_APPLY` jobs into the database queue.
- **Database Integrity**: Ensure no duplicate applications can be enqueued for the same resume and job combination (`unique_queue` constraint).

### Status
- [x] Pass

---

## 6. Application Worker

### Goal
Background worker framework processing applications from the queue.

### Acceptance Criteria
- **Daemon Threading**: Run continuously in the background without blocking the main web server thread.
- **Atomic State Transitions**: Transition queue status from `QUEUED`/`RETRY` to `PROCESSING` atomically.
- **Error & Retry Handling**: Increment attempts on failure, trigger retries for transient errors, and transition to `FAILED` only after 3 failed attempts.

### Status
- [x] Pass

---

## 7. API & Observability

### Goal
Provide routing endpoints and stream system metrics.

### Acceptance Criteria
- **Routing**: Support GET `/api/health`, GET `/api/metrics`, GET `/api/agent/stream`, and POST `/api/parse-resume`, POST `/api/match-jobs`, and POST `/api/detailed-explanation`.
- **SSE Stream**: Broadcast real-time agent updates to all listening UI clients.
- **Metrics Tracker**: Calculate cache hit rates, average local/LLM latencies, and total matches.

### Status
- [x] Pass

---

## Detailed Component Criteria Checklist

## Matcher
**Acceptance**
- Exact skill matching
- Synonym/taxonomy matching
- Transferable skills detected
- No duplicate skills
- Score ∈ [0,100]
**Status:** [x]

---

## Confidence Router
**Acceptance**
- High confidence → Skip LLM
- Low confidence → Use LLM
- Confidence ∈ [0,1]
**Status:** [x]

---

## LLM
**Acceptance**
- Score adjustment ≤ ±5
- Valid JSON output
- Prompt cache works
- No hallucinated skills
**Status:** [x]

---

## Cache
**Acceptance**
- First run → Cache miss
- Second run → Cache hit
- Prompt change → Invalidate LLM cache only
- Resume change → Invalidate local cache
**Status:** [x]

---

## Queue
**Acceptance**
- Queue AUTO_APPLY only
- REVIEW not queued
- REJECT ignored
- No duplicate entries
**Status:** [x]

---

## Worker
**Acceptance**
- Process one job at a time
- Correct status updates
- Retry failed jobs
- Never lose queued jobs
**Status:** [x]

---

## Tracker
**Acceptance**
- One record per application
- Correct status updates
- Submission timestamp immutable
**Status:** [x]



## 8. Hugging Face Spaces & Container Deployment
- [x] Pass
- Validated non-root user 1000 execution
- Validated pre-cached SentenceTransformer embeddings
- Validated port 7860 ASGI binding
