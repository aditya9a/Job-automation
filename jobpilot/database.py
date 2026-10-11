"""
Database layer for JobPilot.
Uses SQLite for local storage of jobs, applications, and scrape history.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .config import settings
from .models import Job, JobStatus


class Database:
    """SQLite database manager for job data."""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or settings.db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        """Create tables if they don't exist."""
        conn = self._get_connection()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    url TEXT NOT NULL,
                    location TEXT DEFAULT '',
                    salary TEXT DEFAULT '',
                    experience TEXT DEFAULT '',
                    job_type TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    skills TEXT DEFAULT '',
                    posted_date TEXT DEFAULT '',
                    external_id TEXT DEFAULT '',
                    status TEXT DEFAULT 'new',
                    match_score REAL DEFAULT 0.0,
                    match_reason TEXT DEFAULT '',
                    scraped_at TEXT NOT NULL,
                    applied_at TEXT DEFAULT '',
                    generated_cover_letter TEXT DEFAULT '',
                    generated_answers TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(platform, url)
                );

                CREATE TABLE IF NOT EXISTS scrape_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    jobs_found INTEGER DEFAULT 0,
                    jobs_new INTEGER DEFAULT 0,
                    jobs_duplicate INTEGER DEFAULT 0,
                    errors TEXT DEFAULT '',
                    started_at TEXT NOT NULL,
                    completed_at TEXT DEFAULT '',
                    success INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS application_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT DEFAULT '',
                    timestamp TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (job_id) REFERENCES jobs(id)
                );

                -- Indexes for common queries
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_platform ON jobs(platform);
                CREATE INDEX IF NOT EXISTS idx_jobs_match_score ON jobs(match_score DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at ON jobs(scraped_at DESC);
            """)
            conn.commit()
        finally:
            conn.close()

    # ─── Job CRUD ────────────────────────────────────────────

    def add_job(self, job: Job) -> Optional[int]:
        """
        Add a job to the database. Returns the job ID if inserted,
        None if it was a duplicate.
        """
        conn = self._get_connection()
        try:
            data = job.to_dict()
            cursor = conn.execute("""
                INSERT OR IGNORE INTO jobs 
                (title, company, platform, url, location, salary, experience,
                 job_type, description, skills, posted_date, external_id,
                 status, match_score, match_reason, scraped_at, applied_at,
                 generated_cover_letter, generated_answers)
                VALUES 
                (:title, :company, :platform, :url, :location, :salary, :experience,
                 :job_type, :description, :skills, :posted_date, :external_id,
                 :status, :match_score, :match_reason, :scraped_at, :applied_at,
                 :generated_cover_letter, :generated_answers)
            """, data)
            conn.commit()

            if cursor.rowcount > 0:
                return cursor.lastrowid
            return None  # Duplicate
        finally:
            conn.close()

    def add_jobs(self, jobs: List[Job]) -> tuple:
        """Add multiple jobs. Returns (inserted_count, duplicate_count)."""
        inserted = 0
        duplicates = 0
        for job in jobs:
            result = self.add_job(job)
            if result is not None:
                inserted += 1
            else:
                duplicates += 1
        return inserted, duplicates

    def get_job(self, job_id: int) -> Optional[Job]:
        """Get a single job by ID."""
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row:
                return Job.from_dict(dict(row))
            return None
        finally:
            conn.close()

    def get_jobs(
        self,
        status: str = None,
        platform: str = None,
        min_score: float = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "match_score DESC, scraped_at DESC"
    ) -> List[Job]:
        """Get jobs with optional filters."""
        conn = self._get_connection()
        try:
            query = "SELECT * FROM jobs WHERE 1=1"
            params = []

            if status:
                query += " AND status = ?"
                params.append(status)
            if platform:
                query += " AND platform = ?"
                params.append(platform)
            if min_score is not None:
                query += " AND match_score >= ?"
                params.append(min_score)

            query += f" ORDER BY {order_by} LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            return [Job.from_dict(dict(row)) for row in rows]
        finally:
            conn.close()

    def update_job_status(self, job_id: int, status: str, **extra_fields):
        """Update a job's status and optionally other fields."""
        conn = self._get_connection()
        try:
            updates = ["status = ?", "updated_at = ?"]
            params = [status, datetime.now().isoformat()]

            for key, value in extra_fields.items():
                updates.append(f"{key} = ?")
                params.append(value)

            params.append(job_id)
            conn.execute(
                f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?",
                params
            )
            conn.commit()
        finally:
            conn.close()

    def update_match_score(self, job_id: int, score: float, reason: str = ""):
        """Update a job's AI match score."""
        self.update_job_status(
            job_id,
            JobStatus.MATCHED.value,
            match_score=score,
            match_reason=reason
        )

    def search_jobs(self, query: str, limit: int = 50) -> List[Job]:
        """Full-text search across job title, company, and description."""
        conn = self._get_connection()
        try:
            pattern = f"%{query}%"
            rows = conn.execute("""
                SELECT * FROM jobs 
                WHERE title LIKE ? OR company LIKE ? OR description LIKE ?
                ORDER BY match_score DESC, scraped_at DESC
                LIMIT ?
            """, (pattern, pattern, pattern, limit)).fetchall()
            return [Job.from_dict(dict(row)) for row in rows]
        finally:
            conn.close()

    # ─── Statistics ──────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get summary statistics."""
        conn = self._get_connection()
        try:
            stats = {}

            # Total jobs
            row = conn.execute("SELECT COUNT(*) as total FROM jobs").fetchone()
            stats["total_jobs"] = row["total"]

            # Jobs by status
            rows = conn.execute(
                "SELECT status, COUNT(*) as count FROM jobs GROUP BY status"
            ).fetchall()
            stats["by_status"] = {row["status"]: row["count"] for row in rows}

            # Jobs by platform
            rows = conn.execute(
                "SELECT platform, COUNT(*) as count FROM jobs GROUP BY platform"
            ).fetchall()
            stats["by_platform"] = {row["platform"]: row["count"] for row in rows}

            # Today's jobs
            today = datetime.now().strftime("%Y-%m-%d")
            row = conn.execute(
                "SELECT COUNT(*) as count FROM jobs WHERE scraped_at LIKE ?",
                (f"{today}%",)
            ).fetchone()
            stats["today_new"] = row["count"]

            # Average match score
            row = conn.execute(
                "SELECT AVG(match_score) as avg_score FROM jobs WHERE match_score > 0"
            ).fetchone()
            stats["avg_match_score"] = round(row["avg_score"] or 0, 1)

            return stats
        finally:
            conn.close()

    # ─── Scrape History ──────────────────────────────────────

    def log_scrape(self, platform: str, jobs_found: int, jobs_new: int,
                   jobs_duplicate: int, errors: list, started_at: str,
                   completed_at: str, success: bool):
        """Log a scraping session."""
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO scrape_history
                (platform, jobs_found, jobs_new, jobs_duplicate, errors,
                 started_at, completed_at, success)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                platform, jobs_found, jobs_new, jobs_duplicate,
                "\n".join(errors), started_at, completed_at, int(success)
            ))
            conn.commit()
        finally:
            conn.close()

    def get_scrape_history(self, limit: int = 20) -> list:
        """Get recent scrape history."""
        conn = self._get_connection()
        try:
            rows = conn.execute("""
                SELECT * FROM scrape_history 
                ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    # ─── Application Log ────────────────────────────────────

    def log_application_action(self, job_id: int, action: str, details: str = ""):
        """Log an action taken on a job application."""
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO application_log (job_id, action, details)
                VALUES (?, ?, ?)
            """, (job_id, action, details))
            conn.commit()
        finally:
            conn.close()

    def log_application(self, job_id: int, action: str, notes: str = "", details: str = ""):
        """Alias for log_application_action for compatibility."""
        return self.log_application_action(job_id, action, details=notes or details)


# Singleton database instance
db = Database()

