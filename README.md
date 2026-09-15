---
title: Autonomous Job Matcher & Resume Parser Agent
emoji: 💼
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Autonomous Job Matcher & Resume Parser Agent

An autonomous AI agent designed for resume parsing, job discovery, semantic capability matching, scoring, and automated job application handling.

---

## 🚀 Live Demo & Deployment on Hugging Face Spaces

### 1. Create a New Space
1. Go to [Hugging Face Spaces](https://huggingface.co/spaces) and click **Create new Space**.
2. Set Space SDK to **Docker** (Blank).
3. Push this repository to your Space repository via Git.

### 2. Configure Space Secrets (Environment Variables)
In your Hugging Face Space **Settings $\to$ Variables and secrets**, add the following Secrets:

| Secret Name | Value Description | Required? |
|---|---|---|
| `GROQ_API_KEY` | Your Groq API key from [Groq Console](https://console.groq.com/keys) | **Required** |
| `USE_POSTGRES` | `true` (if using PostgreSQL) or `false` (uses local SQLite) | Optional |
| `DATABASE_URL` | `postgresql://...` (e.g. Neon DB connection pooler string) | Optional |
| `API_KEY` | Secret token to secure API endpoints (leave empty for open demo) | Optional |
| `GEMINI_API_KEY` | Optional Google Gemini key | Optional |
| `HEADLESS_MODE` | `true` (for headless browser automation in Docker) | Default: `true` |

---

## 💻 Local Development Setup

### 1. Clone & Setup Environment
```bash
git clone https://github.com/your-username/job_agent.git
cd job_agent
cp .env.template .env
```
Edit `.env` and fill in your `GROQ_API_KEY`.

### 2. Install Dependencies
```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

### 3. Run Locally
```bash
python run.py
```
Open your browser at: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

### 4. Run Test Suite
```bash
python -m pytest tests/
```

---
*Release v1.0.0 ready for production and Hugging Face Spaces deployment.*
