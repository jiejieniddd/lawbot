from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from lawbot.accounts import normalize_account, validate_email_account, validate_new_account


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"
    OPERATOR = "operator"


STAFF_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.ADMIN, UserRole.SUPER_ADMIN, UserRole.OPERATOR}
)


def is_staff_role(role: UserRole | str) -> bool:
    try:
        return UserRole(str(role)) in STAFF_ROLES
    except ValueError:
        # Custom RBAC role codes: treat non-user as staff for shell access
        return str(role) != UserRole.USER


def is_super_admin_role(role: UserRole | str) -> bool:
    return str(role) == UserRole.SUPER_ADMIN


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class DocType(StrEnum):
    LAW = "law"
    REGULATION = "regulation"
    FAQ = "faq"


class DocStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Citation(BaseModel):
    law_name: str
    article_no: str
    text: str
    source_id: str
    effective_date: str | None = None
    status: str | None = None
    category: str | None = None
    jurisdiction: str | None = None
    source_url: str | None = None


LEGAL_DISCLAIMER = (
    "本回复仅供参考，不构成正式法律意见。如需正式意见请咨询执业律师。"
    "检索所依据的法规条文来自第三方整理的数据集，非国家官方汇编、非权威发布渠道，"
    "请以全国人大等官方来源为准。"
)


class LLMProviderKind(StrEnum):
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    DASHSCOPE = "dashscope"
    ZHIPU = "zhipu"
    MOONSHOT = "moonshot"
    OPENAI_COMPATIBLE = "openai_compatible"
    OLLAMA = "ollama"


class ImportJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class LLMProviderCreate(BaseModel):
    name: str = Field(max_length=120)
    provider: LLMProviderKind = LLMProviderKind.OPENAI_COMPATIBLE
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str = Field(min_length=1)
    default_model: str = Field(max_length=200)
    priority: int = 100
    enabled: bool = True


class LLMProviderPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    provider: LLMProviderKind | None = None
    base_url: str | None = None
    api_key: str | None = None
    default_model: str | None = Field(default=None, max_length=200)
    priority: int | None = None
    enabled: bool | None = None


class LLMProviderOut(BaseModel):
    id: UUID
    name: str
    provider: str
    base_url: str | None
    default_model: str
    priority: int
    enabled: bool
    api_key_masked: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class KnowledgeImportJobCreate(BaseModel):
    source: str = Field(default="hf:china-effective-laws-regulations", max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)


class KnowledgeImportJobOut(BaseModel):
    id: UUID
    status: str
    source: str
    config: dict[str, Any]
    stats: dict[str, Any]
    error: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ChatEvent(BaseModel):
    type: Literal["token", "citation", "done", "error"]
    data: dict[str, Any]
    request_id: str

    @classmethod
    def token(cls, request_id: str, text: str) -> ChatEvent:
        return cls(type="token", data={"text": text}, request_id=request_id)

    @classmethod
    def citation(cls, request_id: str, citation: Citation) -> ChatEvent:
        return cls(type="citation", data=citation.model_dump(), request_id=request_id)

    @classmethod
    def done(
        cls,
        request_id: str,
        message_id: UUID,
        conversation_id: UUID,
        disclaimer: str = LEGAL_DISCLAIMER,
    ) -> ChatEvent:
        return cls(
            type="done",
            data={
                "message_id": str(message_id),
                "conversation_id": str(conversation_id),
                "disclaimer": disclaimer,
            },
            request_id=request_id,
        )

    @classmethod
    def error(cls, request_id: str, code: str, message: str) -> ChatEvent:
        return cls(type="error", data={"code": code, "message": message}, request_id=request_id)


class TokenPayload(BaseModel):
    sub: str
    role: UserRole
    email: str
    typ: str
    jti: str | None = None


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255, description="登录邮箱")
    password: str = Field(min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)

    @field_validator("email")
    @classmethod
    def _validate_account(cls, v: str) -> str:
        return validate_email_account(v)


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_login_account(cls, v: str) -> str:
        return normalize_account(v)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int



class RoleBrief(BaseModel):
    id: UUID
    code: str
    name: str

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    role: str
    disabled: bool
    created_at: datetime | None = None
    avatar_url: str | None = None
    roles: list[RoleBrief] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=255)
    enabled: bool = True


class RolePatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None


class RoleOut(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    is_system: bool
    enabled: bool
    permission_codes: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class RolePermissionsUpdate(BaseModel):
    permission_codes: list[str] = Field(default_factory=list)


class PermissionOut(BaseModel):
    id: UUID
    code: str
    name: str
    module: str
    description: str | None = None

    model_config = {"from_attributes": True}


class UserRoleAssign(BaseModel):
    role_id: UUID


class AdminCreate(BaseModel):
    email: str = Field(min_length=3, max_length=32, description="登录账号（非邮箱）")
    password: str = Field(min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)
    role_id: UUID | None = None

    @field_validator("email")
    @classmethod
    def _validate_account_admin(cls, v: str) -> str:
        return validate_new_account(v)


class ClientCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255, description="登录邮箱")
    password: str = Field(min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)
    role_id: UUID | None = None

    @field_validator("email")
    @classmethod
    def _validate_account_client(cls, v: str) -> str:
        return validate_email_account(v)


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationOut(BaseModel):
    id: UUID
    title: str
    status: ConversationStatus
    user_id: UUID

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    citations: list[Citation] = Field(default_factory=list)
    request_id: str | None = None

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    conversation_id: UUID
    content: str = Field(min_length=1, max_length=8000)


class UserPatch(BaseModel):
    disabled: bool | None = None
    display_name: str | None = None


class KnowledgeCreate(BaseModel):
    title: str = Field(max_length=300)
    doc_type: DocType = DocType.LAW
    status: DocStatus = DocStatus.DRAFT
    summary: str | None = None
    source_uri: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class KnowledgePatch(BaseModel):
    title: str | None = None
    doc_type: DocType | None = None
    status: DocStatus | None = None
    summary: str | None = None
    source_uri: str | None = None
    meta: dict[str, Any] | None = None


class KnowledgeOut(BaseModel):
    id: UUID
    title: str
    doc_type: DocType
    status: DocStatus
    summary: str | None
    source_uri: str | None
    meta: dict[str, Any]
    created_by: UUID | None
    updated_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class StatsOverview(BaseModel):
    users: int
    end_users: int = 0
    admins: int = 0
    conversations: int
    messages: int
    knowledge_documents: int
