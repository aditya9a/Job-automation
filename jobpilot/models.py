"""
Data models for JobPilot.
Defines the Job, Application, and related data structures.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple


class JobStatus(Enum):
    """Status of a job listing in our pipeline."""
    NEW = "new"                    # Just scraped
    MATCHED = "matched"            # AI has scored it
    SHORTLISTED = "shortlisted"    # User wants to apply
    APPLYING = "applying"          # Auto-filler is working on it
    REVIEW = "review"              # Filled form, waiting for user to review & submit
    APPLIED = "applied"            # Successfully applied
    REJECTED = "rejected"          # User rejected / not interested
    EXPIRED = "expired"            # Job no longer available
    ERROR = "error"                # Error during application


class Platform(Enum):
    """Supported job platforms."""
    CUTSHORT = "cutshort"
    WELLFOUND = "wellfound"
    HIRIST = "hirist"
    LINKEDIN = "linkedin"


@dataclass
class Job:
    """Represents a single job listing."""
    # Core fields
    title: str
    company: str
    platform: str
    url: str

    # Details
    location: str = ""
    salary: str = ""
    experience: str = ""
    job_type: str = ""  # full-time, internship, contract
    description: str = ""
    skills: list = field(default_factory=list)
    posted_date: str = ""

    # Internal tracking
    id: Optional[int] = None
    external_id: str = ""  # Platform-specific job ID
    status: str = JobStatus.NEW.value
    match_score: float = 0.0
    match_reason: str = ""
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())
    applied_at: str = ""

    # AI-generated content
    generated_cover_letter: str = ""
    generated_answers: str = ""  # JSON string of Q&A pairs

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage."""
        return {
            "title": self.title,
            "company": self.company,
            "platform": self.platform,
            "url": self.url,
            "location": self.location,
            "salary": self.salary,
            "experience": self.experience,
            "job_type": self.job_type,
            "description": self.description,
            "skills": ",".join(self.skills) if isinstance(self.skills, list) else self.skills,
            "posted_date": self.posted_date,
            "external_id": self.external_id,
            "status": self.status,
            "match_score": self.match_score,
            "match_reason": self.match_reason,
            "scraped_at": self.scraped_at,
            "applied_at": self.applied_at,
            "generated_cover_letter": self.generated_cover_letter,
            "generated_answers": self.generated_answers,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        """Create a Job from a dictionary (database row)."""
        skills = data.get("skills", "")
        if isinstance(skills, str) and skills:
            skills = skills.split(",")
        elif not skills:
            skills = []

        return cls(
            id=data.get("id"),
            title=data.get("title", ""),
            company=data.get("company", ""),
            platform=data.get("platform", ""),
            url=data.get("url", ""),
            location=data.get("location", ""),
            salary=data.get("salary", ""),
            experience=data.get("experience", ""),
            job_type=data.get("job_type", ""),
            description=data.get("description", ""),
            skills=skills,
            posted_date=data.get("posted_date", ""),
            external_id=data.get("external_id", ""),
            status=data.get("status", JobStatus.NEW.value),
            match_score=data.get("match_score", 0.0),
            match_reason=data.get("match_reason", ""),
            scraped_at=data.get("scraped_at", ""),
            applied_at=data.get("applied_at", ""),
            generated_cover_letter=data.get("generated_cover_letter", ""),
            generated_answers=data.get("generated_answers", ""),
        )

    @property
    def unique_key(self) -> str:
        """Generate a unique key for deduplication."""
        return f"{self.platform}:{self.external_id or self.url}"

    def is_experience_eligible(self, min_allowed: float = 0.0, max_allowed: float = 2.0) -> Tuple[bool, str]:
        """Check if this job's experience requirements fit the user's criteria (e.g. 0-2 years)."""
        # First check title for senior-level indicators
        title_lower = self.title.lower()
        senior_keywords = [
            "senior", "sr.", "sr ", "lead", "principal", "staff", "director",
            "vp ", "vice president", "architect", "manager", "head of", "chief", "cto",
            "associate director", "avp"
        ]
        for kw in senior_keywords:
            if re.search(r'\b' + re.escape(kw.strip()) + r'\b', title_lower):
                return False, f"Title indicates senior role: '{kw.strip()}'"

        return is_experience_eligible(self.experience, min_allowed, max_allowed)


def parse_experience(exp_str: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Parse an experience string into (min_years, max_years).
    Returns (None, None) if experience is not specified.
    """
    if not exp_str or not exp_str.strip():
        return None, None
    s = exp_str.lower().strip()

    # Keywords for freshers / interns / trainees
    if re.search(r'\b(fresher|intern|internship|trainee)\b', s):
        return 0.0, 1.0

    # Range like '0 - 2 years', '1 to 2 yrs', '0.5 - 3'
    range_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)', s)
    if range_match:
        return float(range_match.group(1)), float(range_match.group(2))

    # Single with plus like '2+ years', '5+ yrs'
    plus_match = re.search(r'(\d+(?:\.\d+)?)\s*\+', s)
    if plus_match:
        val = float(plus_match.group(1))
        return val, 99.0

    # Single number like '1 year', '2 yrs'
    single_match = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:year|yr)s?\b', s)
    if single_match:
        val = float(single_match.group(1))
        return val, val

    return None, None


def is_experience_eligible(exp_str: str, min_allowed: float = 0.0, max_allowed: float = 2.0) -> Tuple[bool, str]:
    """
    Check if the required experience falls within [min_allowed, max_allowed] years.
    Returns (is_eligible, reason).
    """
    min_e, max_e = parse_experience(exp_str)
    if min_e is None:
        # Not specified in the card
        return True, "Experience not specified"

    if min_e > max_allowed:
        return False, f"Min experience required ({min_e:g} yrs) exceeds limit ({max_allowed:g} yrs)"

    if max_e is not None and max_e > max_allowed:
        # If minimum required is within entry level (<= 1 yr) and max is at most 3 yrs,
        # it is commonly phrased as '0-3 yrs' or '1-3 yrs' for junior positions open to 0-2 yrs
        if min_e <= 1.0 and max_e <= 3.0:
            return True, f"Junior / entry-level role ({min_e:g}-{max_e:g} yrs)"
        return False, f"Max experience required ({max_e:g} yrs) exceeds limit ({max_allowed:g} yrs)"

    return True, f"Matches 0-{max_allowed:g} yrs ({min_e:g}-{max_e:g} yrs)"


@dataclass
class ScrapeResult:
    """Result of a scraping session."""
    platform: str
    jobs_found: int = 0
    jobs_new: int = 0
    jobs_duplicate: int = 0
    errors: list = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str = ""
    success: bool = True

    def finish(self):
        """Mark the scrape as complete."""
        self.completed_at = datetime.now().isoformat()
