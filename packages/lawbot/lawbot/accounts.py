from __future__ import annotations

import re

ACCOUNT_MIN_LEN = 3
ACCOUNT_MAX_LEN = 32
ACCOUNT_PATTERN = re.compile(r"^[a-z0-9_]+$")
ACCOUNT_RULE_MSG = "账号须为 3–32 位字母、数字或下划线"

EMAIL_MAX_LEN = 255
EMAIL_RULE_MSG = "请输入有效邮箱"
EMAIL_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9._%+\-]{0,62}[a-z0-9])?@"
    r"[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?)+$"
)


def normalize_account(value: str) -> str:
    return (value or "").lower().strip()


def validate_new_account(value: str) -> str:
    """Normalize and validate a staff login account (admin create)."""
    account = normalize_account(value)
    if (
        len(account) < ACCOUNT_MIN_LEN
        or len(account) > ACCOUNT_MAX_LEN
        or not ACCOUNT_PATTERN.fullmatch(account)
    ):
        raise ValueError(ACCOUNT_RULE_MSG)
    return account


def validate_email_account(value: str) -> str:
    """Normalize and validate a C-end login email."""
    email = normalize_account(value)
    if len(email) < ACCOUNT_MIN_LEN or len(email) > EMAIL_MAX_LEN or not EMAIL_PATTERN.fullmatch(email):
        raise ValueError(EMAIL_RULE_MSG)
    return email
