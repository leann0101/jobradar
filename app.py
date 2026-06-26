import os
import json
import uuid
import logging
import threading
import base64
import requests
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # Load .env file (GROQ_API_KEY etc.)

from flask import Flask, render_template, request, jsonify, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler

from scraper.linkedin import scrape_linkedin
from scraper.indeed import scrape_indeed
from scraper.glassdoor import scrape_glassdoor
from ai_analyzer import analyze_job, classify_job

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
JOBS_FILE = DATA_DIR / "jobs.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.json"

# ── Flask App ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
scrape_lock = threading.Lock()
is_scraping = False


# ── Data helpers ──────────────────────────────────────────────────────────────
def load_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_settings() -> dict:
    return load_json(SETTINGS_FILE, {
        "must_have": [],
        "nice_to_have": [],
        "score_thresholds": {"best_match": 40, "medium_match": 15},
        "search": {
            "job_titles": ["product manager"],
            "location": "Germany",
            "days_ago": 15,
            "platforms": ["linkedin", "indeed", "glassdoor"],
        },
    })


def load_jobs() -> list:
    return load_json(JOBS_FILE, [])


def save_jobs(jobs: list):
    save_json(JOBS_FILE, jobs)


def load_history() -> list:
    return load_json(HISTORY_FILE, [])


def save_history(history: list):
    save_json(HISTORY_FILE, history)


def sync_data_to_github():
    token = os.environ.get("GITHUB_TOKEN")
    owner = os.environ.get("GITHUB_OWNER")
    repo = os.environ.get("GITHUB_REPO")
    
    if not (token and owner and repo):
        logger.info("GitHub sync credentials not fully set, skipping sync.")
        return
        
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "JobRadar-Sync"
    }
    
    files_to_sync = ["data/jobs.json", "data/history.json"]
    
    for rel_path in files_to_sync:
        local_path = BASE_DIR / rel_path
        if not local_path.exists():
            continue
            
        github_path = rel_path.replace("\\", "/")
        
        try:
            with open(local_path, "rb") as f:
                content_bytes = f.read()
            encoded = base64.b64encode(content_bytes).decode("utf-8")
            
            sha = None
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{github_path}"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                sha = r.json().get("sha")
                
            payload = {
                "message": f"Sync: update {github_path} from local scrape",
                "content": encoded
            }
            if sha:
                payload["sha"] = sha
                
            r_put = requests.put(url, headers=headers, json=payload, timeout=15)
            if r_put.status_code in [200, 201]:
                logger.info(f"Successfully synced {github_path} to GitHub.")
            else:
                logger.error(f"Failed to sync {github_path} to GitHub: {r_put.status_code} {r_put.text}")
        except Exception as e:
            logger.error(f"Error syncing {github_path} to GitHub: {e}")


