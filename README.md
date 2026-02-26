# Internship Mining

A data engineering learning project that scrapes, parses, and enriches AI/ML & Data Science internship listings into a structured dataset ready for analysis.

---

## What It Does

The pipeline pulls from the [SpeedyApply 2026 AI College Jobs](https://github.com/speedyapply/2026-AI-College-Jobs) repository, which maintains a curated and daily-updated list of AI/ML/Data Science internship postings for US college students. The raw data lives as markdown tables, so the pipeline does the heavy lifting to turn it into something useful.

### Pipeline Steps

```
GitHub (raw markdown)
        │
        ▼
1. Download raw_internships.md
        │
        ▼
2. Parse 3 markdown tables → DataFrames
   ├── FAANG+  (66 rows,   7 companies)
   ├── Quant   (10 rows,   5 companies)
   └── Other   (388 rows, 232 companies)
        │
        ▼
3. Scrape job descriptions from each posting URL
   (routed by job board: Greenhouse, Workday, Lever, Ashby, SmartRecruiters, generic)
        │
        ▼
4. Cache enriched DataFrame → other_df_with_descriptions.parquet
```

### Job Board Coverage

The scraper detects the job board from the URL and uses the most reliable extraction method for each:

| Job Board | Method |
|---|---|
| Greenhouse | HTML scrape (`div.job__description`) |
| Ashby | Public posting API |
| Workday | Internal CXS API, fallback to JSON-LD |
| Lever | HTML scrape (`data-qa="job-description"`) |
| SmartRecruiters | Public postings API |
| Generic | JSON-LD schema markup, then common CSS selectors |

### Current Results

- **388** "Other" company internship postings parsed
- **290/388** (74.7%) job descriptions successfully extracted
- Enriched dataset cached as Parquet for fast reloads

### Output Schema

| Column | Description |
|---|---|
| `Company` | Company name |
| `Position` | Job title |
| `Location` | Location string |
| `Posting` | Direct URL to job posting |
| `Age` | Days since posting |
| `Company Link` | Company careers page URL |
| `raw_description` | Raw HTML of the job description |
| `description_text` | Clean plain text of the job description |

---

## Project Structure

```
internship-mining/
├── process_data.ipynb          # Exploratory notebook (prototyping & EDA)
├── process_data.py             # Refactored pipeline script
├── raw_internships.md          # Cached raw markdown from SpeedyApply
├── other_df_with_descriptions.parquet  # Enriched dataset cache
└── .gitignore
```

### Running the Pipeline

```bash
# Uses cached Parquet if it exists
python process_data.py

# Force re-scrape all job descriptions
python process_data.py --refresh
```

---

## Data Engineering Extensions (Ideas)

This pipeline is a solid foundation. Here are areas of data engineering you can layer on to make it a full learning project:

### 1. Orchestration
Replace the manual `python process_data.py` invocation with a workflow scheduler.
- **Apache Airflow** or **Prefect**: Define a DAG that runs the full pipeline on a schedule (e.g., daily), with retries on failed scrapes and alerting on low extraction rates.
- This teaches dependency management, task scheduling, and observability of pipelines.

### 2. Data Storage & Warehousing
Move beyond Parquet files on disk.
- Load the enriched data into a local **DuckDB** database or a cloud data warehouse like **BigQuery** or **Snowflake** (free tiers available).
- Model the data properly: a `postings` fact table, a `companies` dimension table, a `scrape_runs` audit table.
- This teaches schema design, incremental loading, and idempotent writes.

### 3. Incremental / CDC Pipeline
Right now the pipeline is a full refresh. Make it incremental.
- Track which postings you have already scraped (by URL hash or job ID) in a metadata table.
- On each run, only scrape new postings — skip ones already in the cache.
- This teaches change data capture (CDC) patterns and upsert logic.

### 4. Data Quality & Validation
Add a validation layer between scraping and storage.
- Use **Great Expectations** or **Pandera** to define contracts: e.g., `Company` must not be null, `Salary` must match a `$\d+/hr` pattern, extraction rate must be above 60%.
- Fail the pipeline or emit warnings when checks don't pass.
- This teaches data contracts, schema enforcement, and quality monitoring.

### 5. Streaming Ingestion
Instead of a daily batch, simulate a streaming pipeline.
- Publish each scraped posting as a message to a **Kafka** topic (or a local **Redpanda** instance).
- Have a consumer write records to the database.
- This teaches producer/consumer patterns, offset management, and the difference between batch and stream processing.

### 6. Containerization & Reproducibility
Package the whole thing so it runs anywhere.
- Write a `Dockerfile` that installs dependencies and runs the pipeline.
- Use **Docker Compose** to spin up the scraper alongside a Postgres or DuckDB-serving container.
- This teaches environment isolation, dependency pinning, and portability.

### 7. Cloud Deployment
Move the pipeline off your laptop.
- Run it on a cron schedule using **GitHub Actions** (free) — store the Parquet artifact back to the repo or upload to S3.
- Or deploy to **AWS Lambda** / **Cloud Run** for event-driven triggering.
- This teaches CI/CD for data pipelines and cloud compute basics.

### 8. Monitoring & Alerting
Add observability to the pipeline runs.
- Log structured JSON (run timestamp, rows scraped, extraction rate, failed URLs) to a file or a `runs` table.
- Build a simple dashboard in **Grafana** or a Jupyter report that shows extraction rate trends over time.
- This teaches pipeline health monitoring and operational awareness.

---

## Analysis Ideas (Once Data Is Refined)

With clean, structured job descriptions across hundreds of AI/ML internship postings, you can extract meaningful signals:

### Skills & Technology Trends
- **Keyword frequency analysis**: What tools appear most often in requirements? (Python, SQL, PyTorch, Spark, dbt, Airflow, etc.)
- **Skills by company tier**: Do FAANG+ roles emphasize different skills than "Other" companies? Do quant firms have a distinct tech stack?
- **Emerging vs. declining keywords**: Track how often terms like "LLM", "RAG", "MLOps", or "Spark" appear over time as you re-run the pipeline.

### Salary Intelligence
- **Salary distribution by tier**: FAANG+ averages $50–67/hr, Quant hits $125/hr — how does the "Other" category distribute?
- **Salary vs. location**: Do postings in SF/NYC pay more than remote or Midwest roles?
- **Salary vs. required degree**: Do PhD-specific roles command a premium even within the same company?

### Geographic Patterns
- **Hotspot mapping**: Which cities/metros have the highest concentration of AI internship postings?
- **Remote vs. onsite ratio**: How common is hybrid/remote across different company tiers?

### Job Board & Hiring Funnel
- **Scrape success rate by job board**: Which platforms are easiest/hardest to extract from? (useful for improving coverage)
- **Posting freshness**: How quickly do postings age out? Are older postings more likely to be filled/closed?

### NLP & Text Mining
- **TF-IDF on job descriptions**: Surface the most distinctive terms per company or per role type.
- **Topic modeling (LDA)**: Cluster roles into latent themes — e.g., "ML Research", "Data Engineering", "Analytics", "MLOps".
- **Requirement extraction**: Use an LLM or regex to pull structured requirements (years of experience, specific degrees, must-have vs. nice-to-have skills) from free text.
- **Similarity search**: Given a resume or skill list, find the most relevant postings using embeddings and cosine similarity.

---

## Dependencies

```
pandas
requests
beautifulsoup4
numpy
tqdm
pyarrow   # for Parquet I/O
```
