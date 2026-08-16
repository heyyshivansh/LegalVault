import json
import sys
from typing import Any
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from database import SessionLocal
from models import AuditLog, User, Document, DocumentVersion, utc_now


class AuditEventType:
    # Authentication
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"

    # Documents
    DOCUMENT_CREATED = "DOCUMENT_CREATED"
    DOCUMENT_VIEWED = "DOCUMENT_VIEWED"
    DOCUMENT_DOWNLOADED = "DOCUMENT_DOWNLOADED"

    # Version History
    VERSION_CREATED = "VERSION_CREATED"
    VERSION_VIEWED = "VERSION_VIEWED"
    VERSION_DOWNLOADED = "VERSION_DOWNLOADED"
    VERSION_VERIFIED = "VERSION_VERIFIED"
    VERSION_TAMPERED = "VERSION_TAMPERED"

    # Full Document Verification
    DOCUMENT_VERIFIED = "DOCUMENT_VERIFIED"
    DOCUMENT_TAMPERED = "DOCUMENT_TAMPERED"
    BLOCKCHAIN_PROOF_UNAVAILABLE = "BLOCKCHAIN_PROOF_UNAVAILABLE"

    # Sharing
    DOCUMENT_SHARED = "DOCUMENT_SHARED"
    DOCUMENT_SHARE_REVOKED = "DOCUMENT_SHARE_REVOKED"
    SHARED_DOCUMENT_ACCESSED = "SHARED_DOCUMENT_ACCESSED"

    # Security & Access Control
    ACCESS_DENIED = "ACCESS_DENIED"
    ACTION_DENIED = "ACTION_DENIED"

    # AI Analysis
    AI_METADATA_EXTRACTED = "AI_METADATA_EXTRACTED"
    AI_METADATA_EXTRACTION_FAILED = "AI_METADATA_EXTRACTION_FAILED"
    AI_SUMMARY_GENERATED = "AI_SUMMARY_GENERATED"
    AI_SUMMARY_GENERATION_FAILED = "AI_SUMMARY_GENERATION_FAILED"

    # Administration
    VAULT_RESET = "VAULT_RESET"


class AuditResult:
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    VERIFIED = "VERIFIED"
    TAMPERED = "TAMPERED"
    DENIED = "DENIED"
    UNAVAILABLE = "UNAVAILABLE"


class AuditResourceType:
    DOCUMENT = "DOCUMENT"
    VERSION = "VERSION"
    SHARE = "SHARE"
    AUTH = "AUTH"
    SYSTEM = "SYSTEM"


SENSITIVE_KEYS = {
    "password",
    "plain_password",
    "token",
    "access_token",
    "secret",
    "private_key",
    "file_bytes",
    "api_key",
    "gemini_api_key",
    "prompt",
    "raw_text",
    "extracted_text",
    "document_text",
    "summary_prompt",
    "full_summary",
    "full_text",
}


def sanitize_metadata(meta: dict | None) -> dict | None:
    """Removes sensitive keys from audit metadata."""
    if not meta or not isinstance(meta, dict):
        return meta
    sanitized = {}
    for k, v in meta.items():
        if k.lower() not in SENSITIVE_KEYS:
            sanitized[k] = v
    return sanitized


