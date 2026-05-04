"""Data migration from JSON files to SQLite database."""

import json
import logging
from pathlib import Path
from datetime import datetime

from services.db import get_cursor, get_connection
from services.job_repository import import_from_json, JOBS_DIR
from services.social_account_repository import import_from_dict as import_account
from services.upload_record_repository import import_from_dict as import_record

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent.parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
BACKUPS_DIR = DATA_DIR / "backups"
MIGRATION_LOG = DATA_DIR / "migration.log"

ACCOUNTS_FILE = ROOT_DIR / "config" / "social_upload_accounts.json"
UPLOAD_RECORDS_FILE = ROOT_DIR / "logs" / "social_upload" / "upload_records.json"


def ensure_backup_dir() -> Path:
    """Ensure backup directory exists."""
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUPS_DIR


def log_migration(action: str, details: str):
    """Log migration action."""
    timestamp = datetime.now().isoformat()
    message = f"[{timestamp}] {action}: {details}"
    logger.info(message)
    try:
        with open(MIGRATION_LOG, "a", encoding="utf-8") as f:
            f.write(message + "\n")
    except Exception as e:
        logger.warning(f"Failed to write migration log: {e}")


def is_jobs_table_empty() -> bool:
    """Check if jobs table is empty."""
    with get_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as count FROM jobs")
        row = cursor.fetchone()
        return row["count"] == 0


def is_social_accounts_table_empty() -> bool:
    """Check if social_accounts table is empty."""
    with get_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as count FROM social_accounts")
        row = cursor.fetchone()
        return row["count"] == 0


def is_upload_records_table_empty() -> bool:
    """Check if upload_records table is empty."""
    with get_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as count FROM upload_records")
        row = cursor.fetchone()
        return row["count"] == 0


def get_imported_job_ids() -> set:
    """Get set of job IDs that have been imported from JSON."""
    with get_cursor() as cursor:
        cursor.execute("SELECT id FROM jobs")
        return {row["id"] for row in cursor.fetchall()}


def get_imported_account_ids() -> set:
    """Get set of account IDs that have been imported from JSON."""
    with get_cursor() as cursor:
        cursor.execute("SELECT id FROM social_accounts")
        return {row["id"] for row in cursor.fetchall()}


def migrate_jobs_from_json() -> int:
    """Migrate jobs from old job.json files to database.
    
    Returns:
        Number of jobs imported.
    """
    imported_ids = get_imported_job_ids()
    imported_count = 0
    
    if not JOBS_DIR.exists():
        logger.info(f"Jobs directory {JOBS_DIR} does not exist, nothing to migrate")
        return 0
    
    for job_dir in JOBS_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        
        job_file = job_dir / "job.json"
        if not job_file.exists():
            continue
        
        try:
            job_data = json.loads(job_file.read_text(encoding="utf-8"))
            job_id = job_data.get("id")
            
            if not job_id:
                logger.warning(f"Job in {job_dir.name} has no ID, skipping")
                continue
            
            if job_id in imported_ids:
                logger.debug(f"Job {job_id} already imported, skipping")
                continue
            
            import_from_json(job_id, job_data)
            imported_count += 1
            log_migration("IMPORT_JOB", f"Imported {job_id} from {job_file}")
            
        except Exception as e:
            logger.error(f"Failed to import job from {job_dir.name}: {e}")
            log_migration("IMPORT_JOB_ERROR", f"Failed to import {job_dir.name}: {e}")
    
    logger.info(f"Jobs migration complete: imported {imported_count} jobs")
    return imported_count


def migrate_social_accounts_from_json() -> int:
    """Migrate social accounts from JSON file to database.
    
    Returns:
        Number of accounts imported.
    """
    if not ACCOUNTS_FILE.exists():
        logger.info(f"Accounts file {ACCOUNTS_FILE} does not exist, nothing to migrate")
        return 0
    
    try:
        data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
        accounts = data.get("accounts", [])
    except Exception as e:
        logger.error(f"Failed to read accounts file: {e}")
        return 0
    
    imported_ids = get_imported_account_ids()
    imported_count = 0
    for acc in accounts:
        try:
            if acc.get("id") in imported_ids:
                continue
            import_account(acc)
            imported_count += 1
            log_migration("IMPORT_ACCOUNT", f"Imported {acc.get('id')} from JSON")
        except Exception as e:
            logger.error(f"Failed to import account {acc.get('id')}: {e}")
    
    logger.info(f"Social accounts migration complete: imported {imported_count} accounts")
    return imported_count


def migrate_upload_records_from_json() -> int:
    """Migrate upload records from JSON file to database.
    
    Returns:
        Number of records imported.
    """
    if not UPLOAD_RECORDS_FILE.exists():
        logger.info(f"Upload records file {UPLOAD_RECORDS_FILE} does not exist, nothing to migrate")
        return 0
    
    try:
        data = json.loads(UPLOAD_RECORDS_FILE.read_text(encoding="utf-8"))
        records = data.get("records", [])
    except Exception as e:
        logger.error(f"Failed to read upload records file: {e}")
        return 0
    
    with get_cursor() as cursor:
        cursor.execute("SELECT id FROM upload_records")
        imported_ids = {row["id"] for row in cursor.fetchall()}

    imported_count = 0
    for rec in records:
        try:
            if rec.get("id") in imported_ids:
                continue
            import_record(rec)
            imported_count += 1
        except Exception as e:
            logger.error(f"Failed to import record {rec.get('id')}: {e}")
    
    logger.info(f"Upload records migration complete: imported {imported_count} records")
    return imported_count


def run_all_migrations():
    """Run all data migrations."""
    logger.info("Starting data migrations...")
    
    jobs_imported = migrate_jobs_from_json()
    accounts_imported = migrate_social_accounts_from_json()
    records_imported = migrate_upload_records_from_json()
    
    log_migration("MIGRATION_COMPLETE", 
        f"Imported: {jobs_imported} jobs, {accounts_imported} accounts, {records_imported} records")
    
    logger.info("Data migrations complete")
