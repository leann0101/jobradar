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


def analyze_job(job: dict, must_have: list[str], nice_to_have: list[str], resume_text: str = "", career_objective: dict = None) -> dict:
    """
    Send a job's JD to Groq for career preferences analysis.
    Returns enriched job dict with AI scorecard, career trajectory fit, why_match, why_not_match, etc.
    """
    client = get_client()
    jd_text = job.get("jd_text", "")
    
    if not jd_text:
        jd_text = f"Job title: {job.get('title', '')} at {job.get('company', '')}"

    must_have_str = ", ".join(must_have)
    nice_to_have_str = ", ".join(nice_to_have)

    target_archetype = ""
    target_trajectory = ""
    if career_objective:
        target_archetype = career_objective.get("target_archetype", "")
        target_trajectory = career_objective.get("target_trajectory", "")
    
    if not target_archetype:
        target_archetype = "Strategic Product Builder / Early-stage Discovery PM"
    if not target_trajectory:
        target_trajectory = "I want to become a strategy-driven, discovery-oriented product builder who defines problems in emerging tech."

    resume_prompt_part = ""
    if resume_text.strip():
        resume_prompt_part = f"""
CANDIDATE'S RESUME:
{resume_text[:6000]}

Evaluate the match between the resume and the job description. Provide a compatibility score (0-100), key candidate strengths (matching requirements), and key gaps/missing requirements.
"""
    else:
        resume_prompt_part = "\nNo candidate resume is provided. For the 'resume_match' field, return score 0, empty strengths, empty gaps, and 'Resume not provided' as the explanation.\n"

    prompt = f"""You are an expert job analyst. Analyze this job description, evaluate the fit against the user's career objectives and preferences, extract company profile information, and evaluate compatibility with the candidate's resume (if provided).

JOB DESCRIPTION:
{jd_text[:4000]}

USER'S MUST-HAVE keywords (informational references for technical/domain preferences):
{must_have_str}

USER'S NICE-TO-HAVE keywords:
{nice_to_have_str}

CANDIDATE'S CAREER OBJECTIVES:
- Target Role Archetype: {target_archetype}
- Desired Career Trajectory: {target_trajectory}

{resume_prompt_part}

Evaluate the job against the following 5 dimensions. For each dimension, assign a score from 1 to 5, a short descriptive label, and extract a direct quote from the job description as evidence.

Dimensions:
1. Problem Space Type
   - 5: Emerging tech / new market / 0→1
   - 4: New application of existing tech
   - 3: Optimization of mature product
   - 1 or 2: Operational / maintenance work
2. Product Stage
   - 5: 0→1 discovery
   - 4: Early product (pre PMF)
   - 3: Scaling (1→10)
   - 2: Mature product (10→100)
   - 1: Legacy / maintenance
3. Decision Power
   - 5: Defines product direction
   - 4: Influences roadmap
   - 3: Contributes to decisions
   - 2: Executes roadmap
   - 1: Pure execution
4. Customer Interaction Level
   - 5: Deep customer discovery
   - 4: Frequent customer interaction
   - 3: Occasional exposure
   - 2: Indirect exposure
   - 1: No customer interaction
5. Problem Definition Clarity
   - 5: Completely undefined problem (highly ambiguous / unstructured)
   - 4: High ambiguity
   - 3: Medium ambiguity
   - 2: Low ambiguity
   - 1: Fully defined problem (completely clear / structured)

Also evaluate Career Trajectory Fit (CTF) from 1 to 5 based on how well this job moves the candidate toward their target identity: "{target_archetype}" and trajectory: "{target_trajectory}".
Evaluate skill compounding, decision surface exposure, and system position (Creating vs. Shaping vs. Running system).
Assign:
- 5: Strongly moves toward target identity
- 4: Clearly positive trajectory
- 3: Neutral
- 2: Slight drift away
- 1: Strong drift away
Provide a direct quote from the JD as evidence for this CTF score.

Provide detailed explanations for the match:
- why_match: Deep explanation of why this job matches the user's career objectives (which aspects, dimensions, or duties align well).
- why_not_match: Deep explanation of why this job might NOT match the user's career objectives, any potential gaps, or risks of drifting away from the target trajectory.

Respond with ONLY valid JSON, no markdown, no code blocks.

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
    "business_domain": "business domain",
    "employee_count": "employee count"
  }},
  "resume_match": {{
    "score": 85,
    "strengths": ["strengths"],
    "gaps": ["gaps"],
    "explanation": "overview"
  }},
  "scorecard": {{
    "problem_space_type": {{
      "score": 4,
      "label": "New application of existing tech",
      "evidence": "quote from JD"
    }},
    "product_stage": {{
      "score": 3,
      "label": "Scaling (1->10)",
      "evidence": "quote from JD"
    }},
    "decision_power": {{
      "score": 4,
      "label": "Influences roadmap",
      "evidence": "quote from JD"
    }},
    "customer_interaction": {{
      "score": 5,
      "label": "Deep customer discovery",
      "evidence": "quote from JD"
    }},
    "problem_definition_clarity": {{
      "score": 3,
      "label": "Medium ambiguity",
      "evidence": "quote from JD"
    }}
  }},
  "career_trajectory_fit": {{
    "score": 4,
    "label": "Clearly positive trajectory",
    "evidence": "quote from JD"
  }},
  "why_match": "Detailed explanation of positive match factors...",
  "why_not_match": "Detailed explanation of negative/risk match factors..."
}}
"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1536,
        )
        raw = response.choices[0].message.content.strip()
        
        # Clean possible markdown wrapping
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        
        analysis = json.loads(raw)
    except Exception as e:
        logger.error(f"Groq API or JSON parse error: {e}")
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
            "match_explanation": f"Analysis failed: {str(e)}",
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
            },
            "scorecard": {
                "problem_space_type": {"score": 1, "label": "Operational / maintenance work", "evidence": ""},
                "product_stage": {"score": 1, "label": "Legacy / maintenance", "evidence": ""},
                "decision_power": {"score": 1, "label": "Pure execution", "evidence": ""},
                "customer_interaction": {"score": 1, "label": "No customer interaction", "evidence": ""},
                "problem_definition_clarity": {"score": 1, "label": "Fully defined problem", "evidence": ""}
            },
            "career_trajectory_fit": {"score": 1, "label": "Strong drift away", "evidence": ""},
            "why_match": "Analysis failed.",
            "why_not_match": "Analysis failed."
        }

    # Extract score from scorecard
    scorecard = analysis.get("scorecard", {})
    if not scorecard:
        scorecard = {
            "problem_space_type": {"score": 1, "label": "Operational / maintenance work", "evidence": ""},
            "product_stage": {"score": 1, "label": "Legacy / maintenance", "evidence": ""},
            "decision_power": {"score": 1, "label": "Pure execution", "evidence": ""},
            "customer_interaction": {"score": 1, "label": "No customer interaction", "evidence": ""},
            "problem_definition_clarity": {"score": 1, "label": "Fully defined problem", "evidence": ""}
        }
        analysis["scorecard"] = scorecard
        
    problem_space = scorecard.get("problem_space_type", {}).get("score", 1)
    product_stage = scorecard.get("product_stage", {}).get("score", 1)
    decision_power = scorecard.get("decision_power", {}).get("score", 1)
    customer_interaction = scorecard.get("customer_interaction", {}).get("score", 1)
    problem_definition_clarity = scorecard.get("problem_definition_clarity", {}).get("score", 1)
    
    try: problem_space = int(problem_space)
    except: problem_space = 1
    try: product_stage = int(product_stage)
    except: product_stage = 1
    try: decision_power = int(decision_power)
    except: decision_power = 1
    try: customer_interaction = int(customer_interaction)
    except: customer_interaction = 1
    try: problem_definition_clarity = int(problem_definition_clarity)
    except: problem_definition_clarity = 1

    # Ensure clean numeric values in scorecard dict
    scorecard.setdefault("problem_space_type", {})["score"] = problem_space
    scorecard.setdefault("product_stage", {})["score"] = product_stage
    scorecard.setdefault("decision_power", {})["score"] = decision_power
    scorecard.setdefault("customer_interaction", {})["score"] = customer_interaction
    scorecard.setdefault("problem_definition_clarity", {})["score"] = problem_definition_clarity

    # Job Fit Score (weighted average of 5 dimensions)
    fit_score = (problem_space * 5) + (product_stage * 5) + (decision_power * 4) + (customer_interaction * 3) + (problem_definition_clarity * 3)

    return {**job, **analysis, "match_score": fit_score}


def classify_job(job_or_score, settings: dict) -> str:
    """
    Returns 'best', 'medium', or 'low' based on score thresholds and override gating rules.
    Accepts either a full job dict or an integer score for backward compatibility.
    """
    score_thresholds = settings.get("score_thresholds", settings)
    best_threshold = score_thresholds.get("best_match", 80)
    medium_threshold = score_thresholds.get("medium_match", 60)
    
    if not isinstance(job_or_score, dict):
        if job_or_score >= best_threshold:
            return "best"
        elif job_or_score >= medium_threshold:
            return "medium"
        return "low"

    job = job_or_score
    score = job.get("match_score", 0)
    scorecard = job.get("scorecard", {})
    ctf_info = job.get("career_trajectory_fit", {})
    ctf_score = ctf_info.get("score", 1)
    
    product_stage = scorecard.get("product_stage", {}).get("score", 1)
    decision_power = scorecard.get("decision_power", {}).get("score", 1)
    problem_space = scorecard.get("problem_space_type", {}).get("score", 1)
    customer_interaction = scorecard.get("customer_interaction", {}).get("score", 1)
    problem_definition_clarity = scorecard.get("problem_definition_clarity", {}).get("score", 1)
    
    try: ctf_score = int(ctf_score)
    except: ctf_score = 1
    try: product_stage = int(product_stage)
    except: product_stage = 1
    try: decision_power = int(decision_power)
    except: decision_power = 1
    try: problem_space = int(problem_space)
    except: problem_space = 1
    try: customer_interaction = int(customer_interaction)
    except: customer_interaction = 1
    try: problem_definition_clarity = int(problem_definition_clarity)
    except: problem_definition_clarity = 1
    
    # Load gating rules from settings override_rules
    override_rules = settings.get("override_rules", {})
    min_ps = override_rules.get("min_problem_space", 1)
    min_stage = override_rules.get("min_product_stage", 3)
    min_dec = override_rules.get("min_decision_power", 3)
    min_cust = override_rules.get("min_customer_interaction", 1)
    min_clarity = override_rules.get("min_problem_definition_clarity", 1)
    
    try: min_ps = int(min_ps)
    except: min_ps = 1
    try: min_stage = int(min_stage)
    except: min_stage = 3
    try: min_dec = int(min_dec)
    except: min_dec = 3
    try: min_cust = int(min_cust)
    except: min_cust = 1
    try: min_clarity = int(min_clarity)
    except: min_clarity = 1
    
    # Rule 1: CTF <= 2 -> Low Match (forced)
    if ctf_score <= 2:
        return "low"
        
    # Rule 2: High Match qualifications
    if score >= best_threshold:
        # Check gating requirements: CTF >= 4 AND all dimensions satisfy user minimums
        if (ctf_score >= 4 and 
            problem_space >= min_ps and 
            product_stage >= min_stage and 
            decision_power >= min_dec and 
            customer_interaction >= min_cust and 
            problem_definition_clarity >= min_clarity):
            return "best"
        else:
            return "medium"
            
    # Rule 3: Medium Match
    if score >= medium_threshold:
        return "medium"
        
    # Rule 4: Low Match
    return "low"


def translate_text_to_english(text: str) -> str:
    """
    Translate a job description into English using Llama 3.3.
    """
    client = get_client()
    prompt = f"""You are a professional business translator. Translate the following job description into clear, fluent, professional business English.
Keep the original layout, formatting, line breaks, and bullet points exactly the same.
Do NOT include any introductory or concluding remarks, explanations, or notes. Output ONLY the translated text.

TEXT TO TRANSLATE:
{text[:4000]}
"""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2048,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error in translate_text_to_english: {e}")
        raise e
