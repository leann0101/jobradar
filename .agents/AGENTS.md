# Rules and Context for Antigravity AI Assistant

Welcome to **JobRadar**. Read this file to instantly align on the project architecture, matching guidelines, and environmental requirements.

## Core Directives
1. **Scraping Architecture**: Do NOT use Playwright or headless browsers. Keep scrapers lightweight using `requests` + `BeautifulSoup` to prevent memory usage issues and installation errors on Render.
2. **Auto-Sync Mechanism**: The Flask app includes an auto-sync function `sync_data_to_github()` in `app.py`. When a local scrape completes, it automatically pushes `data/jobs.json`, `data/settings.json`, and `data/history.json` to GitHub. This triggers Render's auto-redeploy to keep the cloud site in sync.
3. **Groq SDK Compatibility**: Pinned `httpx<0.28` to maintain compatibility with `groq==0.9.0` client initialization. Do not remove this pin unless updating `groq` SDK version.

## Project Structure
- [app.py](file:///C:/Users/LeannYC_Wang/OneDrive%20-%20Moxa%20Inc/桌面/Test%20ABC_round%202/app.py): Entry point, routing, configuration, background scheduler, and GitHub sync pipeline.
- [ai_analyzer.py](file:///C:/Users/LeannYC_Wang/OneDrive%20-%20Moxa%20Inc/桌面/Test%20ABC_round%202/ai_analyzer.py): Integrates with Groq Llama 3.3 for career objective matching, resume analysis, scorecard rating, and trajectory fit calculations.
- [scraper/linkedin.py](file:///C:/Users/LeannYC_Wang/OneDrive%20-%20Moxa%20Inc/桌面/Test%20ABC_round%202/scraper/linkedin.py): Public search guest scraper with 3-page pagination (start=0, 25, 50).
- [templates/](file:///C:/Users/LeannYC_Wang/OneDrive%20-%20Moxa%20Inc/桌面/Test%20ABC_round%202/templates/) & [static/](file:///C:/Users/LeannYC_Wang/OneDrive%20-%20Moxa%20Inc/桌面/Test%20ABC_round%202/static/): Dark-mode premium Glassmorphic UI Dashboard and settings pages.

## AI Matching & Scoring System (Three-Tier Engine)
JobRadar uses a **减法與語意推理雙軌篩選機制** to classify jobs into **High (best)**, **Medium (medium)**, and **Low (low)** match.

### 1. Scorecard (Tier 2 Score)
Evaluates 5 dimensions (each scored 1-5):
*   **Problem Space Type** (Weight multiplier: 5)
*   **Product Stage** (Weight multiplier: 5) -- *Note: If Product Stage <= 2, the job cannot be a High Match.*
*   **Decision Power** (Weight multiplier: 4) -- *Note: If Decision Power <= 2, the job cannot be a High Match.*
*   **Customer Interaction Level** (Weight multiplier: 3)
*   **Problem Definition Clarity** (Weight multiplier: 3)

#### Formula:
$$\text{Job Fit Score} = (S_{\text{Problem Space}} \times 5) + (S_{\text{Product Stage}} \times 5) + (S_{\text{Decision Power}} \times 4) + (S_{\text{Customer Interaction}} \times 3) + (S_{\text{Problem Clarity}} \times 3)$$

### 2. Gating and Classification Rules (Tier 3 CTF)
*   **Forced Low Match**: If Career Trajectory Fit (CTF) score $\le 2$, the job is forced to **Low Match** (regardless of score).
*   **High Match**: Score must be $\ge$ `best_match` threshold, $CTF \ge 4$, and individual dimension scores must satisfy the configured `override_rules` (e.g., `min_product_stage`, `min_decision_power`). Otherwise, the job is downgraded to **Medium Match**.
*   **Low Match Threshold**: Score is below `medium_match` threshold or fails hard gates.

