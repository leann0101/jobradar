# Instructions for AI Assistant

Welcome to **JobRadar**. This document describes the project architecture, tech stack, and user requirements to help you get up to speed immediately.

## Project Overview
JobRadar is a full-stack AI-powered job search assistant. It scrapes LinkedIn for Product Manager jobs, analyzes the descriptions (JDs) using Groq API (Llama 3.3), scores them based on the user's weighted keywords, and displays them on a dark-mode dashboard.

## Tech Stack
- **Backend**: Flask (Python 3.10+), APScheduler (background scheduling).
- **AI**: Groq API (`llama-3.3-70b-versatile`) via the `groq` SDK.
- **Scraper**: Lightweight requests + BeautifulSoup4 (no browser dependencies/Playwright needed to support lightweight local runs and avoid Cloudflare blocks on Render).
- **Frontend**: HTML5, Vanilla CSS (Dark Mode), Javascript (Tag inputs, polling).

## Project Architecture
- `app.py`: Main Flask server, routes, scraper orchestration, and GitHub auto-sync.
- `ai_analyzer.py`: Integrates with Groq API, prompts the Llama model, and calculates weighted match scores.
- `scraper/`:
  - `linkedin.py`: Public LinkedIn Guest search scraper (implements 3-page pagination: start=0, 25, 50).
  - `indeed.py` & `glassdoor.py`: Fallback scrapers.
- `data/`:
  - `settings.json`: Stores search criteria and keywords.
  - `jobs.json`: The database of scraped and analyzed jobs.
  - `history.json`: Log of scraping runs.
- `templates/` & `static/`: Frontend dashboard UI.

## User's Specific Requirements & Settings
- **Search Criteria**:
  - Location: Configurable via UI Settings (Default: Germany).
  - Job Titles: Configurable via UI Settings (Default: "product manager").
- **AI Scoring System**:
  - **Must-Have Keywords** (Weight = 2): `Industry 4.0`, `IIoT`, `Manufacturing`, `Factory Automation`, `OT/IT Integration`, `Hardware`, `B2B Industrial`, `Robotics`, `Automation`, `Sensors`, `Edge Computing`, `SCADA`, `MES`, `ERP`, `Embedded Systems`, `Firmware`.
  - **Nice-to-Have Keywords** (Weight = 1): `Roadmap Planning`, `Cross-functional Team`.
  - **Match Score Formula**:
    $$Score = \frac{\text{Matched Must-Haves} \times 2 + \text{Matched Nice-to-Haves} \times 1}{\text{Total Must-Haves} \times 2 + \text{Total Nice-to-Haves} \times 1} \times 100$$
  - **Match Classifications**:
    - Best Match: Score $\ge 40\%$
    - Medium Match: Score $\ge 15\%$
    - Low Match (Hidden from dashboard lists, visible in history): Score $< 15\%$

## GitHub Auto-Sync & Deployment
- **Deployment**: Hosted as a Web Service on **Render.com**.
- **Auto-Sync**: When running locally, after each scrape pipeline completion, the local server automatically commits and pushes the updated `data/jobs.json` and `data/history.json` files back to GitHub using the REST API. This triggers a redeploy on Render, keeping the cloud dashboard synchronized with the local scraper's results!
