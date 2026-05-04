"""Social account repository for social_accounts table CRUD operations."""

import datetime
from typing import Optional, List

from services.db import get_cursor


ACCOUNT_COLUMNS = {
    "id",
    "platform",
    "account",
    "label",
    "last_check_status",
    "last_check_at",
    "last_error",
    "cookie_path",
    "profile_dir",
    "created_at",
    "updated_at",
}
ACCOUNT_MUTABLE_COLUMNS = ACCOUNT_COLUMNS - {"id", "created_at"}


def get_all_accounts() -> List[dict]:
    """Get all social accounts."""
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM social_accounts ORDER BY platform, account")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_account(account_id: str) -> Optional[dict]:
    """Get a single account by ID."""
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM social_accounts WHERE id = ?", (account_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def create_account(
    platform: str,
    account: str,
    label: str = "",
    cookie_path: str = None,
    profile_dir: str = None,
) -> dict:
    """Create a new social account."""
    account_id = f"{platform}_{account}"
    now = datetime.datetime.now().isoformat()
    
    account_data = {
        "id": account_id,
        "platform": platform,
        "account": account,
        "label": label or "",
        "last_check_status": "unknown",
        "last_check_at": None,
        "last_error": "",
        "cookie_path": cookie_path or "",
        "profile_dir": profile_dir or "",
        "created_at": now,
        "updated_at": now,
    }
    
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO social_accounts (
                id, platform, account, label, last_check_status,
                last_check_at, last_error, cookie_path, profile_dir,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            account_data["id"],
            account_data["platform"],
            account_data["account"],
            account_data["label"],
            account_data["last_check_status"],
            account_data["last_check_at"],
            account_data["last_error"],
            account_data["cookie_path"],
            account_data["profile_dir"],
            account_data["created_at"],
            account_data["updated_at"],
        ))
    
    return account_data


def update_account(account_id: str, updates: dict) -> Optional[dict]:
    """Update an account with given fields."""
    updates = {k: v for k, v in updates.items() if k in ACCOUNT_MUTABLE_COLUMNS}
    if not updates:
        return get_account(account_id)
    updates["updated_at"] = datetime.datetime.now().isoformat()
    
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [account_id]
    
    with get_cursor() as cursor:
        cursor.execute(f"UPDATE social_accounts SET {set_clause} WHERE id = ?", values)
        if cursor.rowcount == 0:
            return None
    
    return get_account(account_id)


def delete_account(account_id: str) -> bool:
    """Delete an account."""
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM social_accounts WHERE id = ?", (account_id,))
        return cursor.rowcount > 0


def account_exists(account_id: str) -> bool:
    """Check if an account exists."""
    with get_cursor() as cursor:
        cursor.execute("SELECT 1 FROM social_accounts WHERE id = ?", (account_id,))
        return cursor.fetchone() is not None


def import_from_dict(account_data: dict) -> dict:
    """Import an account from a dict into database."""
    account_data = {k: v for k, v in account_data.items() if k in ACCOUNT_COLUMNS}
    account_data["updated_at"] = datetime.datetime.now().isoformat()
    
    with get_cursor() as cursor:
        columns = ["id", "platform", "account", "label", "last_check_status",
                   "last_check_at", "last_error", "cookie_path", "profile_dir",
                   "created_at", "updated_at"]
        
        values = []
        for col in columns:
            values.append(account_data.get(col, ""))
        
        cursor.execute("""
            INSERT OR REPLACE INTO social_accounts (
                id, platform, account, label, last_check_status,
                last_check_at, last_error, cookie_path, profile_dir,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, values)
    
    return account_data
