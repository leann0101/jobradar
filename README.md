# JobRadar 🎯 — AI-Powered PM Job Search Assistant

A web-based job search assistant that **automatically scrapes** LinkedIn, Indeed, and Glassdoor for **Product Manager** roles in **Germany**, then uses **Groq AI** to analyze JDs and match them against your keyword preferences.

## Features

- 🔍 **Multi-platform scraping**: LinkedIn, Indeed, Glassdoor
- 🤖 **AI analysis**: Groq LLaMA 3.3 extracts skills, industry, experience level
- 🎯 **Smart matching**: Weighted keyword scoring (Must-Have × 2 + Nice-to-Have × 1)
- 📊 **Visual dashboard**: Best Match / Medium Match cards with score rings
- ⚙️ **Configurable**: Edit keywords and thresholds via the Settings page
- 🕐 **Weekly auto-scrape**: Every Monday 08:00 UTC (+ manual trigger)
- 🚀 **Deploy-ready**: One-click deploy on Render.com

---

## Quick Start (Local)

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium
```

### 2. Set your Groq API key
Copy `.env.example` to `.env` and fill in your key:
```bash
cp .env.example .env
# Edit .env: GROQ_API_KEY=gsk_xxxxx
```

### 3. Run the app
```bash
python app.py
```
Visit: `http://localhost:5000`

### 4. Trigger a scrape
Click **"Run Scraper Now"** on the dashboard. First run takes ~5–10 minutes.

---

## Deploy on Render.com

1. Push this folder to a **GitHub repository**
2. Go to [render.com](https://render.com) → New Web Service → Connect your repo
3. Render auto-detects `render.yaml`
4. Add environment variable: `GROQ_API_KEY = your_key_here`
5. Deploy → your app will be live at `https://jobradar-xxxx.onrender.com`

> **Note**: Free Render instances sleep after 15 min of inactivity. The weekly scheduler will still fire when the service is awake. For reliable scheduling, consider upgrading to a paid plan or using Railway.

---

## Match Scoring Formula

```
score = (matched_must_have × 2 + matched_nice_to_have × 1)
        ─────────────────────────────────────────────────── × 100
        (total_must_have × 2 + total_nice_to_have × 1)

Best Match:   score ≥ 40%
Medium Match: score ≥ 15%
Low Match:    score < 15%
```

---

## Project Structure

```
├── app.py              # Flask app + scheduler + scraping pipeline
├── ai_analyzer.py      # Groq API integration + scoring
├── scraper/
│   ├── linkedin.py     # LinkedIn public search scraper
│   ├── indeed.py       # Indeed Germany scraper
│   └── glassdoor.py    # Glassdoor scraper
├── data/
│   ├── jobs.json       # All scraped + analyzed jobs
│   ├── settings.json   # Your keyword preferences
│   └── history.json    # Scrape run history
├── templates/          # HTML templates (Jinja2)
├── static/             # CSS + JS
├── Procfile            # For Render/Railway
└── render.yaml         # Render deployment config
```

---

## Your Initial Keywords

**Must-Have** (weight ×2):
`Industry 4.0`, `IIoT`, `Manufacturing`, `Factory Automation`, `OT/IT Integration`, `Hardware`, `B2B Industrial`, `Robotics`, `Automation`, `Sensors`, `Edge Computing`, `SCADA`, `MES`, `ERP`, `Embedded Systems`, `Firmware`

**Nice-to-Have** (weight ×1):
`Roadmap Planning`, `Cross-functional Team`
