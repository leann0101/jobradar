"""
migrate_json_to_db.py
把現有 data/jobs.json, settings.json, history.json 的資料匯入 PostgreSQL。

使用方法：
  DATABASE_URL=postgresql://... python migrate_json_to_db.py
"""
import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"


def main():
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    if not DATABASE_URL:
        raise SystemExit("❌ DATABASE_URL environment variable is not set.")

    from db import init_db, db_save_jobs, db_save_settings, db_save_history

    logger.info("Initializing DB tables...")
    init_db()

    # ── Migrate jobs ──────────────────────────────────────────────────────────
    jobs_path = DATA_DIR / "jobs.json"
    if jobs_path.exists():
        with open(jobs_path) as f:
            jobs = json.load(f)
        logger.info(f"Migrating {len(jobs)} jobs...")
        db_save_jobs(jobs)
        logger.info("✅ Jobs migrated.")
    else:
        logger.warning("No jobs.json found, skipping jobs migration.")

    # ── Migrate settings ──────────────────────────────────────────────────────
    settings_path = DATA_DIR / "settings.json"
    if settings_path.exists():
        with open(settings_path) as f:
            settings = json.load(f)
        logger.info("Migrating settings...")
        db_save_settings(settings)
        logger.info("✅ Settings migrated.")
    else:
        logger.warning("No settings.json found, skipping settings migration.")

    # ── Migrate history ───────────────────────────────────────────────────────
    history_path = DATA_DIR / "history.json"
    if history_path.exists():
        with open(history_path) as f:
            history = json.load(f)
        logger.info(f"Migrating {len(history)} history records...")
        for entry in history:
            db_save_history([entry])
        logger.info("✅ History migrated.")
    else:
        logger.warning("No history.json found, skipping history migration.")

    logger.info("\n🎉 Migration complete! You can now set DATABASE_URL in Render and remove JSON sync.")


if __name__ == "__main__":
    main()
