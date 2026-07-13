from __future__ import annotations
import os
import json
import uuid
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, jsonify, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler

from scraper.linkedin import scrape_linkedin
from scraper.indeed import scrape_indeed
from scraper.glassdoor import scrape_glassdoor
from ai_analyzer import analyze_job, classify_job

# DB layer — falls back to JSON if DATABASE_URL is not set
USE_DB = bool(os.environ.get("DATABASE_URL"))
if USE_DB:
    from db import (
        init_db,
        db_load_jobs, db_save_jobs, db_get_job, db_delete_job,
        db_set_favorite, db_get_favorites, db_url_exists,
        db_load_settings, db_save_settings,
        db_load_history, db_save_history,
    )

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Paths (JSON fallback) ─────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
JOBS_FILE = DATA_DIR / "jobs.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.json"

# ── Flask App ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
scrape_lock = threading.Lock()
is_scraping = False


# ── JSON helpers (fallback) ───────────────────────────────────────────────────
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


# ── Unified data helpers (DB or JSON) ────────────────────────────────────────
def load_settings() -> dict:
    if USE_DB:
        return db_load_settings()

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


def save_settings(settings: dict):
    if USE_DB:
        db_save_settings(settings)
    else:
        save_json(SETTINGS_FILE, settings)


def load_jobs() -> list:
    if USE_DB:
        return db_load_jobs()

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
            j["resume_match"] = {"score": 0, "strengths": [], "gaps": [], "explanation": ""}
            modified = True
        if "scorecard" not in j or not j["scorecard"] or "career_trajectory_fit" not in j:
            j["scorecard"] = {
                "problem_space_type": {"score": 3, "label": "Optimization of mature product", "evidence": "Pre-migration record"},
                "product_stage": {"score": 3, "label": "Scaling (1->10)", "evidence": "Pre-migration record"},
                "decision_power": {"score": 3, "label": "Contributes to decisions", "evidence": "Pre-migration record"},
                "customer_interaction": {"score": 3, "label": "Occasional exposure", "evidence": "Pre-migration record"},
                "problem_definition_clarity": {"score": 3, "label": "Medium ambiguity", "evidence": "Pre-migration record"}
            }
            j["career_trajectory_fit"] = {"score": 3, "label": "Neutral", "evidence": "Pre-migration record"}
            j["why_match"] = "Pre-migration record. Run scraper to re-analyze."
            j["why_not_match"] = "Pre-migration record. Run scraper to re-analyze."
            modified = True
    if modified:
        save_json(JOBS_FILE, jobs)
    return jobs


def save_jobs(jobs: list):
    if USE_DB:
        db_save_jobs(jobs)
    else:
        save_json(JOBS_FILE, jobs)


def load_history() -> list:
    if USE_DB:
        return db_load_history()
    return load_json(HISTORY_FILE, [])


def save_history(history: list):
    if USE_DB:
        db_save_history(history)
    else:
        save_json(HISTORY_FILE, history)


def get_job_by_id(job_id: str) -> dict | None:
    if USE_DB:
        return db_get_job(job_id)
    jobs = load_jobs()
    return next((j for j in jobs if j.get("id") == job_id), None)


def url_already_exists(url: str) -> bool:
    if USE_DB:
        return db_url_exists(url)
    jobs = load_jobs()
    return any(j.get("url") == url for j in jobs)