def log_audit_event(
    db: Session | None = None,
    *,
    action: str,
    result: str,
    actor: User | None = None,
    actor_name: str | None = None,
    actor_email: str | None = None,
    actor_role: str | None = None,
    ip_address: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    document: Document | None = None,
    document_id: int | None = None,
    document_title: str | None = None,
    version: DocumentVersion | None = None,
    version_id: int | None = None,
    version_number: int | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    isolated: bool = False,
) -> AuditLog | None:
    """
    Centralized audit logging helper.
    - Captures immutable snapshots of actor, action, resource, version, and result.
    - Supports isolated sub-sessions for persisting security denials before 401/403 exceptions.
    - Prevents sensitive leakage (no passwords or tokens).
    - Catches database errors gracefully to protect core business workflows.
    """
    # 1. Resolve Actor Snapshot
    eff_actor_id = actor.id if actor else None
    eff_actor_name = actor.name if actor else (actor_name or None)
    eff_actor_email = actor.email if actor else (actor_email or None)
    eff_actor_role = actor.role if actor else (actor_role or "ANONYMOUS")

    # 2. Resolve Document / Version Snapshot
    eff_doc_id = document.id if document else document_id
    eff_doc_title = document.filename if document else (document_title or None)

    eff_ver_id = version.id if version else version_id
    eff_ver_num = version.version_number if version else version_number
    if eff_ver_num is None and document and document.version:
        eff_ver_num = document.version

    # 3. Default Resource Type & ID if omitted
    eff_resource_type = resource_type
    if not eff_resource_type:
        if version or version_number:
            eff_resource_type = AuditResourceType.VERSION
        elif document or document_id:
            eff_resource_type = AuditResourceType.DOCUMENT
        elif action in [AuditEventType.LOGIN_SUCCESS, AuditEventType.LOGIN_FAILED, AuditEventType.LOGOUT]:
            eff_resource_type = AuditResourceType.AUTH
        elif action == AuditEventType.VAULT_RESET:
            eff_resource_type = AuditResourceType.SYSTEM
        else:
            eff_resource_type = AuditResourceType.DOCUMENT

    eff_resource_id = resource_id
    if not eff_resource_id:
        if eff_doc_id and eff_ver_num:
            eff_resource_id = f"{eff_doc_id}_v{eff_ver_num}"
        elif eff_doc_id:
            eff_resource_id = str(eff_doc_id)

    # 4. Serialize Sanitized Metadata
    sanitized_meta = sanitize_metadata(metadata)
    metadata_json_str = json.dumps(sanitized_meta) if sanitized_meta else None

    # 5. Construct AuditLog Record
    audit_entry = AuditLog(
        actor_id=eff_actor_id,
        actor_name=eff_actor_name,
        actor_email=eff_actor_email,
        actor_role=eff_actor_role,
        ip_address=ip_address,
        action=action,
        resource_type=eff_resource_type,
        resource_id=eff_resource_id,
        document_id=eff_doc_id,
        document_title=eff_doc_title,
        version_id=eff_ver_id,
        version_number=eff_ver_num,
        result=result,
        reason=reason,
        metadata_json=metadata_json_str,
        created_at=utc_now(),
    )

    # 6. Session Handling & Commit
    if isolated or db is None:
        session = SessionLocal()
        try:
            session.add(audit_entry)
            session.commit()
            session.refresh(audit_entry)
            return audit_entry
        except Exception as e:
            session.rollback()
            print(f"[AUDIT LOG WARNING] Failed to record isolated audit event '{action}': {e}", file=sys.stderr)
            return None
        finally:
            session.close()
    else:
        try:
            db.add(audit_entry)
            db.commit()
            db.refresh(audit_entry)
            return audit_entry
        except Exception as e:
            db.rollback()
            print(f"[AUDIT LOG WARNING] Failed to record audit event '{action}': {e}", file=sys.stderr)
            return None


def format_utc_iso(dt: datetime | None) -> str | None:
    """Serializes a datetime object to an ISO 8601 UTC string ending with 'Z'."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def format_audit_event_response(audit_log: AuditLog, is_system_view: bool = False) -> dict:
    """
    Formats an AuditLog model into an API dictionary response.
    - Formats created_at to canonical UTC ISO with 'Z'.
    - If is_system_view is False (document-level view), masks sensitive fields like ip_address.
    """
    parsed_meta = None
    if audit_log.metadata_json:
        try:
            parsed_meta = json.loads(audit_log.metadata_json)
        except Exception:
            parsed_meta = None

    data = {
        "id": audit_log.id,
        "actor_id": audit_log.actor_id,
        "actor_name": audit_log.actor_name or "System / Anonymous",
        "actor_role": audit_log.actor_role or "ANONYMOUS",
        "action": audit_log.action,
        "resource_type": audit_log.resource_type,
        "resource_id": audit_log.resource_id,
        "document_id": audit_log.document_id,
        "document_title": audit_log.document_title,
        "version_id": audit_log.version_id,
        "version_number": audit_log.version_number,
        "result": audit_log.result,
        "reason": audit_log.reason,
        "metadata": parsed_meta,
        "created_at": format_utc_iso(audit_log.created_at),
        "actor_email": audit_log.actor_email if is_system_view else None,
        "ip_address": audit_log.ip_address if is_system_view else None,
    }

    return data
