import os
import json
import logging
from groq import Groq

logger = logging.getLogger(__name__)

_client = None


def get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")
        _client = Groq(api_key=api_key)
    return _client


def analyze_job(job: dict, must_have: list[str], nice_to_have: list[str]) -> dict:
    """
    Send a job's JD to Groq for analysis.
    Returns enriched job dict with AI fields and match score.
    """
    client = get_client()
    jd_text = job.get("jd_text", "")
    
    if not jd_text:
        jd_text = f"Job title: {job.get('title', '')} at {job.get('company', '')}"

    must_have_str = ", ".join(must_have)
    nice_to_have_str = ", ".join(nice_to_have)

    prompt = f"""You are an expert job analyst. Analyze this job description and respond with ONLY valid JSON, no markdown, no code blocks.

JOB DESCRIPTION:
{jd_text[:4000]}

USER'S MUST-HAVE keywords (industrial/technical preferences):
{must_have_str}

USER'S NICE-TO-HAVE keywords:
{nice_to_have_str}

Respond with this exact JSON structure:
{{
  "summary": "3-sentence summary of the role",
  "required_skills": ["skill1", "skill2"],
  "preferred_skills": ["skill1", "skill2"],
  "industry": "industry/domain of the company",
  "experience_level": "Junior/Mid/Senior/Lead",
  "language_requirements": ["English", "German"],
  "matched_must_have": ["matched keyword1", "matched keyword2"],
  "matched_nice_to_have": ["matched keyword1"],
  "missing_must_have": ["missing keyword1"],
  "match_explanation": "One sentence explaining the match quality"
}}

For matched keywords: list any must-have or nice-to-have keywords that appear directly or conceptually in the JD.
Be generous in concept matching (e.g. "automation" matches "Factory Automation", "IoT" matches "IIoT").
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1024,
        )
        raw = response.choices[0].message.content.strip()
        
        # Clean possible markdown wrapping
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        
        analysis = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error from Groq: {e}, raw: {raw[:200]}")
        analysis = {
            "summary": "Analysis unavailable",
            "required_skills": [],
            "preferred_skills": [],
            "industry": "",
            "experience_level": "",
            "language_requirements": [],
            "matched_must_have": [],
            "matched_nice_to_have": [],
            "missing_must_have": must_have,
            "match_explanation": "Could not analyze this job.",
        }
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        analysis = {
            "summary": "Analysis unavailable",
            "required_skills": [],
            "preferred_skills": [],
            "industry": "",
            "experience_level": "",
            "language_requirements": [],
            "matched_must_have": [],
            "matched_nice_to_have": [],
            "missing_must_have": must_have,
            "match_explanation": f"API error: {str(e)}",
        }

    # Calculate match score
    score = _calculate_score(
        analysis.get("matched_must_have", []),
        analysis.get("matched_nice_to_have", []),
        must_have,
        nice_to_have,
    )

    return {**job, **analysis, "match_score": score}


def _calculate_score(
    matched_must: list,
    matched_nice: list,
    total_must: list,
    total_nice: list,
) -> int:
    """
    Weighted match score:
      must_have keywords weight = 2
      nice_to_have keywords weight = 1
    Score = 0–100
    """
    must_weight = 2
    nice_weight = 1

    max_score = len(total_must) * must_weight + len(total_nice) * nice_weight
    if max_score == 0:
        return 0

    earned = len(matched_must) * must_weight + len(matched_nice) * nice_weight
    return round((earned / max_score) * 100)


def classify_job(score: int, thresholds: dict) -> str:
    """Returns 'best', 'medium', or 'low' based on score thresholds."""
    best = thresholds.get("best_match", 40)
    medium = thresholds.get("medium_match", 15)
    if score >= best:
        return "best"
    elif score >= medium:
        return "medium"
    return "low"
