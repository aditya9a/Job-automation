"""
AI Job Matcher using Google Gemini.
Scores jobs against your resume/profile for relevance.
"""

import json
import logging
from typing import List, Optional

import google.generativeai as genai

from ..config import settings
from ..models import Job, JobStatus
from ..database import db

logger = logging.getLogger(__name__)


class JobMatcher:
    """
    Uses Google Gemini to score how well each job matches your profile.
    Returns a score (0-100) and reasoning for each job.
    """

    def __init__(self):
        api_key = settings.gemini_api_key
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not set. Add it to your .env file. "
                "Get one at https://aistudio.google.com/app/apikey"
            )
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("models/gemini-3.8-flash")

    def _rule_based_score(self, job: Job) -> dict:
        """Fast fallback rule-based score when AI API is unavailable."""
        # Check experience eligibility
        ok, exp_reason = job.is_experience_eligible(
            settings.min_experience_years, settings.max_experience_years
        )
        if not ok:
            return {
                "score": 0,
                "reason": f"Disqualified: {exp_reason}",
                "strengths": [],
                "gaps": [f"Experience ({job.experience}) exceeds candidate maximum of {settings.max_experience_years:g} years"]
            }

        profile = settings.profile
        prefs = profile.get("preferences", {})
        candidate_skills = set(s.lower() for s in prefs.get("skills", []))
        candidate_roles = [r.lower() for r in prefs.get("roles", [])]

        text = f"{job.title} {job.description} {' '.join(job.skills)}".lower()

        matched_skills = [s for s in candidate_skills if s in text]
        role_match = any(r in job.title.lower() for r in candidate_roles)

        base_score = 40 if role_match else 15
        skill_score = min(50, len(matched_skills) * 8)
        total_score = min(95, base_score + skill_score)

        strengths = [s.title() for s in matched_skills[:5]]
        gaps = ["More experience required" if "senior" in text else "Specific domain knowledge"]

        reason = f"Matched role keywords and {len(matched_skills)} core skills ({', '.join(strengths[:3]) if strengths else 'general'})."
        return {
            "score": total_score,
            "reason": reason,
            "strengths": strengths,
            "gaps": gaps,
        }


    def _build_profile_summary(self) -> str:
        """Build a text summary of the user's profile for the AI prompt."""
        profile = settings.profile
        prefs = profile.get("preferences", {})
        resume = profile.get("resume", {})

        return f"""
CANDIDATE PROFILE:
- Name: {profile.get('personal', {}).get('full_name', 'N/A')}
- Experience Summary: {resume.get('summary', 'N/A')}
- Target Roles: {', '.join(prefs.get('roles', []))}
- Skills: {', '.join(prefs.get('skills', []))}
- Preferred Locations: {', '.join(prefs.get('locations', []))}
- Experience Level: {', '.join(prefs.get('experience_level', []))}
- Minimum Salary: {prefs.get('min_salary_lpa', 0)} LPA
""".strip()

    def _build_job_summary(self, job: Job) -> str:
        """Build a text summary of a job for the AI prompt."""
        skills_str = ", ".join(job.skills) if job.skills else "Not specified"
        return f"""
JOB LISTING:
- Title: {job.title}
- Company: {job.company}
- Location: {job.location or 'Not specified'}
- Salary: {job.salary or 'Not specified'}
- Experience Required: {job.experience or 'Not specified'}
- Job Type: {job.job_type or 'Not specified'}
- Skills: {skills_str}
- Description: {job.description[:1000] if job.description else 'Not available'}
""".strip()

    async def score_job(self, job: Job) -> dict:
        """
        Score a single job against the user's profile.
        Returns: {"score": 0-100, "reason": "...", "strengths": [...], "gaps": [...]}
        """
        # Disqualify immediately if experience does not match candidate profile
        ok, exp_reason = job.is_experience_eligible(
            settings.min_experience_years, settings.max_experience_years
        )
        if not ok:
            return {
                "score": 0,
                "reason": f"Disqualified: {exp_reason}",
                "strengths": [],
                "gaps": [f"Experience ({job.experience or 'senior'}) exceeds candidate filter (0-{settings.max_experience_years:g} yrs)"]
            }

        profile = self._build_profile_summary()
        job_summary = self._build_job_summary(job)

        prompt = f"""You are a job matching assistant. Analyze how well this job matches the candidate's profile.

{profile}

{job_summary}

Respond ONLY with a JSON object (no markdown, no code fences):
{{
    "score": <integer 0-100>,
    "reason": "<1-2 sentence explanation>",
    "strengths": ["<matching strength 1>", "<matching strength 2>"],
    "gaps": ["<gap or concern 1>", "<gap or concern 2>"]
}}

Scoring guide:
- 90-100: Perfect match (role, skills, location, experience all align)
- 70-89: Strong match (most criteria align, minor gaps)
- 50-69: Moderate match (some alignment, notable gaps)
- 30-49: Weak match (few criteria align)
- 0-29: Poor match (significantly misaligned)
"""

        try:
            response = self.model.generate_content(prompt)
            text = response.text.strip()

            # Clean up response (remove markdown code fences if present)
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            text = text.strip()

            result = json.loads(text)
            return {
                "score": min(100, max(0, int(result.get("score", 0)))),
                "reason": result.get("reason", ""),
                "strengths": result.get("strengths", []),
                "gaps": result.get("gaps", []),
            }
        except Exception as e:
            logger.warning(f"AI scoring unavailable ({e}), using resume rule-based scoring fallback")
            return self._rule_based_score(job)

    async def score_jobs(self, jobs: List[Job] = None, batch_size: int = 5) -> int:
        """
        Score multiple jobs. If no jobs given, scores all unmatched jobs in the DB.
        Returns the number of jobs scored.
        """
        if jobs is None:
            jobs = db.get_jobs(status=JobStatus.NEW.value, limit=200)

        scored = 0
        for job in jobs:
            try:
                result = await self.score_job(job)
                score = result["score"]
                reason = result["reason"]

                # Include strengths and gaps in reason
                if result["strengths"]:
                    reason += f" Strengths: {', '.join(result['strengths'])}."
                if result["gaps"]:
                    reason += f" Gaps: {', '.join(result['gaps'])}."

                db.update_match_score(job.id, score, reason)
                scored += 1
                logger.info(
                    f"[matcher] {job.title} @ {job.company}: "
                    f"Score={score} — {result['reason']}"
                )
            except Exception as e:
                logger.error(f"[matcher] Error scoring {job.title}: {e}")
                continue

        logger.info(f"[matcher] Scored {scored}/{len(jobs)} jobs")
        return scored