# ── Scraping pipeline ─────────────────────────────────────────────────────────
def run_scrape_pipeline(is_local: bool = False):
    """
    Core pipeline:
    1. Load settings (title, location, days_ago)
    2. Scrape LinkedIn, Indeed, Glassdoor based on configured platforms
    3. Remove duplicates vs existing DB URLs
    4. Enrich company info
    5. Score and filter via Groq
    6. Save to DB
    """
    global is_scraping, scrape_lock
    with scrape_lock:
        if is_scraping:
            logger.info("Scraping already in progress. Skipping.")
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
        resume_text = settings.get("resume_text", "")

        # Existing URLs for dedup
        if USE_DB:
            existing_urls = set()  # db_url_exists() is checked per job below
        else:
            existing_jobs = load_jobs()
            existing_urls = {j["url"] for j in existing_jobs}

        # Define how many pages to scrape based on environment
        linkedin_pages = 5 if is_local else 3
        indeed_pages = 3 if is_local else 1

        all_raw_jobs = []
        for title in job_titles:
            if "linkedin" in platforms:
                logger.info(f"Scraping LinkedIn for '{title}' (up to {linkedin_pages} pages)...")
                try:
                    all_raw_jobs.extend(scrape_linkedin(title, location, days_ago, filter_cfg=search_cfg, existing_urls=existing_urls, max_pages=linkedin_pages))
                except Exception as e:
                    logger.error(f"LinkedIn failed: {e}")

            if "indeed" in platforms:
                logger.info(f"Scraping Indeed for '{title}' (up to {indeed_pages} pages)...")
                try:
                    all_raw_jobs.extend(scrape_indeed(title, location, days_ago, existing_urls=existing_urls, max_pages=indeed_pages))
                except Exception as e:
                    logger.error(f"Indeed failed: {e}")

            if "glassdoor" in platforms:
                logger.info(f"Scraping Glassdoor for '{title}'...")
                try:
                    all_raw_jobs.extend(scrape_glassdoor(title, location, days_ago))
                except Exception as e:
                    logger.error(f"Glassdoor failed: {e}")

        # De-duplicate
        if USE_DB:
            new_raw = [j for j in all_raw_jobs if j.get("url") and not db_url_exists(j["url"])]
        else:
            new_raw = [j for j in all_raw_jobs if j.get("url") and j["url"] not in existing_urls]

        logger.info(f"Found {len(new_raw)} new jobs to analyze.")

        # AI analyze each new job
        analyzed = []
        for job in new_raw:
            try:
                enriched = analyze_job(job, must_have, nice_to_have, resume_text, settings.get("career_objective"))
                enriched["id"] = str(uuid.uuid4())
                enriched["scraped_at"] = datetime.now().isoformat()

                # Classify
                user_languages = [lang.lower() for lang in search_cfg.get("languages", []) if lang]
                if user_languages:
                    job_langs = [lang.lower() for lang in enriched.get("language_requirements", [])]
                    if job_langs and not any(lang in user_languages for lang in job_langs):
                        enriched["match_category"] = "low"
                    else:
                        enriched["match_category"] = classify_job(enriched, settings)
                else:
                    enriched["match_category"] = classify_job(enriched, settings)

                analyzed.append(enriched)
                logger.info(f"  ✓ {job['title']} @ {job['company']} — score: {enriched.get('match_score', 0)}")
            except Exception as e:
                logger.error(f"Analysis failed for {job.get('title')}: {e}")

        # Save new jobs
        if USE_DB:
            db_save_jobs(analyzed)
            # Re-classify all existing jobs with new settings if needed
        else:
            existing_jobs = load_jobs()
            all_jobs = existing_jobs + analyzed
            user_languages = [lang.lower() for lang in search_cfg.get("languages", []) if lang]
            for j in all_jobs:
                if "match_score" in j:
                    if user_languages:
                        job_langs = [lang.lower() for lang in j.get("language_requirements", [])]
                        if job_langs and not any(lang in user_languages for lang in job_langs):
                            j["match_category"] = "low"
                        else:
                            j["match_category"] = classify_job(j, settings)
                    else:
                        j["match_category"] = classify_job(j, settings)
            save_jobs(all_jobs)

        # Log history
        history = load_history()
        new_entry = {
            "run_at": datetime.now().isoformat(),
            "new_jobs_found": len(analyzed),
            "total_jobs": len(analyzed),
            "platforms": platforms,
        }
        history.insert(0, new_entry)
        history = history[:50]
        save_history(history)

        logger.info(f"Scrape complete. {len(analyzed)} new jobs added.")

    finally:
        with scrape_lock:
            is_scraping = False


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def dashboard():
    jobs = load_jobs()
    settings = load_settings()
    history = load_history()

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
    job = get_job_by_id(job_id)
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

        co = data.get("career_objective", {})
        settings["career_objective"] = {
            "target_archetype": co.get("target_archetype", "Strategic Product Builder / Early-stage Discovery PM").strip(),
            "target_trajectory": co.get("target_trajectory", "").strip()
        }

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
        save_settings(settings)

        # Re-classify existing jobs under new thresholds
        if not USE_DB:
            jobs = load_jobs()
            user_languages = [lang.lower() for lang in settings.get("search", {}).get("languages", []) if lang]
            for j in jobs:
                if "match_score" in j:
                    if user_languages:
                        job_langs = [lang.lower() for lang in j.get("language_requirements", [])]
                        if job_langs and not any(lang in user_languages for lang in job_langs):
                            j["match_category"] = "low"
                        else:
                            j["match_category"] = classify_job(j, settings)
                    else:
                        j["match_category"] = classify_job(j, settings)
            save_jobs(jobs)

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
    job = get_job_by_id(job_id)
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
        save_jobs([job])
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
    if USE_DB:
        db_delete_job(job_id)
    else:
        jobs = load_jobs()
        jobs = [j for j in jobs if j.get("id") != job_id]
        save_jobs(jobs)
    return jsonify({"status": "deleted"})


