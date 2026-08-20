from sqlmodel import SQLModel, Field
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, DateTime, ForeignKey, Index

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

class Endpoint(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
    sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    url: str
    interval_seconds: int = 60
    is_active: bool = True
    next_check_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), nullable=False)
    )

    __table_args__ = (
        Index("ix_endpoint_due", "is_active", "next_check_at"),
    )


class CheckResult(SQLModel, table = True):
    id: int | None = Field(default=None, primary_key=True)
    endpoint_id: int = Field(
    sa_column=Column(Integer, ForeignKey("endpoint.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    checked_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    status_code: int | None #200, 503, or NULL when no HTTP response
    error: str | None #timeout, dns_failure, connection_refused, or NULL if success
    response_time_ms: int | None #NULL if failure


    



