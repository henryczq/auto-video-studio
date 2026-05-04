"""Social accounts - now backed by SQLite database."""

from typing import Optional, List

from services.social_account_repository import (
    get_all_accounts as db_list_accounts,
    get_account as db_get_account,
    create_account as db_create_account,
    update_account as db_update_account,
    delete_account as db_delete_account,
    account_exists as db_account_exists,
)


def load_accounts() -> List[dict]:
    """Load all accounts from database."""
    return db_list_accounts()


def save_accounts(accounts: list) -> list:
    """Save accounts list (for compatibility, just returns the list)."""
    return accounts


def add_account(platform: str, account: str, label: str = "") -> dict:
    """Add a new social account."""
    return db_create_account(platform, account, label)


def update_account(account_id: str, updates: dict) -> dict:
    """Update an account."""
    result = db_update_account(account_id, updates)
    if result is None:
        raise ValueError(f"账号不存在: {account_id}")
    return result


def delete_account(account_id: str) -> bool:
    """Delete an account."""
    result = db_delete_account(account_id)
    if not result:
        raise ValueError(f"账号不存在: {account_id}")
    return result


def get_account(account_id: str) -> Optional[dict]:
    """Get an account by ID."""
    return db_get_account(account_id)


def list_accounts() -> List[dict]:
    """List all accounts."""
    return db_list_accounts()
