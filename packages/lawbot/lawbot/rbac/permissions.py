from __future__ import annotations

from typing import TypedDict


class PermissionDef(TypedDict):
    code: str
    name: str
    module: str
    description: str


class RoleDef(TypedDict):
    code: str
    name: str
    description: str
    is_system: bool


PERMISSION_DEFS: list[PermissionDef] = [
    {"code": "user:list", "name": "查看用户", "module": "user", "description": "列出 C 端用户"},
    {"code": "user:create", "name": "创建用户", "module": "user", "description": "创建 C 端用户"},
    {"code": "user:disable", "name": "禁用用户", "module": "user", "description": "启用/禁用用户"},
    {"code": "admin:manage", "name": "管理管理员", "module": "admin", "description": "创建/管理普通管理员"},
    {"code": "role:manage", "name": "角色管理", "module": "role", "description": "管理角色与权限"},
    {"code": "knowledge:read", "name": "知识库只读", "module": "knowledge", "description": "查看文档与试检索"},
    {"code": "knowledge:import", "name": "知识导入", "module": "knowledge", "description": "触发知识导入任务"},
    {"code": "provider:manage", "name": "模型供应商", "module": "provider", "description": "管理模型供应商"},
    {"code": "audit:read", "name": "审计只读", "module": "audit", "description": "查看会话审计"},
    {"code": "stats:read", "name": "统计只读", "module": "stats", "description": "查看仪表盘统计"},
    {"code": "settings:read", "name": "系统设置", "module": "settings", "description": "查看系统设置"},
    {"code": "settings:write", "name": "修改系统设置", "module": "settings", "description": "修改系统设置"},
]

ALL_PERMISSION_CODES: tuple[str, ...] = tuple(p["code"] for p in PERMISSION_DEFS)

ROLE_DEFS: list[RoleDef] = [
    {
        "code": "super_admin",
        "name": "超级管理员",
        "description": "拥有全部权限，不可删除",
        "is_system": True,
    },
    {
        "code": "admin",
        "name": "普通管理员",
        "description": "后台管理（不含角色管理）",
        "is_system": True,
    },
    {
        "code": "operator",
        "name": "运营",
        "description": "审计与知识库只读",
        "is_system": True,
    },
    {
        "code": "user",
        "name": "普通用户",
        "description": "C 端用户，无后台权限",
        "is_system": True,
    },
]

ROLE_PERMISSION_CODES: dict[str, tuple[str, ...]] = {
    "super_admin": ALL_PERMISSION_CODES,
    "admin": tuple(
        c for c in ALL_PERMISSION_CODES if c not in {"role:manage", "settings:write"}
    ),
    "operator": ("stats:read", "audit:read", "knowledge:read"),
    "user": (),
}
