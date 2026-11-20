"""Minimal user preference hints (province / case domain)."""

from __future__ import annotations

from typing import Any

PROVINCE_KEYWORDS: tuple[str, ...] = (
    "北京",
    "上海",
    "天津",
    "重庆",
    "河北",
    "山西",
    "辽宁",
    "吉林",
    "黑龙江",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "山东",
    "河南",
    "湖北",
    "湖南",
    "广东",
    "海南",
    "四川",
    "贵州",
    "云南",
    "陕西",
    "甘肃",
    "青海",
    "台湾",
    "内蒙古",
    "广西",
    "西藏",
    "宁夏",
    "新疆",
    "香港",
    "澳门",
)

LOCAL_LAW_NOTE = "当前库不含该地方法规，地方规定请另行核实。"


def extract_province(text: str) -> str | None:
    raw = text or ""
    for name in PROVINCE_KEYWORDS:
        if name in raw:
            return name
    return None


def upsert_user_preference(
    db: Any,
    *,
    user_id: Any,
    province: str | None = None,
    case_domain: str | None = None,
) -> Any:
    from lawbot.db.models import UserPreference

    row = db.get(UserPreference, user_id)
    if row is None:
        row = UserPreference(user_id=user_id)
        db.add(row)
    if province:
        row.province = province
    if case_domain and case_domain != "general":
        row.case_domain = case_domain
    db.commit()
    db.refresh(row)
    return row


def load_user_preference(db: Any, user_id: Any) -> Any | None:
    from lawbot.db.models import UserPreference

    return db.get(UserPreference, user_id)
