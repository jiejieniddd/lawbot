from __future__ import annotations

import re

ACCOUNT_MIN_LEN = 3
ACCOUNT_MAX_LEN = 32
ACCOUNT_PATTERN = re.compile(r"^[a-z0-9_]+$")
ACCOUNT_RULE_MSG = "账号须为 3–32 位字母、数字或下划线"


def normalize_account(value: str) -> str:
    return (value or "").lower().strip()


def validate_new_account(value: str) -> str:
    """Normalize and validate a new login account (register / admin create)."""
    account = normalize_account(value)
    if (
        len(account) < ACCOUNT_MIN_LEN
        or len(account) > ACCOUNT_MAX_LEN
        or not ACCOUNT_PATTERN.fullmatch(account)
    ):
        raise ValueError(ACCOUNT_RULE_MSG)
    return account