class CoverLetterGenerator:
    """Generates tailored cover letters using Gemini."""

    def __init__(self):
        api_key = settings.gemini_api_key
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set.")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-3.8-flash")

    async def generate(self, job: Job, style: str = "concise") -> str:
        """
        Generate a cover letter for a specific job.
        style: "concise" (3-4 paragraphs) or "detailed" (5-6 paragraphs)
        """
        profile = settings.profile
        resume_summary = profile.get("resume", {}).get("summary", "")
        name = profile.get("personal", {}).get("full_name", "Candidate")
        skills = ", ".join(profile.get("preferences", {}).get("skills", []))

        length_guide = "3-4 short paragraphs" if style == "concise" else "5-6 paragraphs"

        prompt = f"""Write a professional cover letter for this job application.

CANDIDATE:
- Name: {name}
- Summary: {resume_summary}
- Key Skills: {skills}

JOB:
- Title: {job.title}
- Company: {job.company}
- Description: {job.description[:1500] if job.description else 'Not available'}

REQUIREMENTS:
- Length: {length_guide}
- Tone: Professional but personable
- Focus on relevant experience and enthusiasm for the role
- Don't be generic — reference specific aspects of the company/role
- Don't include the date or address headers
- Start with "Dear Hiring Manager," or "Dear {job.company} Team,"

Write ONLY the cover letter text, nothing else.
"""

        try:
            response = self.model.generate_content(prompt)
            cover_letter = response.text.strip()

            # Save to database
            if job.id:
                db.update_job_status(
                    job.id, job.status,
                    generated_cover_letter=cover_letter
                )

            return cover_letter
        except Exception as e:
            logger.error(f"Cover letter generation error: {e}")
            return ""
