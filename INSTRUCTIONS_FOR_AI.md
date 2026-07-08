# Instructions for AI Assistant: JobRadar

Welcome to **JobRadar**, a full-stack, AI-powered PM job search and semantic matching dashboard. This document acts as the core guide to the system's architecture, matching logic, and operational constraints.

---

## 1. Project Overview & Architecture
JobRadar is designed to scrape, analyze, score, and display Product Manager job listings in Germany based on structured career objectives and preferences. It runs locally as a scraping/data-sync engine and deploys to **Render.com** to serve a dark-mode, glassmorphic dashboard.

### Core File Structure
*   [app.py](file:///C:/Users/LeannYC_Wang/OneDrive%20-%20Moxa%20Inc/桌面/Test%20ABC_round%202/app.py): The entrypoint Flask application. Manages routing, background scraping schedules, configuration, and the GitHub auto-sync mechanism.
*   [ai_analyzer.py](file:///C:/Users/LeannYC_Wang/OneDrive%20-%20Moxa%20Inc/桌面/Test%20ABC_round%202/ai_analyzer.py): Integrates with the Groq SDK using the `llama-3.3-70b-versatile` model. Houses functions for resume scanning, job description translation, and the **Three-Tier Matching Engine**.
*   `scraper/`:
    *   [scraper/linkedin.py](file:///C:/Users/LeannYC_Wang/OneDrive%20-%20Moxa%20Inc/桌面/Test%20ABC_round%202/scraper/linkedin.py): Public guest search scraper for LinkedIn (fetches 3 pages: start=0, 25, 50).
    *   `scraper/indeed.py` & `scraper/glassdoor.py`: Stubbed/fallback scrapers.
*   `data/`:
    *   `data/settings.json`: Stores user search configurations, resume text, keywords, and minimum override thresholds.
    *   `data/jobs.json`: The database of scraped job postings and their corresponding AI analysis records.
    *   `data/history.json`: Log of scraping runs (run timestamp, new jobs found, total jobs count).
*   `templates/` & `static/`: Frontend dashboard assets built with HTML5, Vanilla CSS, and JavaScript.

---

## 2. The Three-Tier Matching & Filtering Engine
Rather than relying on primitive keyword matching, JobRadar implements a **減法與語意推理雙軌篩選機制** (semantic three-tier evaluation system) that matches jobs against the candidate's career blueprint.

### Tier 1: Basic Filters & Hard Constraints
1.  **Search Parameters**: Jobs are filtered by location, experience levels, and employment types at the scraping layer.
2.  **Language Filter**: Post-scrape checks match the job's `language_requirements` (detected by LLM) against the user's `search.languages` setting. If there is a mismatch, the job is forced directly to **Low Match**, bypassing scorechecks.

### Tier 2: Soft Preference & Structured Scorecard
For each job, the LLM analyzes the JD and rates 5 dimensions on a scale of 1 to 5:
1.  **Problem Space Type** (Weight: 25%, multiplier $\times 5$)
2.  **Product Stage** (Weight: 25%, multiplier $\times 5$)
    *   *Gating Rule*: If Product Stage $\le 2$, the job is automatically blocked from being a High Match.
3.  **Decision Power** (Weight: 20%, multiplier $\times 4$)
    *   *Gating Rule*: If Decision Power $\le 2$, the job is automatically blocked from being a High Match.
4.  **Customer Interaction Level** (Weight: 15%, multiplier $\times 3$)
5.  **Problem Definition Clarity** (Weight: 15%, multiplier $\times 3$)

#### Score Calculation Formula
$$\text{Job Fit Score} = (S_{\text{Problem Space}} \times 5) + (S_{\text{Product Stage}} \times 5) + (S_{\text{Decision Power}} \times 4) + (S_{\text{Customer Interaction}} \times 3) + (S_{\text{Problem Clarity}} \times 3)$$
*This calculates a score between 20 and 100.*

### Tier 3: Career Trajectory Fit (CTF) & Override Rules
The LLM evaluates a **Career Trajectory Fit (CTF)** score from 1 to 5 based on how well the job aligns with the candidate's `target_archetype` and `target_trajectory`.
*   **Forced Low Match**: If $CTF \le 2$ (representing drift away from career path), the job is forced to **Low Match**.
*   **High Match (best)**: To be classified as High Match, the job must satisfy:
    1.  Job Fit Score $\ge$ `best_match` threshold (configured in settings, e.g., 40).
    2.  $CTF \ge 4$.
    3.  Every scorecard dimension score must be $\ge$ the corresponding minimum specified in `override_rules` (e.g. `min_product_stage`, `min_decision_power`).
*   **Medium Match (medium)**: Jobs that have a Job Fit Score $\ge$ `medium_match` threshold (e.g., 15) and do not trigger a forced low match, or those that met the score for Best Match but failed the CTF or override minimums (downgraded to Medium).
*   **Low Match (low)**: Jobs with a score below the `medium_match` threshold, or those that failed the CTF/language hard gates. Low matches are hidden from the main dashboard lists but visible in their own toggleable section.

---

## 3. Operational & Environment Constraints
1.  **Lightweight Scraper Constraint**: The scrapers **must not** use Playwright, Puppeteer, or headless browsers. They must remain lightweight, using Python's `requests` + `BeautifulSoup` to avoid memory bottlenecks and compilation errors on Render's free tier.
2.  **Groq SDK Dependency Pin**: Keep `httpx<0.28` pinned in `requirements.txt` to maintain compatibility with the `groq==0.9.0` client initialization. Do not remove this pin.
3.  **Auto-Sync Mechanism**: When a local scrape completes, `app.py` automatically commits and pushes the updated `data/jobs.json`, `data/settings.json`, and `data/history.json` to GitHub using the Git REST API. This triggers Render's auto-redeploy, effectively syncing the cloud database.
4.  **Settings Layout**: Settings are split into two tabs:
    *   **System Settings**: Match Score Thresholds, Preferred Dimension Minimums (Override Rules), and Clean Up Old Jobs (Danger Zone).
    *   **Job Search Settings**: Search filters (platforms, job titles, languages, location, experience levels, etc.).
5.  **Danger Zone**: Provides options to clear jobs older than $X$ days or clear all jobs.
