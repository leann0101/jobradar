import os
import json
import uuid
import logging
import threading
import base64
import requests
import time
from datetime import datetime, timedelta
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
    defaults = {
        "must_have": [],
        "nice_to_have": [],
        "score_thresholds": {"best_match": 80, "medium_match": 60},
        "career_objective": {
            "target_archetype": "Strategic Product Builder / Early-stage Discovery PM",
            "target_trajectory": "I want to become a strategy-driven, discovery-oriented product builder who defines problems in emerging tech."
        },
        "override_rules": {
            "min_problem_space": 1,
            "min_product_stage": 3,
            "min_decision_power": 3,
            "min_customer_interaction": 1,
            "min_problem_definition_clarity": 1
        },
        "search": {
            "job_titles": ["product manager"],
            "location": "Germany",
            "days_ago": 15,
            "platforms": ["linkedin", "indeed", "glassdoor"],
            "experience_levels": [],
            "location_types": [],
            "employment_types": [],
            "languages": [],
        },
        "resume_text": "",
    }
    data = load_json(SETTINGS_FILE, {})
    for k, v in defaults.items():
        if k not in data:
            data[k] = v
        elif isinstance(v, dict) and isinstance(data[k], dict):
            for sub_k, sub_v in v.items():
                if sub_k not in data[k]:
                    data[k][sub_k] = sub_v
    return data


def load_jobs() -> list:
    jobs = load_json(JOBS_FILE, [])
    modified = False
    for j in jobs:
        if "company_profile" not in j or not isinstance(j["company_profile"], dict):
            j["company_profile"] = {
                "description": "Company description unavailable",
                "business_domain": j.get("industry", "Technology"),
                "employee_count": "Unknown"
            }
            modified = True
        if "resume_match" not in j or not isinstance(j["resume_match"], dict):
            j["resume_match"] = {
                "score": 0,
                "strengths": [],
                "gaps": [],
                "explanation": "No resume analysis available"
            }
            modified = True
            
        # Migrate old jobs to the new scorecard and CTF schema
        if "scorecard" not in j or not j["scorecard"] or "career_trajectory_fit" not in j or not j["career_trajectory_fit"]:
            j["scorecard"] = {
                "problem_space_type": {"score": 3, "label": "Optimization of mature product", "evidence": "Pre-migration record"},
                "product_stage": {"score": 3, "label": "Scaling (1->10)", "evidence": "Pre-migration record"},
                "decision_power": {"score": 3, "label": "Contributes to decisions", "evidence": "Pre-migration record"},
                "customer_interaction": {"score": 3, "label": "Occasional exposure", "evidence": "Pre-migration record"},
                "problem_definition_clarity": {"score": 3, "label": "Medium ambiguity", "evidence": "Pre-migration record"}
            }
            j["career_trajectory_fit"] = {
                "score": 3,
                "label": "Neutral",
                "evidence": "Pre-migration record"
            }
            j["why_match"] = "Pre-migration record. Run scraper to re-analyze this job."
            j["why_not_match"] = "Pre-migration record. Run scraper to re-analyze this job."
            modified = True
            
    if modified:
        save_json(JOBS_FILE, jobs)
    return jobs


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
    
    files_to_sync = ["data/jobs.json", "data/history.json", "data/settings.json"]
    
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
        resume_text = settings.get("resume_text", "")

        existing_jobs = load_jobs()
        existing_urls = {j["url"] for j in existing_jobs}

        all_raw_jobs = []
        for title in job_titles:
            if "linkedin" in platforms:
                logger.info(f"Scraping LinkedIn for '{title}'...")
                try:
                    all_raw_jobs.extend(scrape_linkedin(title, location, days_ago, filter_cfg=search_cfg, existing_urls=existing_urls))
                except Exception as e:
                    logger.error(f"LinkedIn failed: {e}")

            if "indeed" in platforms:
                logger.info(f"Scraping Indeed for '{title}'...")
                try:
                    all_raw_jobs.extend(scrape_indeed(title, location, days_ago, existing_urls=existing_urls))
                except Exception as e:
                    logger.error(f"Indeed failed: {e}")

            if "glassdoor" in platforms:
                logger.info(f"Scraping Glassdoor for '{title}'...")
                try:
                    all_raw_jobs.extend(scrape_glassdoor(title, location, days_ago, existing_urls=existing_urls))
                except Exception as e:
                    logger.error(f"Glassdoor failed: {e}")

        # De-duplicate by URL
        new_raw = [j for j in all_raw_jobs if j.get("url") and j["url"] not in existing_urls]
        logger.info(f"Found {len(new_raw)} new jobs to analyze.")

        # AI analyze each new job
        analyzed = []
        for job in new_raw:
            try:
                enriched = analyze_job(
                    job,
                    must_have,
                    nice_to_have,
                    resume_text,
                    settings.get("career_objective")
                )
                enriched["id"] = str(uuid.uuid4())
                enriched["scraped_at"] = datetime.now().isoformat()
                analyzed.append(enriched)
                logger.info(f"  ✓ {job['title']} @ {job['company']} — score: {enriched.get('match_score', 0)}")
            except Exception as e:
                logger.error(f"Analysis failed for {job.get('title')}: {e}")

        all_jobs = existing_jobs + analyzed
        
        # Re-classify all jobs with current thresholds and language filter
        user_languages = [lang.lower() for lang in search_cfg.get("languages", []) if lang]
        for j in all_jobs:
            if "match_score" in j:
                lang_ok = True
                if user_languages:
                    job_languages = [lang.lower() for lang in j.get("language_requirements", [])]
                    if job_languages and not any(lang in user_languages for lang in job_languages):
                        lang_ok = False
                
                if lang_ok:
                    j["match_category"] = classify_job(j, settings)
                else:
                    j["match_category"] = "low"

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
    low = [j for j in jobs_sorted if j.get("match_category") == "low"]

    last_run = history[0]["run_at"] if history else None
    return render_template(
        "dashboard.html",
        best_jobs=best,
        medium_jobs=medium,
        low_jobs=low,
        total=len(jobs),
        best_count=len(best),
        medium_count=len(medium),
        low_count=len(low),
        last_run=last_run,
        is_scraping=is_scraping,
        settings=settings,
    )


