from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from database import Base


def utc_now():
    """Generates a canonical timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class UserRole:
    LAWYER = "LAWYER"
    JUDGE = "JUDGE"
    CLIENT = "CLIENT"
    ADMIN = "ADMIN"

    ALL = [LAWYER, JUDGE, CLIENT, ADMIN]


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # LAWYER, JUDGE, CLIENT, ADMIN
    created_at = Column(DateTime, default=utc_now)


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    case_number = Column(String, nullable=True)
    uploaded_by = Column(String, nullable=False)
    file_hash = Column(String, nullable=True)
    version = Column(Integer, default=1)
    blockchain_tx_hash = Column(String, nullable=True)
    blockchain_status = Column(String, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now)

    versions = relationship(
        "DocumentVersion",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number.asc()",
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False, default=0)
    file_type = Column(String, nullable=True)
    file_hash = Column(String, nullable=False, index=True)
    uploaded_by = Column(String, nullable=False)
    uploader_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    blockchain_tx_hash = Column(String, nullable=True)
    blockchain_status = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_version"),
    )

    document = relationship("Document", back_populates="versions")
    ai_metadata = relationship("DocumentVersionMetadata", back_populates="version", uselist=False, cascade="all, delete-orphan")
    ai_summary = relationship("DocumentVersionSummary", back_populates="version", uselist=False, cascade="all, delete-orphan")


class DocumentVersionMetadata(Base):
    __tablename__ = "document_version_metadata"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id = Column(Integer, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    version_number = Column(Integer, nullable=False)
    source_hash = Column(String, nullable=False, index=True)

    status = Column(String, nullable=False, default="NOT_ANALYZED")  # NOT_ANALYZED, COMPLETED, FAILED, EXTRACTION_UNAVAILABLE
    document_type = Column(String, nullable=True)
    case_number = Column(String, nullable=True)
    court = Column(String, nullable=True)
    jurisdiction = Column(String, nullable=True)
    subject = Column(String, nullable=True)

    parties_json = Column(String, nullable=True)
    dates_json = Column(String, nullable=True)
    keywords_json = Column(String, nullable=True)
    confidence_json = Column(String, nullable=True)

    ai_provider = Column(String, nullable=True)
    ai_model = Column(String, nullable=True)
    extraction_duration_ms = Column(Integer, nullable=True)
    error_message = Column(String, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("version_id", name="uq_version_metadata"),
    )

    version = relationship("DocumentVersion", back_populates="ai_metadata")
    document = relationship("Document")


class DocumentVersionSummary(Base):
    __tablename__ = "document_version_summaries"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id = Column(Integer, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    version_number = Column(Integer, nullable=False)
    source_hash = Column(String, nullable=False, index=True)

    status = Column(String, nullable=False, default="NOT_GENERATED")  # NOT_GENERATED, COMPLETED, FAILED, EXTRACTION_UNAVAILABLE, EXTRACTION_LIMIT_EXCEEDED
    summary = Column(Text, nullable=True)
    key_facts_json = Column(Text, nullable=True)
    legal_issues_json = Column(Text, nullable=True)
    important_points_json = Column(Text, nullable=True)

    ai_provider = Column(String, nullable=True)
    ai_model = Column(String, nullable=True)
    generation_duration_ms = Column(Integer, nullable=True)
    error_message = Column(String, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("version_id", name="uq_version_summary"),
    )

    version = relationship("DocumentVersion", back_populates="ai_summary")
    document = relationship("Document")


class DocumentShare(Base):
    __tablename__ = "document_shares"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    shared_with_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    shared_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_name = Column(String, nullable=True)
    actor_email = Column(String, nullable=True)
    actor_role = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)

    action = Column(String, nullable=False, index=True)
    resource_type = Column(String, nullable=True, index=True)
    resource_id = Column(String, nullable=True)

    document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    document_title = Column(String, nullable=True)
    version_id = Column(Integer, ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True)
    version_number = Column(Integer, nullable=True)

    result = Column(String, nullable=False, index=True)
    reason = Column(String, nullable=True)
    metadata_json = Column(String, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)