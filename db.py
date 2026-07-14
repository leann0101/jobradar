"""
db.py — Database layer for JobRadar using SQLAlchemy + PostgreSQL.
Replaces jobs.json / settings.json / history.json file storage.

Requires env var:
  DATABASE_URL=postgresql://user:password@host:5432/dbname
"""
from __future__ import annotations
import os
import json
import logging
from typing import Optional
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, String, Integer, Boolean,
    Text, DateTime, JSON, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session

logger = logging.getLogger(__name__)

# ── Engine setup ──────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Render sets DATABASE_URL starting with 'postgres://' (older format),
# SQLAlchemy 1.4+ needs 'postgresql://'
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

_engine = None
_Session = None


def get_engine():
    global _engine
    if _engine is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL environment variable is not set.")
        _engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,        # Reconnect on lost connection
            pool_recycle=300,          # Recycle connections every 5 min
            connect_args={"connect_timeout": 10}
        )
        logger.info("SQLAlchemy engine created.")
    return _engine


def get_session():
    global _Session
    if _Session is None:
        _Session = scoped_session(sessionmaker(bind=get_engine()))
    return _Session


Base = declarative_base()


# ── Models ────────────────────────────────────────────────────────────────────

class Job(Base):
    """One scraped + analyzed job listing."""
    __tablename__ = "jobs"

    id              = Column(String, primary_key=True)
    title           = Column(String, nullable=False)
    company         = Column(String, default="")
    location        = Column(String, default="")
    url             = Column(String, default="", unique=True)
    platform        = Column(String, default="")
    date_posted     = Column(String, default="")
    scraped_at      = Column(String, default="")
    jd_text         = Column(Text, default="")

    # AI analysis fields
    summary             = Column(Text, default="")
    required_skills     = Column(JSON, default=list)
    preferred_skills    = Column(JSON, default=list)
    industry            = Column(String, default="")
    experience_level    = Column(String, default="")
    language_requirements = Column(JSON, default=list)
    matched_must_have   = Column(JSON, default=list)
    matched_nice_to_have = Column(JSON, default=list)
    missing_must_have   = Column(JSON, default=list)
    match_explanation   = Column(Text, default="")
    match_score         = Column(Integer, default=0)
    match_category      = Column(String, default="low")  # best / medium / low

    # Scorecard (5 dimensions) + CTF
    scorecard               = Column(JSON, default=dict)
    career_trajectory_fit   = Column(JSON, default=dict)
    why_match               = Column(Text, default="")
    why_not_match           = Column(Text, default="")

    # Company Intelligence
    company_profile     = Column(JSON, default=dict)

    # Resume match
    resume_match        = Column(JSON, default=dict)

    # User flags
    favorite    = Column(Boolean, default=False)
    viewed      = Column(Boolean, default=False)
    deleted     = Column(Boolean, default=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "platform": self.platform,
            "date_posted": self.date_posted,
            "scraped_at": self.scraped_at,
            "jd_text": self.jd_text,
            "summary": self.summary,
            "required_skills": self.required_skills or [],
            "preferred_skills": self.preferred_skills or [],
            "industry": self.industry,
            "experience_level": self.experience_level,
            "language_requirements": self.language_requirements or [],
            "matched_must_have": self.matched_must_have or [],
            "matched_nice_to_have": self.matched_nice_to_have or [],
            "missing_must_have": self.missing_must_have or [],
            "match_explanation": self.match_explanation,
            "match_score": self.match_score,
            "match_category": self.match_category,
            "scorecard": self.scorecard or {},
            "career_trajectory_fit": self.career_trajectory_fit or {},
            "why_match": self.why_match,
            "why_not_match": self.why_not_match,
            "company_profile": self.company_profile or {},
            "resume_match": self.resume_match or {},
            "favorite": self.favorite,
            "viewed": self.viewed,
        }


class Setting(Base):
    """Key-value store for app settings (one row per key)."""
    __tablename__ = "settings"

    key     = Column(String, primary_key=True)
    value   = Column(JSON, nullable=False)


class ScrapeHistory(Base):
    """Log of scrape pipeline runs."""
    __tablename__ = "scrape_history"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    run_at      = Column(String, nullable=False)
    total_found = Column(Integer, default=0)
    new_jobs    = Column(Integer, default=0)
    platforms   = Column(JSON, default=list)
    status      = Column(String, default="ok")
    error       = Column(Text, default="")


# ── Init ──────────────────────────────────────────────────────────────────────

def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(get_engine())
    logger.info("Database tables initialized.")


# ── Job CRUD ──────────────────────────────────────────────────────────────────

def db_load_jobs(include_deleted=False) -> list:
    Session = get_session()
    try:
        q = Session.query(Job)
        if not include_deleted:
            q = q.filter(Job.deleted == False)
        jobs = q.order_by(Job.scraped_at.desc()).all()
        return [j.to_dict() for j in jobs]
    finally:
        Session.remove()


def _parse_json_field(val):
    """If val is a JSON string, parse it. Otherwise return as-is."""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


# JSON fields that may arrive as strings and need parsing
_JSON_FIELDS = [
    "required_skills", "preferred_skills", "language_requirements",
    "matched_must_have", "matched_nice_to_have", "missing_must_have",
    "scorecard", "career_trajectory_fit", "company_profile", "resume_match",
]