@app.route("/job/<job_id>")
def job_detail(job_id):
    jobs = load_jobs()
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if not job:
        return redirect(url_for("dashboard"))
    settings = load_settings()
    return render_template("job_detail.html", job=job, settings=settings)


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    settings = load_settings()
    if request.method == "POST":
        data = request.get_json() or {}
        settings["must_have"] = [k.strip() for k in data.get("must_have", []) if k.strip()]
        settings["nice_to_have"] = [k.strip() for k in data.get("nice_to_have", []) if k.strip()]
        settings["score_thresholds"]["best_match"] = int(data.get("best_match", 80))
        settings["score_thresholds"]["medium_match"] = int(data.get("medium_match", 60))
        
        # Career Objectives
        co = data.get("career_objective", {})
        settings["career_objective"] = {
            "target_archetype": co.get("target_archetype", "Strategic Product Builder / Early-stage Discovery PM").strip(),
            "target_trajectory": co.get("target_trajectory", "").strip()
        }
        
        # Override rules
        ov = data.get("override_rules", {})
        settings["override_rules"] = {
            "min_problem_space": int(ov.get("min_problem_space", 1)),
            "min_product_stage": int(ov.get("min_product_stage", 3)),
            "min_decision_power": int(ov.get("min_decision_power", 3)),
            "min_customer_interaction": int(ov.get("min_customer_interaction", 1)),
            "min_problem_definition_clarity": int(ov.get("min_problem_definition_clarity", 1))
        }

        settings["search"]["days_ago"] = int(data.get("days_ago", 15))
        settings["search"]["location"] = data.get("location", "Germany").strip()
        settings["search"]["job_titles"] = [t.strip() for t in data.get("job_titles", []) if t.strip()]
        if not settings["search"]["job_titles"]:
            settings["search"]["job_titles"] = ["product manager"]
        settings["search"]["platforms"] = data.get("platforms", ["linkedin", "indeed", "glassdoor"])
        settings["search"]["experience_levels"] = data.get("experience_levels", [])
        settings["search"]["location_types"] = data.get("location_types", [])
        settings["search"]["employment_types"] = data.get("employment_types", [])
        settings["search"]["languages"] = data.get("languages", [])
        settings["resume_text"] = data.get("resume_text", "").strip()
        save_json(SETTINGS_FILE, settings)

        # Re-classify existing jobs under new thresholds/rules
        jobs = load_jobs()
        user_languages = [lang.lower() for lang in settings.get("search", {}).get("languages", []) if lang]
        for j in jobs:
            if "match_score" in j:
                lang_ok = True
                if user_languages:
                    job_languages = [lang.lower() for lang in j.get("language_requirements", [])]
                    if job_languages and not any(lang in user_languages for lang in job_languages):
                        lang_ok = False
                
                if lang_ok:
                    j["match_category"] = classify_job(j, settings)
                else:
                    j["match_category"] = "low"
        save_jobs(jobs)

        sync_data_to_github()
        return jsonify({"status": "ok"})
    return render_template("settings.html", settings=settings)


