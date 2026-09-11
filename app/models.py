from sqlmodel import SQLModel, Field
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, DateTime, ForeignKey, Index, desc
from enum import Enum
from urllib.parse import urlsplit
from pydantic import field_validator

def validate_check_url(value: str) -> str:
    value = value.strip()
    parts = urlsplit(value)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or any(ch.isspace() for ch in value)
        or len(value) > 2048
    ):
        raise ValueError("must be an http:// or https:// URL with a host")
    return value

class AlertChannel(str, Enum):
    EMAIL = "email"
    WEBHOOK = "webhook"

class UserBase(SQLModel):
    email: str = Field(unique = True, index = True)

class UserCreate(UserBase):
    password: str

class UserRead(UserBase):
    id: int
    created_at: datetime

class User(UserBase, table = True):
    id: int | None = Field(default = None, primary_key = True)
    hashed_password: str
    created_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), nullable=False),
    default_factory=lambda: datetime.now(timezone.utc),
)

class EndpointBase(SQLModel):
    url: str
    interval_seconds: int = 60

class EndpointUpdate(SQLModel):
    interval_seconds: int | None = Field(default=None, ge=10, le=86400)
    is_active: bool | None = None
    url: str | None = None
    
    @field_validator("url")
    @classmethod
    def check_url(cls, value: str | None) -> str | None:
        return None if value is None else validate_check_url(value)
    
class EndpointRead(EndpointBase):
    id: int 
    is_active: bool
    next_check_at: datetime
    latest_status_code: int | None = None
    latest_checked_at: datetime | None = None


class EndpointCreate(EndpointBase):
    interval_seconds: int = Field(default=60, ge=10, le=86400)
    @field_validator("url")
    @classmethod
    def check_url(cls, value: str) -> str:
        return validate_check_url(value)

class Endpoint(EndpointBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
    sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    is_active: bool = True
    next_check_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    __table_args__ = (
        Index("ix_endpoint_due", "is_active", "next_check_at"),
    )


class CheckResult(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    endpoint_id: int = Field(
        sa_column=Column(Integer, ForeignKey("endpoint.id", ondelete="CASCADE"), nullable=False)
    )
    checked_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    status_code: int | None      # 200, 503, or NULL when no HTTP response
    error: str | None            # timeout, dns_failure, connection_refused, or NULL if success
    response_time_ms: int | None # NULL if failure

    __table_args__ = (
        Index("ix_checkresult_latest", "endpoint_id", desc("checked_at")),
    )

class AlertConfigCreate(SQLModel):
    threshold: int = Field(default = 3)
    channel: AlertChannel
    target: str
    is_active: bool = Field(default = True)

class AlertConfigRead(AlertConfigCreate):
    id: int | None
    endpoint_id: int = Field(
        sa_column=Column(Integer, ForeignKey("endpoint.id", ondelete="CASCADE"), nullable=False, index=True)
    )

class AlertConfigUpdate(SQLModel):
    threshold: int | None = None
    channel: AlertChannel | None = None
    target: str | None = None
    is_active: bool | None = None

class AlertConfig(AlertConfigCreate, table=True):
    id: int | None = Field(default = None, primary_key=True)
    user_id: int = Field(
    sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    endpoint_id: int = Field(
        sa_column=Column(Integer, ForeignKey("endpoint.id", ondelete="CASCADE"), nullable=False, index=True)
    )

class AlertState(SQLModel, table=True):
    id: int | None = Field(default = None, primary_key=True)
    config_id: int = Field(
        sa_column=Column(Integer, ForeignKey("alertconfig.id", ondelete="CASCADE"), nullable=False, index=True, unique = True)
        )
    current_streak: int = Field(default=0)
    alert_sent: bool = Field(default=False)
    last_alert_at: datetime | None = Field(
    default=None,
    sa_column=Column(DateTime(timezone=True), nullable=True)
    )   