# ── Scraping pipeline ─────────────────────────────────────────────────────────
def run_scrape_pipeline():
    global is_scraping
    with scrape_lock:
        if is_scraping:
            logger.info("Scrape already in progress, skipping.")
            return
        is_scraping = True

    try:
        settings = load_settings()
        search_cfg = settings.get("search", {})
        job_titles = search_cfg.get("job_titles", ["product manager"])
        location = search_cfg.get("location", "Germany")
        days_ago = search_cfg.get("days_ago", 15)
        platforms = search_cfg.get("platforms", ["linkedin", "indeed", "glassdoor"])
        must_have = settings.get("must_have", [])
        nice_to_have = settings.get("nice_to_have", [])
        thresholds = settings.get("score_thresholds", {"best_match": 40, "medium_match": 15})

        all_raw_jobs = []
        for title in job_titles:
            if "linkedin" in platforms:
                logger.info(f"Scraping LinkedIn for '{title}'...")
                try:
                    all_raw_jobs.extend(scrape_linkedin(title, location, days_ago))
                except Exception as e:
                    logger.error(f"LinkedIn failed: {e}")

            if "indeed" in platforms:
                logger.info(f"Scraping Indeed for '{title}'...")
                try:
                    all_raw_jobs.extend(scrape_indeed(title, location, days_ago))
                except Exception as e:
                    logger.error(f"Indeed failed: {e}")

            if "glassdoor" in platforms:
                logger.info(f"Scraping Glassdoor for '{title}'...")
                try:
                    all_raw_jobs.extend(scrape_glassdoor(title, location, days_ago))
                except Exception as e:
                    logger.error(f"Glassdoor failed: {e}")

        # De-duplicate by URL
        existing_jobs = load_jobs()
        existing_urls = {j["url"] for j in existing_jobs}
        new_raw = [j for j in all_raw_jobs if j.get("url") and j["url"] not in existing_urls]
        logger.info(f"Found {len(new_raw)} new jobs to analyze.")

        # AI analyze each new job
        analyzed = []
        for job in new_raw:
            try:
                enriched = analyze_job(job, must_have, nice_to_have)
                enriched["id"] = str(uuid.uuid4())
                enriched["match_category"] = classify_job(enriched["match_score"], thresholds)
                enriched["scraped_at"] = datetime.now().isoformat()
                analyzed.append(enriched)
                logger.info(f"  ✓ {job['title']} @ {job['company']} — score: {enriched['match_score']} ({enriched['match_category']})")
            except Exception as e:
                logger.error(f"Analysis failed for {job.get('title')}: {e}")

        # Re-score existing jobs if settings changed (optional: skip for performance)
        all_jobs = existing_jobs + analyzed
        # Re-classify existing with current thresholds
        for j in all_jobs:
            if "match_score" in j:
                j["match_category"] = classify_job(j["match_score"], thresholds)

        save_jobs(all_jobs)

        # Log history
        history = load_history()
        history.insert(0, {
            "run_at": datetime.now().isoformat(),
            "new_jobs_found": len(analyzed),
            "total_jobs": len(all_jobs),
            "platforms": platforms,
        })
        history = history[:50]  # Keep last 50 runs
        save_history(history)

        logger.info(f"Scrape complete. {len(analyzed)} new jobs added.")

        # Sync to GitHub (keeps data persistent across restarts/deploys)
        sync_data_to_github()
    finally:
        with scrape_lock:
            is_scraping = False


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def dashboard():
    jobs = load_jobs()
    settings = load_settings()
    history = load_history()

    # Sort by match_score desc
    jobs_sorted = sorted(jobs, key=lambda x: x.get("match_score", 0), reverse=True)
    best = [j for j in jobs_sorted if j.get("match_category") == "best"]
    medium = [j for j in jobs_sorted if j.get("match_category") == "medium"]

    last_run = history[0]["run_at"] if history else None
    return render_template(
        "dashboard.html",
        best_jobs=best,
        medium_jobs=medium,
        total=len(jobs),
        best_count=len(best),
        medium_count=len(medium),
        last_run=last_run,
        is_scraping=is_scraping,
    )


@app.route("/job/<job_id>")
def job_detail(job_id):
    jobs = load_jobs()
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if not job:
        return "Job not found", 404
    settings = load_settings()
    return render_template("job_detail.html", job=job, settings=settings)


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    settings = load_settings()
    if request.method == "POST":
        data = request.get_json() or {}
        settings["must_have"] = [k.strip() for k in data.get("must_have", []) if k.strip()]
        settings["nice_to_have"] = [k.strip() for k in data.get("nice_to_have", []) if k.strip()]
        settings["score_thresholds"]["best_match"] = int(data.get("best_match", 40))
        settings["score_thresholds"]["medium_match"] = int(data.get("medium_match", 15))
        settings["search"]["days_ago"] = int(data.get("days_ago", 15))
        settings["search"]["location"] = data.get("location", "Germany").strip()
        settings["search"]["job_titles"] = [t.strip() for t in data.get("job_titles", []) if t.strip()]
        if not settings["search"]["job_titles"]:
            settings["search"]["job_titles"] = ["product manager"]
        settings["search"]["platforms"] = data.get("platforms", ["linkedin", "indeed", "glassdoor"])
        save_json(SETTINGS_FILE, settings)
        return jsonify({"status": "ok"})
    return render_template("settings.html", settings=settings)


@app.route("/history")
def history_page():
    history = load_history()
    return render_template("history.html", history=history)


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """Trigger a scrape run manually."""
    global is_scraping
    if is_scraping:
        return jsonify({"status": "already_running"}), 409
    thread = threading.Thread(target=run_scrape_pipeline, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/scrape/status")
def api_scrape_status():
    return jsonify({"is_scraping": is_scraping})


@app.route("/api/jobs/delete/<job_id>", methods=["DELETE"])
def api_delete_job(job_id):
    jobs = load_jobs()
    jobs = [j for j in jobs if j.get("id") != job_id]
    save_jobs(jobs)
    return jsonify({"status": "deleted"})


@app.route("/api/jobs/clear", methods=["DELETE"])
def api_clear_jobs():
    save_jobs([])
    return jsonify({"status": "cleared"})


# ── Scheduler ─────────────────────────────────────────────────────────────────
def start_scheduler():
    scheduler = BackgroundScheduler()
    # Run every Monday at 08:00 UTC
    scheduler.add_job(
        run_scrape_pipeline,
        trigger="cron",
        day_of_week="mon",
        hour=8,
        minute=0,
        id="weekly_scrape",
    )
    scheduler.start()
    logger.info("Scheduler started: weekly scrape every Monday 08:00 UTC")
    return scheduler


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    scheduler = start_scheduler()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
