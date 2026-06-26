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


def recommend_from_resume(resume_text: str) -> dict:
    """
    Analyze the resume text using Groq and recommend relevant job titles and search keywords.
    """
    client = get_client()
    
    prompt = f"""You are a career consultant and ATS expert. Analyze this candidate's resume and recommend relevant job titles and search keywords for their job hunt.
Ensure that the recommended keywords are aligned with industrial, tech, software, manufacturing, or B2B sectors if relevant.

RESUME:
{resume_text[:6000]}

Respond with ONLY valid JSON, no markdown, no code blocks.
Respond with this exact JSON structure:
{{
  "recommended_titles": ["title1", "title2", "title3"],
  "recommended_keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5", "keyword6"]
}}
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=512,
        )
        raw = response.choices[0].message.content.strip()
        
        # Clean possible markdown wrapping
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        
        res = json.loads(raw)
        return {
            "recommended_titles": res.get("recommended_titles", []),
            "recommended_keywords": res.get("recommended_keywords", [])
        }
    except Exception as e:
        logger.error(f"Error in recommend_from_resume: {e}")
        raise e


def analyze_job(job: dict, must_have: list[str], nice_to_have: list[str], resume_text: str = "") -> dict:
    """
    Send a job's JD to Groq for analysis.
    Returns enriched job dict with AI fields, match score, company profile, and resume match.
    """
    client = get_client()
    jd_text = job.get("jd_text", "")
    
    if not jd_text:
        jd_text = f"Job title: {job.get('title', '')} at {job.get('company', '')}"

    must_have_str = ", ".join(must_have)
    nice_to_have_str = ", ".join(nice_to_have)

    resume_prompt_part = ""
    if resume_text.strip():
        resume_prompt_part = f"""
CANDIDATE'S RESUME:
{resume_text[:6000]}

Evaluate the match between the resume and the job description. Provide a compatibility score (0-100), key candidate strengths (matching requirements), and key gaps/missing requirements.
"""
    else:
        resume_prompt_part = "\nNo candidate resume is provided. For the 'resume_match' field, return score 0, empty strengths, empty gaps, and 'Resume not provided' as the explanation.\n"

    prompt = f"""You are an expert job analyst. Analyze this job description, evaluate the fit against user preferences, extract company profile information, and evaluate compatibility with the candidate's resume (if provided).
Respond with ONLY valid JSON, no markdown, no code blocks.

JOB DESCRIPTION:
{jd_text[:4000]}

USER'S MUST-HAVE keywords (industrial/technical preferences):
{must_have_str}

USER'S NICE-TO-HAVE keywords:
{nice_to_have_str}
{resume_prompt_part}

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
  "match_explanation": "One sentence explaining the preferences match quality",
  "company_profile": {{
    "description": "Brief description of the company and what it does",
    "business_domain": "e.g. Factory Automation / Industrial Networking / IIoT Solutions",
    "employee_count": "e.g. 50-200 / 10,000+ / Unknown"
  }},
  "resume_match": {{
    "score": 85,
    "strengths": ["list of candidate's strengths matching this job"],
    "gaps": ["list of candidate's missing qualifications or skills"],
    "explanation": "Brief overview of the fit with candidate's experience"
  }}
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
            "company_profile": {
                "description": "Company description unavailable",
                "business_domain": "",
                "employee_count": "Unknown"
            },
            "resume_match": {
                "score": 0,
                "strengths": [],
                "gaps": [],
                "explanation": "Analysis failed or unavailable"
            }
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
            "company_profile": {
                "description": "Company description unavailable",
                "business_domain": "",
                "employee_count": "Unknown"
            },
            "resume_match": {
                "score": 0,
                "strengths": [],
                "gaps": [],
                "explanation": "Analysis failed or unavailable"
            }
        }

    # Calculate match score (Preferences score)
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