@app.route("/api/jobs/favorite/<job_id>", methods=["POST"])
def api_favorite_job(job_id):
    data = request.get_json() or {}
    is_favorite = bool(data.get("favorite", False))

    if USE_DB:
        db_set_favorite(job_id, is_favorite)
    else:
        jobs = load_jobs()
        for j in jobs:
            if j.get("id") == job_id:
                j["favorite"] = is_favorite
                break
        save_jobs(jobs)

    return jsonify({"status": "ok", "favorite": is_favorite})


@app.route("/api/favorites", methods=["GET"])
def api_get_favorites():
    if USE_DB:
        fav_ids = db_get_favorites()
    else:
        jobs = load_jobs()
        fav_ids = [j["id"] for j in jobs if j.get("favorite")]
    return jsonify({"favorites": fav_ids})


@app.route("/api/jobs/clear", methods=["DELETE"])
def api_clear_jobs():
    if USE_DB:
        # Soft-delete all
        jobs = db_load_jobs()
        for j in jobs:
            db_delete_job(j["id"])
    else:
        save_jobs([])
    return jsonify({"status": "cleared"})


@app.route("/api/jobs/clear-old", methods=["POST"])
def api_clear_old_jobs():
    data = request.get_json() or {}
    days = int(data.get("days", 30))
    cutoff_date = (datetime.now() - timedelta(days=days)).date()

    jobs = load_jobs()
    initial_count = len(jobs)
    cleared_count = 0

    for j in jobs:
        date_str = j.get("date_posted", "")
        if date_str:
            try:
                posted_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                if posted_date < cutoff_date:
                    if USE_DB:
                        db_delete_job(j["id"])
                    cleared_count += 1
            except Exception:
                pass

    if not USE_DB:
        filtered_jobs = [j for j in jobs if not _is_older_than(j.get("date_posted", ""), cutoff_date)]
        save_jobs(filtered_jobs)
        cleared_count = initial_count - len(filtered_jobs)

    return jsonify({
        "status": "ok",
        "cleared_count": cleared_count,
        "total_remaining": initial_count - cleared_count
    })


def _is_older_than(date_str: str, cutoff) -> bool:
    if not date_str:
        return False
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").date() < cutoff
    except Exception:
        return False


# ── Scheduler ─────────────────────────────────────────────────────────────────
def start_scheduler():
    scheduler = BackgroundScheduler()
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


def check_and_trigger_missed_scrape():
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
                clean_ts = last_run_str.replace("Z", "+00:00")
                last_run = datetime.fromisoformat(clean_ts)
                if last_run.tzinfo is not None:
                    last_run = last_run.replace(tzinfo=None)
                if datetime.now() - last_run > timedelta(days=6.9):
                    logger.info(f"Last scrape was {last_run_str} (>7 days). Triggering missed scrape.")
                    thread = threading.Thread(target=run_scrape_pipeline, daemon=True)
                    thread.start()
            except Exception as e:
                logger.error(f"Failed to parse last run timestamp '{last_run_str}': {e}")
    except Exception as e:
        logger.error(f"Error in check_and_trigger_missed_scrape: {e}")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if USE_DB:
        logger.info("DATABASE_URL detected — using PostgreSQL.")
        init_db()
    else:
        logger.info("No DATABASE_URL — using JSON file storage.")

    scheduler = start_scheduler()
    missed_thread = threading.Thread(target=check_and_trigger_missed_scrape, daemon=True)
    missed_thread.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
