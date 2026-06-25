# Rules and Context for Antigravity AI Assistant

Welcome to **JobRadar**. Read this file to instantly align on the project architecture, guidelines, and user requirements.

## Core Directives
1. **Scraping Architecture**: Do NOT use Playwright or headless browsers. Keep scrapers lightweight using `requests` + `BeautifulSoup` to prevent memory usage issues and installation errors on Render.
2. **Auto-Sync Mechanism**: The Flask app includes an auto-sync function `sync_data_to_github()` in `app.py`. When a local scrape completes, it automatically pushes `data/jobs.json` and `data/history.json` to GitHub. This triggers Render's auto-redeploy to keep the cloud site in sync.
3. **Groq SDK compatability**: Pinned `httpx<0.28` to maintain compatibility with `groq==0.9.0` client initialization. Do not remove this pin unless updating `groq` SDK version.

## Project Structure
- [app.py](file:///C:/Users/LeannYC_Wang/OneDrive%20-%20Moxa%20Inc/桌面/Test%20ABC_round%202/app.py): Entry point, routes, scheduler, and GitHub sync pipeline.
- [ai_analyzer.py](file:///C:/Users/LeannYC_Wang/OneDrive%20-%20Moxa%20Inc/桌面/Test%20ABC_round%202/ai_analyzer.py): Integrates with Groq Llama 3.3 for job requirements analysis and score calculation.
- [scraper/linkedin.py](file:///C:/Users/LeannYC_Wang/OneDrive%20-%20Moxa%20Inc/桌面/Test%20ABC_round%202/scraper/linkedin.py): LinkedIn public search scraper with 3-page pagination (start=0, 25, 50).
- [templates/](file:///C:/Users/LeannYC_Wang/OneDrive%20-%20Moxa%20Inc/桌面/Test%20ABC_round%202/templates/) & [static/](file:///C:/Users/LeannYC_Wang/OneDrive%20-%20Moxa%20Inc/桌面/Test%20ABC_round%202/static/): Dark-mode premium Glassmorphic UI Dashboard.

## AI Matching Formula & Preferences
- **Must-Have** (weight ×2): `Industry 4.0`, `IIoT`, `Manufacturing`, `Factory Automation`, `OT/IT Integration`, `Hardware`, `B2B Industrial`, `Robotics`, `Automation`, `Sensors`, `Edge Computing`, `SCADA`, `MES`, `ERP`, `Embedded Systems`, `Firmware`
- **Nice-to-Have** (weight ×1): `Roadmap Planning`, `Cross-functional Team`
- **Formula**:
  \[Score = \frac{\text{Matched Must-Haves} \times 2 + \text{Matched Nice-to-Haves} \times 1}{\text{Total Must-Haves} \times 2 + \text{Total Nice-to-Haves} \times 1} \times 100\]
- **Thresholds**:
  - Best Match: Score $\ge 40\%$
  - Medium Match: Score $\ge 15\%$
  - Low Match (Filtered out of dashboard lists): Score $< 15\%$
