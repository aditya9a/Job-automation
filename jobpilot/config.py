"""
Configuration loader for JobPilot.
Loads profile, platform configs, and environment variables.
"""

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def load_yaml(filepath: Path) -> dict:
    """Load a YAML configuration file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_profile() -> dict:
    """Load user profile configuration."""
    return load_yaml(CONFIG_DIR / "profile.yaml")


def get_platforms() -> dict:
    """Load platform-specific configuration."""
    return load_yaml(CONFIG_DIR / "platforms.yaml")


def get_env(key: str, default: str = None) -> str:
    """Get an environment variable with optional default."""
    return os.getenv(key, default)


# Frequently accessed config values
class Settings:
    """Central settings object."""

    def __init__(self):
        self._profile = None
        self._platforms = None

    @property
    def profile(self) -> dict:
        if self._profile is None:
            self._profile = get_profile()
        return self._profile

    @property
    def platforms(self) -> dict:
        if self._platforms is None:
            self._platforms = get_platforms()
        return self._platforms

    @property
    def gemini_api_key(self) -> str:
        return get_env("GEMINI_API_KEY", "")

    @property
    def linkedin_email(self) -> str:
        return get_env("LINKEDIN_EMAIL", "")

    @property
    def linkedin_password(self) -> str:
        return get_env("LINKEDIN_PASSWORD", "")

    @property
    def db_path(self) -> Path:
        return DATA_DIR / "jobpilot.db"

    @property
    def dashboard_port(self) -> int:
        return int(get_env("DASHBOARD_PORT", "5000"))

    @property
    def dashboard_host(self) -> str:
        return get_env("DASHBOARD_HOST", "127.0.0.1")

    @property
    def scrape_delay_min(self) -> int:
        return int(get_env("SCRAPE_DELAY_MIN", "2"))

    @property
    def scrape_delay_max(self) -> int:
        return int(get_env("SCRAPE_DELAY_MAX", "5"))

    @property
    def max_jobs_per_platform(self) -> int:
        return int(get_env("MAX_JOBS_PER_PLATFORM", "50"))

    @property
    def user_roles(self) -> list:
        return self.profile.get("preferences", {}).get("roles", [])

    @property
    def user_skills(self) -> list:
        return self.profile.get("preferences", {}).get("skills", [])

    @property
    def user_locations(self) -> list:
        return self.profile.get("preferences", {}).get("locations", [])

    @property
    def exclude_keywords(self) -> list:
        return self.profile.get("preferences", {}).get("exclude_keywords", [])

    @property
    def min_match_score(self) -> int:
        return self.profile.get("preferences", {}).get("min_match_score", 50)

    @property
    def min_experience_years(self) -> float:
        return float(self.profile.get("preferences", {}).get("min_experience_years", 0))

    @property
    def max_experience_years(self) -> float:
        return float(self.profile.get("preferences", {}).get("max_experience_years", 2))

    @property
    def resume_summary(self) -> str:
        return self.profile.get("resume", {}).get("summary", "")

    def reload(self):
        """Force reload all configurations."""
        self._profile = None
        self._platforms = None


# Singleton settings instance
settings = Settings()