def db_save_jobs(jobs: list):
    """Upsert a list of job dicts into the DB (Optimized with Batch Commits)."""
    Session = get_session()
    try:
        # Fetch all existing jobs in one query
        existing_objs = Session.query(Job).all()
        existing_by_id = {obj.id: obj for obj in existing_objs}
        existing_by_url = {obj.url: obj for obj in existing_objs if obj.url}

        batch_size = 10
        for i, job_dict in enumerate(jobs):
            # Parse any JSON-string fields back to dicts/lists
            clean = {k: v for k, v in job_dict.items()}
            for field in _JSON_FIELDS:
                if field in clean:
                    clean[field] = _parse_json_field(clean[field])

            # why_match / why_not_match may be dicts — flatten to string
            for field in ("why_match", "why_not_match"):
                val = clean.get(field, "")
                if isinstance(val, dict):
                    # Extract text from nested explanation lists
                    exp = val.get("explanation", val)
                    if isinstance(exp, list):
                        clean[field] = "\n".join(str(x) for x in exp)
                    else:
                        clean[field] = str(exp)
                elif not isinstance(val, str):
                    clean[field] = str(val)

            # Check match in memory
            existing = None
            job_id = clean.get("id")
            job_url = clean.get("url")

            if job_id in existing_by_id:
                existing = existing_by_id[job_id]
            elif job_url and job_url in existing_by_url:
                existing = existing_by_url[job_url]

            if existing:
                clean["id"] = existing.id
                for k, v in clean.items():
                    if hasattr(existing, k):
                        setattr(existing, k, v)
            else:
                kwargs = {k: v for k, v in clean.items() if hasattr(Job, k)}
                new_job = Job(**kwargs)
                Session.add(new_job)
                # Update memory maps to prevent duplicates within the list itself
                if new_job.id:
                    existing_by_id[new_job.id] = new_job
                if new_job.url:
                    existing_by_url[new_job.url] = new_job

            # Commit periodically to avoid network timeouts on large payloads
            if (i + 1) % batch_size == 0:
                Session.commit()
                logger.info(f"  Processed and committed {i + 1}/{len(jobs)} jobs...")

        # Final commit
        Session.commit()
    except Exception as e:
        Session.rollback()
        logger.error(f"db_save_jobs error: {e}")
        raise
    finally:
        Session.remove()


def db_get_job(job_id: str) -> Optional[dict]:
    Session = get_session()
    try:
        job = Session.query(Job).filter_by(id=job_id, deleted=False).first()
        return job.to_dict() if job else None
    finally:
        Session.remove()


def db_delete_job(job_id: str):
    Session = get_session()
    try:
        job = Session.query(Job).filter_by(id=job_id).first()
        if job:
            job.deleted = True
            Session.commit()
    except Exception as e:
        Session.rollback()
        raise
    finally:
        Session.remove()


def db_set_favorite(job_id: str, is_favorite: bool):
    Session = get_session()
    try:
        job = Session.query(Job).filter_by(id=job_id).first()
        if job:
            job.favorite = is_favorite
            Session.commit()
    except Exception as e:
        Session.rollback()
        raise
    finally:
        Session.remove()


def db_get_favorites() -> list:
    Session = get_session()
    try:
        jobs = Session.query(Job).filter_by(favorite=True, deleted=False).all()
        return [j.id for j in jobs]
    finally:
        Session.remove()


def db_url_exists(url: str) -> bool:
    Session = get_session()
    try:
        return Session.query(Job).filter_by(url=url).first() is not None
    finally:
        Session.remove()

def db_get_all_urls() -> set:
    Session = get_session()
    try:
        rows = Session.query(Job.url).filter(Job.url != "").all()
        return {r[0] for r in rows if r[0]}
    finally:
        Session.remove()


# ── Settings CRUD ─────────────────────────────────────────────────────────────

SETTINGS_DEFAULTS = {
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


def db_load_settings() -> dict:
    Session = get_session()
    try:
        rows = Session.query(Setting).all()
        data = {r.key: r.value for r in rows}
        # Apply defaults for missing keys
        result = dict(SETTINGS_DEFAULTS)
        result.update(data)
        # Deep merge nested dicts
        for k, v in SETTINGS_DEFAULTS.items():
            if isinstance(v, dict) and isinstance(result.get(k), dict):
                merged = dict(v)
                merged.update(result[k])
                result[k] = merged
        return result
    finally:
        Session.remove()


def db_save_settings(settings: dict):
    Session = get_session()
    try:
        for key, value in settings.items():
            row = Session.query(Setting).filter_by(key=key).first()
            if row:
                row.value = value
            else:
                Session.add(Setting(key=key, value=value))
        Session.commit()
    except Exception as e:
        Session.rollback()
        raise
    finally:
        Session.remove()


# ── History CRUD ──────────────────────────────────────────────────────────────

def db_load_history() -> list:
    Session = get_session()
    try:
        rows = Session.query(ScrapeHistory).order_by(ScrapeHistory.id.desc()).all()
        return [
            {
                "run_at": r.run_at,
                "total_found": r.total_found,
                "new_jobs": r.new_jobs,
                "platforms": r.platforms or [],
                "status": r.status,
                "error": r.error,
            }
            for r in rows
        ]
    finally:
        Session.remove()


def db_save_history(history: list):
    """Overwrite history by replacing all rows with the given list."""
    Session = get_session()
    try:
        # Only insert the first (newest) entry if it's not already stored
        if not history:
            return
        latest = history[0]
        row = ScrapeHistory(
            run_at=latest.get("run_at", datetime.utcnow().isoformat()),
            total_found=latest.get("total_found", 0),
            new_jobs=latest.get("new_jobs", 0),
            platforms=latest.get("platforms", []),
            status=latest.get("status", "ok"),
            error=latest.get("error", ""),
        )
        Session.add(row)
        Session.commit()
    except Exception as e:
        Session.rollback()
        raise
    finally:
        Session.remove()
