-- Resumes Table
CREATE TABLE IF NOT EXISTS resumes (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    parsed_json TEXT NOT NULL,
    embedding TEXT, -- Serialized JSON array for embeddings compatibility
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Jobs Table
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    jd_raw TEXT NOT NULL,
    jd_parsed TEXT,
    embedding TEXT,
    jd_hash TEXT,
    parser_version TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Matches Table
CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    resume_id TEXT NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    match_score REAL NOT NULL,
    matched_skills TEXT,
    missing_skills TEXT,
    reasoning TEXT,
    match_version TEXT,
    resume_hash TEXT,
    soft_matches TEXT,
    matched_capabilities TEXT,
    score_breakdown TEXT,
    level1_key TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_resume_job UNIQUE (resume_id, job_id)
);

-- Semantic Cache Table
CREATE TABLE IF NOT EXISTS semantic_cache (
    resume_hash TEXT NOT NULL,
    required_id TEXT NOT NULL,
    matched INTEGER NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT,
    evidence TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (resume_hash, required_id)
);

-- LLM Context Cache Table
CREATE TABLE IF NOT EXISTS llm_cache (
    id TEXT PRIMARY KEY,
    cache_key TEXT UNIQUE NOT NULL,
    llm_adjustment REAL NOT NULL,
    reasoning TEXT,
    llm_model TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- AI Detailed Explanations Table
CREATE TABLE IF NOT EXISTS ai_explanations (
    id TEXT PRIMARY KEY,
    resume_id TEXT NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    explanation TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_resume_job_exp UNIQUE (resume_id, job_id)
);

-- Application Queue Table
CREATE TABLE IF NOT EXISTS application_queue (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    resume_id TEXT NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'QUEUED' CHECK(
        status IN (
            'QUEUED', 'RUNNING', 'PROCESSING', 'FORM_FILLING', 
            'AWAITING_USER_SUBMIT', 'SUBMITTED', 'COMPLETED', 
            'FAILED', 'RETRY', 'RETRYING'
        )
    ),
    attempt_count INTEGER DEFAULT 0,
    attempts INTEGER DEFAULT 0,
    error_message TEXT,
    error_msg TEXT,
    browser_session_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    CONSTRAINT unique_queue UNIQUE (resume_id, job_id)
);

-- Fast Queue Polling Index
CREATE INDEX IF NOT EXISTS idx_app_queue_polling ON application_queue(status, created_at);

-- Application Audit Logs Table
CREATE TABLE IF NOT EXISTS application_audit_logs (
    id TEXT PRIMARY KEY,
    queue_id TEXT NOT NULL REFERENCES application_queue(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    resume_id TEXT NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status TEXT NOT NULL,
    screenshot_path TEXT,
    submission_result TEXT,
    error_details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Fast Audit Trail Index
CREATE INDEX IF NOT EXISTS idx_audit_queue_id ON application_audit_logs(queue_id, created_at);

-- Candidate Answers Database Table for Custom Application Questions
CREATE TABLE IF NOT EXISTS candidate_answers (
    id TEXT PRIMARY KEY,
    question_key TEXT UNIQUE NOT NULL,
    question_pattern TEXT NOT NULL,
    answer_value TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);