@app.route("/api/resume/analyze", methods=["POST"])
def api_analyze_resume():
    data = request.get_json() or {}
    resume_text = data.get("resume_text", "").strip()
    if not resume_text:
        return jsonify({"error": "Resume text is empty"}), 400

    try:
        from ai_analyzer import recommend_from_resume
        recommendations = recommend_from_resume(resume_text)
        return jsonify(recommendations)
    except Exception as e:
        logger.error(f"Failed to analyze resume: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/job/translate/<job_id>", methods=["POST"])
def api_translate_job(job_id):
    jobs = load_jobs()
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    
    if job.get("jd_translated"):
        return jsonify({"translated_text": job["jd_translated"]})
        
    jd_text = job.get("jd_text", "")
    if not jd_text:
        return jsonify({"error": "No description to translate"}), 400
        
    try:
        from ai_analyzer import translate_text_to_english
        translated = translate_text_to_english(jd_text)
        job["jd_translated"] = translated
        # Save back updated job
        save_jobs(jobs)
        # Sync immediately
        sync_data_to_github()
        return jsonify({"translated_text": translated})
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return jsonify({"error": str(e)}), 500


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


@app.route("/api/jobs/clear-old", methods=["POST"])
def api_clear_old_jobs():
    data = request.get_json() or {}
    days = int(data.get("days", 30))
    
    jobs = load_jobs()
    initial_count = len(jobs)
    
    cutoff_date = (datetime.now() - timedelta(days=days)).date()
    
    filtered_jobs = []
    for j in jobs:
        date_str = j.get("date_posted", "")
        keep = True
        if date_str:
            try:
                posted_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                if posted_date < cutoff_date:
                    keep = False
            except Exception:
                pass
        if keep:
            filtered_jobs.append(j)
            
    save_jobs(filtered_jobs)
    sync_data_to_github()
    
    cleared_count = initial_count - len(filtered_jobs)
    return jsonify({
        "status": "ok",
        "cleared_count": cleared_count,
        "total_remaining": len(filtered_jobs)
    })


# ── Scheduler ─────────────────────────────────────────────────────────────────
def check_and_trigger_missed_scrape():
    # Wait a few seconds to let the main web process boot up fully
    time.sleep(10)
    try:
        history = load_history()
        if not history:
            logger.info("No scrape history found. Running initial scrape on startup.")
            thread = threading.Thread(target=run_scrape_pipeline, daemon=True)
            thread.start()
            return
            
        last_run_str = history[0].get("run_at", "")
        if last_run_str:
            try:
                # Support timezone offsets or plain ISO format parsing
                # replacing 'Z' with '+00:00' to support older python versions if needed
                clean_ts = last_run_str.replace("Z", "+00:00")
                last_run = datetime.fromisoformat(clean_ts)
                
                # Make sure both datetimes are timezone-naive or zone-aware
                # If last_run is timezone-aware, strip it to match datetime.now()
                if last_run.tzinfo is not None:
                    last_run = last_run.replace(tzinfo=None)
                    
                if datetime.now() - last_run > timedelta(days=6.9):
                    logger.info(f"Last scrape was {last_run_str} (more than 7 days ago). Triggering missed scrape on startup.")
                    thread = threading.Thread(target=run_scrape_pipeline, daemon=True)
                    thread.start()
            except Exception as e:
                logger.error(f"Failed to parse last run timestamp '{last_run_str}': {e}")
    except Exception as e:
        logger.error(f"Error in check_and_trigger_missed_scrape: {e}")


def start_scheduler():
    scheduler = BackgroundScheduler(timezone="UTC")
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
    
    # Run the self-healing startup check in a separate background thread
    thread = threading.Thread(target=check_and_trigger_missed_scrape, daemon=True)
    thread.start()
    
    return scheduler


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    scheduler = start_scheduler()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
