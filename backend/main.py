from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
import json
import shutil
import os
import hashlib
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import func

from database import engine, Base, SessionLocal, migrate_schema, seed_initial_users
from models import Document, User, UserRole, DocumentShare, DocumentVersion, AuditLog, DocumentVersionMetadata
from sqlalchemy.exc import IntegrityError
from blockchain import (
    register_document_on_chain,
    get_document_from_chain,
    get_web3_and_contract,
    CONTRACT_ADDRESS,
    BlockchainUnavailableError,
    ContractUnavailableError,
)
from auth import (
    get_current_user,
    require_roles,
    verify_password,
    create_access_token,
    get_db,
)
from audit import (
    log_audit_event,
    AuditEventType,
    AuditResult,
    AuditResourceType,
    format_audit_event_response,
)
from ai_extractor import (
    AIExtractor,
    AIConfigurationError,
    AITimeoutError,
    AIParsingError,
    AIServiceError,
    DEFAULT_EMPTY_METADATA,
    normalize_extracted_schema,
)

Base.metadata.create_all(bind=engine)
migrate_schema()
seed_initial_users()

app = FastAPI(title="LegalVault API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


from pydantic import BaseModel, field_serializer


def format_utc_iso(dt: datetime | None) -> str | None:
    """
    Serializes a datetime object to an unambiguous UTC ISO 8601 string ending in 'Z'.
    If the datetime is naive (such as historical records read from SQLite), it is
    explicitly interpreted as UTC without modifying or shifting the numerical clock value.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


# --- Schemas ---

class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    created_at: datetime | None = None

    class Config:
        from_attributes = True

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime | None, _info) -> str | None:
        return format_utc_iso(dt)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ShareRequest(BaseModel):
    shared_with_user_id: int | None = None
    email: str | None = None


class ShareableUserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str


class ResetVaultResponse(BaseModel):
    message: str
    documents_deleted: int
    shares_deleted: int
    files_deleted: int
    audit_records_cleared: int | None = None


class AuditLogItemResponse(BaseModel):
    id: int
    actor_id: int | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    actor_email: str | None = None
    ip_address: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    document_id: int | None = None
    document_title: str | None = None
    version_id: int | None = None
    version_number: int | None = None
    result: str
    reason: str | None = None
    metadata: dict | None = None
    created_at: str | None = None


class DocumentAuditResponse(BaseModel):
    document_id: int
    total_count: int
    events: list[AuditLogItemResponse]


class SystemAuditResponse(BaseModel):
    total_count: int
    events: list[AuditLogItemResponse]


class SystemOverviewStats(BaseModel):
    total_documents: int
    total_versions: int
    total_file_size_bytes: int
    total_users: int
    users_by_role: dict[str, int]
    total_active_shares: int
    shared_documents_count: int


class IntegrityOverviewStats(BaseModel):
    verified_documents: int
    tampered_documents: int
    proof_unavailable_documents: int
    attention_required_count: int


class SecurityOverviewStats(BaseModel):
    window_hours: int = 24
    failed_logins_24h: int
    failed_logins_all_time: int
    access_denied_24h: int
    access_denied_all_time: int
    action_denied_24h: int
    action_denied_all_time: int


class BlockchainOverviewStats(BaseModel):
    is_connected: bool
    chain_id: int | None = None
    network_name: str
    contract_address: str
    anchored_versions_count: int
    pending_versions_count: int
    latest_anchor_tx: str | None = None
    latest_anchor_time: str | None = None


class AttentionDocumentItem(BaseModel):
    document_id: int
    filename: str
    case_number: str | None = None
    version_number: int | None = None
    issue_type: str  # "TAMPERED", "PROOF_UNAVAILABLE", "MISSING_FILE"
    detected_at: str | None = None
    reason: str | None = None


class AdminDashboardResponse(BaseModel):
    system_overview: SystemOverviewStats
    integrity_overview: IntegrityOverviewStats
    security_overview: SecurityOverviewStats
    blockchain_overview: BlockchainOverviewStats
    attention_documents: list[AttentionDocumentItem]
    recent_activity: list[AuditLogItemResponse]
    generated_at: str


# --- AI Metadata Schemas ---

class PartyItem(BaseModel):
    name: str
    role: str = "Party"


class DateItem(BaseModel):
    date: str
    description: str = "Date"


class ConfidenceSchema(BaseModel):
    overall: float = 0.0
    fields: dict[str, float] = {}


class DocumentVersionMetadataResponse(BaseModel):
    id: int | None = None
    document_id: int
    version_id: int | None = None
    version_number: int
    source_hash: str | None = None
    status: str  # NOT_ANALYZED, COMPLETED, FAILED, EXTRACTION_UNAVAILABLE
    document_type: str | None = None
    case_number: str | None = None
    court: str | None = None
    jurisdiction: str | None = None
    subject: str | None = None
    parties: list[PartyItem] = []
    dates: list[DateItem] = []
    keywords: list[str] = []
    confidence: ConfidenceSchema = ConfidenceSchema()
    ai_provider: str | None = None
    ai_model: str | None = None
    extraction_duration_ms: int | None = None
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    cached: bool = False
    is_owner_or_admin: bool = False


def format_version_metadata_response(
    meta: DocumentVersionMetadata | None,
    document_id: int,
    version_id: int | None,
    version_number: int,
    source_hash: str | None,
    is_owner_or_admin: bool,
    cached: bool = False,
) -> dict:
    if meta is None:
        return {
            "id": None,
            "document_id": document_id,
            "version_id": version_id,
            "version_number": version_number,
            "source_hash": source_hash,
            "status": "NOT_ANALYZED",
            "document_type": None,
            "case_number": None,
            "court": None,
            "jurisdiction": None,
            "subject": None,
            "parties": [],
            "dates": [],
            "keywords": [],
            "confidence": {"overall": 0.0, "fields": {}},
            "ai_provider": None,
            "ai_model": None,
            "extraction_duration_ms": None,
            "error_message": None,
            "created_at": None,
            "updated_at": None,
            "cached": False,
            "is_owner_or_admin": is_owner_or_admin,
        }

    parties = []
    if meta.parties_json:
        try:
            parties = json.loads(meta.parties_json)
        except Exception:
            parties = []

    dates = []
    if meta.dates_json:
        try:
            dates = json.loads(meta.dates_json)
        except Exception:
            dates = []

    keywords = []
    if meta.keywords_json:
        try:
            keywords = json.loads(meta.keywords_json)
        except Exception:
            keywords = []

    confidence = {"overall": 0.0, "fields": {}}
    if meta.confidence_json:
        try:
            confidence = json.loads(meta.confidence_json)
        except Exception:
            confidence = {"overall": 0.0, "fields": {}}

    return {
        "id": meta.id,
        "document_id": meta.document_id,
        "version_id": meta.version_id,
        "version_number": meta.version_number,
        "source_hash": meta.source_hash,
        "status": meta.status or "NOT_ANALYZED",
        "document_type": meta.document_type,
        "case_number": meta.case_number,
        "court": meta.court,
        "jurisdiction": meta.jurisdiction,
        "subject": meta.subject,
        "parties": parties,
        "dates": dates,
        "keywords": keywords,
        "confidence": confidence,
        "ai_provider": meta.ai_provider,
        "ai_model": meta.ai_model,
        "extraction_duration_ms": meta.extraction_duration_ms,
        "error_message": meta.error_message,
        "created_at": format_utc_iso(meta.created_at),
        "updated_at": format_utc_iso(meta.updated_at),
        "cached": cached,
        "is_owner_or_admin": is_owner_or_admin,
    }



LEGALVAULT_ENV = os.getenv("LEGALVAULT_ENV", "development").strip().lower()
LEGALVAULT_UPLOAD_MAX_MB = int(os.getenv("LEGALVAULT_UPLOAD_MAX_MB", "10"))
MAX_UPLOAD_BYTES = LEGALVAULT_UPLOAD_MAX_MB * 1024 * 1024

ALLOWED_EXTENSIONS_STR = os.getenv("LEGALVAULT_ALLOWED_EXTENSIONS", ".pdf,.txt,.docx,.jpg,.jpeg,.png")
ALLOWED_EXTENSIONS = [ext.strip().lower() for ext in ALLOWED_EXTENSIONS_STR.split(",") if ext.strip()]


# --- Access Control Helpers ---

def check_document_ownership(document: Document, user: User) -> bool:
    """Checks if the user is the direct owner of the document or an admin."""
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.LAWYER:
        if document.owner_id is not None and document.owner_id == user.id:
            return True
        if document.owner_id is None and document.uploaded_by:
            uploader = document.uploaded_by.strip().lower()
            if uploader in [user.name.strip().lower(), user.email.strip().lower()]:
                return True
    return False


def check_document_access(document: Document, user: User, db: Session) -> bool:
    """
    Enforces document access rules:
    - ADMIN: Full access to all documents.
    - LAWYER: Access to documents they own OR documents explicitly shared with them.
    - JUDGE / CLIENT: Access strictly limited to documents explicitly shared with them.
    """
    if user.role == UserRole.ADMIN:
        return True

    if user.role == UserRole.LAWYER:
        if check_document_ownership(document, user):
            return True
        # Check if explicitly shared with this lawyer
        share = db.query(DocumentShare).filter(
            DocumentShare.document_id == document.id,
            DocumentShare.shared_with_user_id == user.id,
        ).first()
        return share is not None

    if user.role in [UserRole.JUDGE, UserRole.CLIENT]:
        # Only if document is explicitly shared with this user
        share = db.query(DocumentShare).filter(
            DocumentShare.document_id == document.id,
            DocumentShare.shared_with_user_id == user.id,
        ).first()
        return share is not None

    return False


# --- Auth Endpoints ---

@app.get("/")
def home():
    return {
        "message": "LegalVault API is running"
    }


@app.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email_clean = req.email.lower().strip()
    client_ip = request.client.host if request.client else None
    user = db.query(User).filter(User.email == email_clean).first()
    if not user or not verify_password(req.password, user.password_hash):
        log_audit_event(
            action=AuditEventType.LOGIN_FAILED,
            result=AuditResult.FAILED,
            actor_email=email_clean,
            ip_address=client_ip,
            reason="Invalid email or password",
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    log_audit_event(
        db=db,
        action=AuditEventType.LOGIN_SUCCESS,
        result=AuditResult.SUCCESS,
        actor=user,
        ip_address=client_ip,
    )

    token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role}
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user,
    }


@app.post("/auth/logout")
def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else None
    log_audit_event(
        db=db,
        action=AuditEventType.LOGOUT,
        result=AuditResult.SUCCESS,
        actor=current_user,
        ip_address=client_ip,
    )
    return {"message": "Logged out successfully"}


@app.get("/auth/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@app.get("/users/shareable", response_model=list[ShareableUserResponse])
def get_shareable_users(
    current_user: User = Depends(require_roles(UserRole.LAWYER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Returns all JUDGE and CLIENT users available as share recipients."""
    users = db.query(User).filter(User.role.in_([UserRole.JUDGE, UserRole.CLIENT])).all()
    return [
        {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "role": u.role,
        }
        for u in users
    ]


# --- Document Endpoints ---

@app.get("/documents")
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == UserRole.ADMIN:
        documents = db.query(Document).order_by(Document.created_at.desc()).all()
        return [
            {
                "id": doc.id,
                "filename": doc.filename,
                "case_number": doc.case_number,
                "uploaded_by": doc.uploaded_by,
                "file_hash": doc.file_hash,
                "version": doc.version,
                "blockchain_tx_hash": doc.blockchain_tx_hash,
                "blockchain_status": doc.blockchain_status,
                "created_at": format_utc_iso(doc.created_at),
                "is_owner": True,
                "is_shared": False,
                "shared_by_name": None,
            }
            for doc in documents
        ]

    elif current_user.role == UserRole.LAWYER:
        all_docs = db.query(Document).order_by(Document.created_at.desc()).all()
        result = []
        for doc in all_docs:
            is_owner = check_document_ownership(doc, current_user)
            share = db.query(DocumentShare).filter(
                DocumentShare.document_id == doc.id,
                DocumentShare.shared_with_user_id == current_user.id,
            ).first()

            if is_owner or share:
                creator_name = None
                if share:
                    creator_user = db.query(User).filter(User.id == share.shared_by_user_id).first()
                    creator_name = creator_user.name if creator_user else None
                result.append({
                    "id": doc.id,
                    "filename": doc.filename,
                    "case_number": doc.case_number,
                    "uploaded_by": doc.uploaded_by,
                    "file_hash": doc.file_hash,
                    "version": doc.version,
                    "blockchain_tx_hash": doc.blockchain_tx_hash,
                    "blockchain_status": doc.blockchain_status,
                    "created_at": format_utc_iso(doc.created_at),
                    "is_owner": is_owner,
                    "is_shared": share is not None and not is_owner,
                    "shared_by_name": creator_name,
                })
        return result

    else:
        # JUDGE or CLIENT: only query documents explicitly shared with current_user
        shares = db.query(DocumentShare).filter(
            DocumentShare.shared_with_user_id == current_user.id
        ).all()

        if not shares:
            return []

        share_map = {s.document_id: s for s in shares}
        doc_ids = list(share_map.keys())
        docs = db.query(Document).filter(Document.id.in_(doc_ids)).order_by(Document.created_at.desc()).all()

        result = []
        for doc in docs:
            share = share_map.get(doc.id)
            creator_name = None
            if share:
                creator = db.query(User).filter(User.id == share.shared_by_user_id).first()
                if creator:
                    creator_name = creator.name

            result.append({
                "id": doc.id,
                "filename": doc.filename,
                "case_number": doc.case_number,
                "uploaded_by": doc.uploaded_by,
                "file_hash": doc.file_hash,
                "version": doc.version,
                "blockchain_tx_hash": doc.blockchain_tx_hash,
                "blockchain_status": doc.blockchain_status,
                "created_at": format_utc_iso(doc.created_at),
                "is_owner": False,
                "is_shared": True,
                "shared_by_name": creator_name or doc.uploaded_by,
            })
        return result


def get_version_file_path(version: DocumentVersion, document: Document = None) -> str:
    """Resolves the on-disk file path for a document version with fallback for legacy files."""
    if version and version.stored_filename:
        stored_path = os.path.join(UPLOAD_DIR, version.stored_filename)
        if os.path.exists(stored_path):
            return stored_path
    if version and version.filename:
        name_path = os.path.join(UPLOAD_DIR, version.filename)
        if os.path.exists(name_path):
            return name_path
    if document and document.filename:
        doc_path = os.path.join(UPLOAD_DIR, document.filename)
        if os.path.exists(doc_path):
            return doc_path
    target = (version.stored_filename if version and version.stored_filename else (version.filename if version else (document.filename if document else "unknown")))
    return os.path.join(UPLOAD_DIR, target)


def find_document_version(document_id: int, version_identifier: str | int, db: Session) -> DocumentVersion | None:
    """Finds a version by version_number (e.g. 1, 2) or by primary key ID."""
    try:
        num = int(version_identifier)
        # Check by version_number first
        v = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == document_id,
            DocumentVersion.version_number == num,
        ).first()
        if v:
            return v
        # Then check by primary key id
        v = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == document_id,
            DocumentVersion.id == num,
        ).first()
        if v:
            return v
    except (ValueError, TypeError):
        pass
    return None


@app.get("/documents/{document_id}")
def get_document_detail(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database",
        )

    if not check_document_access(document, current_user, db):
        log_audit_event(
            action=AuditEventType.ACCESS_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason=f"Access forbidden: You do not have permission to view document #{document_id}",
            metadata={"attempted_action": "VIEW_DOCUMENT"},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: You do not have permission to view document #{document_id}",
        )

    onchain_data = None
    try:
        onchain_data = get_document_from_chain(str(document.id))
    except Exception:
        pass

    is_owner = check_document_ownership(document, current_user)
    version_count = db.query(DocumentVersion).filter(DocumentVersion.document_id == document.id).count()
    if version_count == 0:
        version_count = 1

    # Record audit event for viewing document
    if not is_owner and current_user.role != UserRole.ADMIN:
        log_audit_event(
            db=db,
            action=AuditEventType.SHARED_DOCUMENT_ACCESSED,
            result=AuditResult.SUCCESS,
            actor=current_user,
            document=document,
            version_number=document.version or 1,
        )
    else:
        log_audit_event(
            db=db,
            action=AuditEventType.DOCUMENT_VIEWED,
            result=AuditResult.SUCCESS,
            actor=current_user,
            document=document,
            version_number=document.version or 1,
        )

    return {
        "id": document.id,
        "filename": document.filename,
        "case_number": document.case_number,
        "uploaded_by": document.uploaded_by,
        "file_hash": document.file_hash,
        "version": document.version or 1,
        "version_count": version_count,
        "blockchain_tx_hash": document.blockchain_tx_hash,
        "blockchain_status": document.blockchain_status,
        "created_at": format_utc_iso(document.created_at),
        "onchain": onchain_data,
        "contract_address": CONTRACT_ADDRESS,
        "is_owner": is_owner,
    }


@app.get("/documents/{document_id}/download")
def download_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database",
        )

    if not check_document_access(document, current_user, db):
        log_audit_event(
            action=AuditEventType.ACCESS_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason=f"Access forbidden: You do not have permission to download document #{document_id}",
            metadata={"attempted_action": "DOWNLOAD_DOCUMENT"},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: You do not have permission to download document #{document_id}",
        )

    # Find the current active version record if available
    current_ver = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == document.id,
        DocumentVersion.version_number == (document.version or 1),
    ).first()

    file_path = get_version_file_path(current_ver, document)
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stored document file '{document.filename}' not found on disk",
        )

    log_audit_event(
        db=db,
        action=AuditEventType.DOCUMENT_DOWNLOADED,
        result=AuditResult.SUCCESS,
        actor=current_user,
        document=document,
        version_number=document.version or 1,
    )

    return FileResponse(
        path=file_path,
        filename=document.filename,
        media_type="application/octet-stream",
    )


@app.post("/documents/upload")
def upload_document(
    file: UploadFile = File(...),
    case_number: str = Form(...),
    uploaded_by: str = Form(None),
    allow_duplicate: bool = Form(False),
    current_user: User = Depends(require_roles(UserRole.LAWYER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    # 1. Validate File Extension
    ext = os.path.splitext(file.filename)[1].lower()
    if not ext or ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed formats: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # 2. Read in chunks to compute SHA-256 and check max size without excessive memory usage
    hasher = hashlib.sha256()
    file_bytes = bytearray()
    total_bytes = 0
    chunk_size = 64 * 1024  # 64 KB

    while True:
        chunk = file.file.read(chunk_size)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Uploaded file exceeds maximum allowed size limit of {LEGALVAULT_UPLOAD_MAX_MB} MB (received {total_bytes / (1024*1024):.2f} MB).",
            )
        hasher.update(chunk)
        file_bytes.extend(chunk)

    file_hash = hasher.hexdigest()

    # 3. Duplicate SHA-256 Detection
    if not allow_duplicate:
        existing_doc = db.query(Document).filter(Document.file_hash == file_hash).first()
        if existing_doc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "DUPLICATE_DOCUMENT",
                    "message": "Duplicate document content detected. A record with an identical SHA-256 cryptographic hash already exists in the vault.",
                    "existing_document": {
                        "id": existing_doc.id,
                        "filename": existing_doc.filename,
                        "case_number": existing_doc.case_number,
                        "uploaded_by": existing_doc.uploaded_by,
                        "file_hash": existing_doc.file_hash,
                        "blockchain_status": existing_doc.blockchain_status,
                        "created_at": format_utc_iso(existing_doc.created_at),
                    },
                },
            )

    # 4. Save file to disk
    stored_filename = file.filename
    file_path = os.path.join(UPLOAD_DIR, stored_filename)
    try:
        with open(file_path, "wb") as buffer:
            buffer.write(file_bytes)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save document file to disk: {str(e)}",
        )

    # 5. Create database records (Document + DocumentVersion v1)
    try:
        document = Document(
            filename=file.filename,
            case_number=case_number,
            uploaded_by=uploaded_by or current_user.name,
            owner_id=current_user.id,
            file_hash=file_hash,
            version=1,
        )
        db.add(document)
        db.commit()
        db.refresh(document)

        v1 = DocumentVersion(
            document_id=document.id,
            version_number=1,
            filename=file.filename,
            stored_filename=stored_filename,
            file_size=total_bytes,
            file_type=ext,
            file_hash=file_hash,
            uploaded_by=uploaded_by or current_user.name,
            uploader_id=current_user.id,
            created_at=document.created_at,
        )
        db.add(v1)
        db.commit()
        db.refresh(v1)
    except Exception as e:
        db.rollback()
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database failure creating document records: {str(e)}",
        )

    # 6. Anchor to Blockchain
    blockchain_tx_hash = None
    blockchain_status = "failed"

    try:
        # Register version-specific key e.g. "1_v1"
        ver_result = register_document_on_chain(
            document_id=f"{document.id}_v1",
            document_hash=file_hash,
            version=1,
        )
        blockchain_tx_hash = ver_result["blockchain_tx_hash"]
        blockchain_status = ver_result["blockchain_status"]

        # Also register master document key e.g. "1"
        try:
            register_document_on_chain(
                document_id=str(document.id),
                document_hash=file_hash,
                version=1,
            )
        except Exception:
            pass
    except Exception:
        blockchain_status = "failed"

    document.blockchain_tx_hash = blockchain_tx_hash
    document.blockchain_status = blockchain_status
    v1.blockchain_tx_hash = blockchain_tx_hash
    v1.blockchain_status = blockchain_status
    db.commit()
    db.refresh(document)

    # Audit log for document creation
    log_audit_event(
        db=db,
        action=AuditEventType.DOCUMENT_CREATED,
        result=AuditResult.SUCCESS,
        actor=current_user,
        document=document,
        version=v1,
        version_number=1,
        metadata={"case_number": case_number},
    )

    return {
        "message": "Document uploaded successfully",
        "document_id": document.id,
        "filename": document.filename,
        "file_hash": file_hash,
        "version": document.version,
        "blockchain_tx_hash": document.blockchain_tx_hash,
        "blockchain_status": document.blockchain_status,
    }


# --- Document Version History Endpoints ---

@app.get("/documents/{document_id}/versions")
def list_document_versions(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns the version history for a document ordered from newest to oldest."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database",
        )

    if not check_document_access(document, current_user, db):
        log_audit_event(
            action=AuditEventType.ACCESS_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason=f"Access forbidden: You do not have permission to view versions for document #{document_id}",
            metadata={"attempted_action": "LIST_VERSIONS"},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: You do not have permission to view versions for document #{document_id}",
        )

    versions = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == document_id
    ).order_by(DocumentVersion.version_number.desc()).all()

    # If no DocumentVersion rows exist yet, create a synthetic representation of v1
    if not versions:
        return [
            {
                "id": document.id,
                "document_id": document.id,
                "version_number": document.version or 1,
                "filename": document.filename,
                "stored_filename": document.filename,
                "file_size": 0,
                "file_type": os.path.splitext(document.filename)[1].lower() if document.filename else None,
                "file_hash": document.file_hash,
                "uploaded_by": document.uploaded_by,
                "uploader_id": document.owner_id,
                "blockchain_tx_hash": document.blockchain_tx_hash,
                "blockchain_status": document.blockchain_status,
                "created_at": format_utc_iso(document.created_at),
                "is_current": True,
            }
        ]

    return [
        {
            "id": v.id,
            "document_id": v.document_id,
            "version_number": v.version_number,
            "filename": v.filename,
            "stored_filename": v.stored_filename,
            "file_size": v.file_size,
            "file_type": v.file_type,
            "file_hash": v.file_hash,
            "uploaded_by": v.uploaded_by,
            "uploader_id": v.uploader_id,
            "blockchain_tx_hash": v.blockchain_tx_hash,
            "blockchain_status": v.blockchain_status,
            "created_at": format_utc_iso(v.created_at),
            "is_current": (v.version_number == document.version),
        }
        for v in versions
    ]


@app.get("/documents/{document_id}/versions/{version_identifier}")
def get_document_version_detail(
    document_id: int,
    version_identifier: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieves metadata and blockchain provenance for a specific document version."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database",
        )

    if not check_document_access(document, current_user, db):
        log_audit_event(
            action=AuditEventType.ACCESS_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason=f"Access forbidden: You do not have permission to view document #{document_id}",
            metadata={"attempted_action": "VIEW_VERSION", "version_identifier": str(version_identifier)},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: You do not have permission to view document #{document_id}",
        )

    version = find_document_version(document_id, version_identifier, db)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version '{version_identifier}' not found for document #{document_id}",
        )

    onchain_data = None
    try:
        onchain_data = get_document_from_chain(f"{document.id}_v{version.version_number}")
        if (not onchain_data.get("document_hash") or onchain_data.get("timestamp") == 0) and version.version_number == 1:
            try:
                base_chain = get_document_from_chain(str(document.id))
                if base_chain.get("document_hash") and base_chain.get("timestamp") != 0:
                    onchain_data = base_chain
            except Exception:
                pass
    except Exception:
        pass

    log_audit_event(
        db=db,
        action=AuditEventType.VERSION_VIEWED,
        result=AuditResult.SUCCESS,
        actor=current_user,
        document=document,
        version=version,
        version_number=version.version_number,
    )

    return {
        "id": version.id,
        "document_id": version.document_id,
        "version_number": version.version_number,
        "filename": version.filename,
        "stored_filename": version.stored_filename,
        "file_size": version.file_size,
        "file_type": version.file_type,
        "file_hash": version.file_hash,
        "uploaded_by": version.uploaded_by,
        "uploader_id": version.uploader_id,
        "blockchain_tx_hash": version.blockchain_tx_hash,
        "blockchain_status": version.blockchain_status,
        "created_at": format_utc_iso(version.created_at),
        "is_current": (version.version_number == document.version),
        "onchain": onchain_data,
        "contract_address": CONTRACT_ADDRESS,
    }


@app.get("/documents/{document_id}/versions/{version_identifier}/download")
def download_document_version(
    document_id: int,
    version_identifier: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Downloads the exact off-chain file corresponding to a historical version."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database",
        )

    if not check_document_access(document, current_user, db):
        log_audit_event(
            action=AuditEventType.ACCESS_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason=f"Access forbidden: You do not have permission to download document #{document_id}",
            metadata={"attempted_action": "DOWNLOAD_VERSION", "version_identifier": str(version_identifier)},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: You do not have permission to download document #{document_id}",
        )

    version = find_document_version(document_id, version_identifier, db)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version '{version_identifier}' not found for document #{document_id}",
        )

    file_path = get_version_file_path(version, document)
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stored document version file '{version.filename}' (v{version.version_number}) not found on disk",
        )

    log_audit_event(
        db=db,
        action=AuditEventType.VERSION_DOWNLOADED,
        result=AuditResult.SUCCESS,
        actor=current_user,
        document=document,
        version=version,
        version_number=version.version_number,
    )

    return FileResponse(
        path=file_path,
        filename=version.filename,
        media_type="application/octet-stream",
    )


@app.post("/documents/{document_id}/versions")
def upload_document_version(
    document_id: int,
    file: UploadFile = File(...),
    uploaded_by: str = Form(None),
    allow_duplicate: bool = Form(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Creates a new immutable revision (Version N+1) for an existing document.
    - Strictly enforces ownership/admin permissions.
    - Validates file type and size limit.
    - Calculates SHA-256 hash.
    - Checks duplicate hash within the document versions.
    - Safely creates version record and anchors on-chain with rollback on failure.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database",
        )

    # Permissions: Only Document Owner or Admin can upload new version
    if not check_document_ownership(document, current_user):
        log_audit_event(
            action=AuditEventType.ACTION_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason="Access forbidden: You do not have permission to upload revisions to this document. Only the document owner or an administrator can create new versions.",
            metadata={"attempted_action": "VERSION_UPLOAD"},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You do not have permission to upload revisions to this document. Only the document owner or an administrator can create new versions.",
        )

    # 1. Validate File Extension
    ext = os.path.splitext(file.filename)[1].lower()
    if not ext or ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed formats: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # 2. Read in chunks to compute SHA-256 and check max size
    hasher = hashlib.sha256()
    file_bytes = bytearray()
    total_bytes = 0
    chunk_size = 64 * 1024  # 64 KB

    while True:
        chunk = file.file.read(chunk_size)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Uploaded file exceeds maximum allowed size limit of {LEGALVAULT_UPLOAD_MAX_MB} MB (received {total_bytes / (1024*1024):.2f} MB).",
            )
        hasher.update(chunk)
        file_bytes.extend(chunk)

    file_hash = hasher.hexdigest()

    # 3. Duplicate Detection for this document
    if not allow_duplicate:
        existing_version = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == document.id,
            DocumentVersion.file_hash == file_hash,
        ).first()

        if existing_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "DUPLICATE_VERSION",
                    "message": f"Duplicate version content detected. Version {existing_version.version_number} of this document already has an identical cryptographic SHA-256 hash.",
                    "existing_version": {
                        "id": existing_version.id,
                        "document_id": existing_version.document_id,
                        "version_number": existing_version.version_number,
                        "filename": existing_version.filename,
                        "file_hash": existing_version.file_hash,
                        "created_at": format_utc_iso(existing_version.created_at),
                    },
                },
            )

    # 4. Determine deterministic next version number
    max_ver = db.query(DocumentVersion.version_number).filter(
        DocumentVersion.document_id == document.id
    ).order_by(DocumentVersion.version_number.desc()).first()

    next_version = (max_ver[0] + 1) if max_ver else ((document.version or 1) + 1)

    # 5. Store file with unique version path
    clean_filename = os.path.basename(file.filename)
    stored_filename = f"doc_{document.id}_v{next_version}_{clean_filename}"
    file_path = os.path.join(UPLOAD_DIR, stored_filename)

    try:
        with open(file_path, "wb") as buffer:
            buffer.write(file_bytes)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write version file to storage: {str(e)}",
        )

    # 6. Database record creation with rollback on error
    try:
        new_version = DocumentVersion(
            document_id=document.id,
            version_number=next_version,
            filename=file.filename,
            stored_filename=stored_filename,
            file_size=total_bytes,
            file_type=ext,
            file_hash=file_hash,
            uploaded_by=uploaded_by or current_user.name,
            uploader_id=current_user.id,
        )
        db.add(new_version)

        # Update parent document current version pointer and master metadata
        document.version = next_version
        document.filename = file.filename
        document.file_hash = file_hash

        db.commit()
        db.refresh(new_version)
        db.refresh(document)
    except IntegrityError:
        db.rollback()
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A version with number {next_version} was concurrently registered for document #{document.id}. Please retry.",
        )
    except Exception as e:
        db.rollback()
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database failure creating version record: {str(e)}",
        )

    # 7. Anchor to Blockchain
    blockchain_tx_hash = None
    blockchain_status = "failed"

    try:
        # Register version-specific key e.g. "1_v2"
        ver_chain = register_document_on_chain(
            document_id=f"{document.id}_v{next_version}",
            document_hash=file_hash,
            version=next_version,
        )
        blockchain_tx_hash = ver_chain["blockchain_tx_hash"]
        blockchain_status = ver_chain["blockchain_status"]

        # Also update master document key e.g. "1"
        try:
            register_document_on_chain(
                document_id=str(document.id),
                document_hash=file_hash,
                version=next_version,
            )
        except Exception:
            pass
    except Exception:
        blockchain_status = "failed"

    new_version.blockchain_tx_hash = blockchain_tx_hash
    new_version.blockchain_status = blockchain_status
    document.blockchain_tx_hash = blockchain_tx_hash
    document.blockchain_status = blockchain_status
    db.commit()
    db.refresh(new_version)
    db.refresh(document)

    # Audit log for version creation
    log_audit_event(
        db=db,
        action=AuditEventType.VERSION_CREATED,
        result=AuditResult.SUCCESS,
        actor=current_user,
        document=document,
        version=new_version,
        version_number=next_version,
    )

    return {
        "message": f"Version {next_version} created and anchored successfully",
        "document_id": document.id,
        "version_id": new_version.id,
        "version_number": new_version.version_number,
        "filename": new_version.filename,
        "file_hash": new_version.file_hash,
        "file_size": new_version.file_size,
        "blockchain_tx_hash": new_version.blockchain_tx_hash,
        "blockchain_status": new_version.blockchain_status,
        "created_at": format_utc_iso(new_version.created_at),
    }


@app.post("/documents/{document_id}/versions/{version_identifier}/verify")
def verify_document_version(
    document_id: int,
    version_identifier: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cryptographically verifies a specific historical version of a document against the blockchain."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database",
        )

    if not check_document_access(document, current_user, db):
        log_audit_event(
            action=AuditEventType.ACCESS_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason=f"Access forbidden: You do not have permission to verify document #{document_id}",
            metadata={"attempted_action": "VERIFY_VERSION", "version_identifier": str(version_identifier)},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: You do not have permission to verify document #{document_id}",
        )

    version = find_document_version(document_id, version_identifier, db)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version '{version_identifier}' not found for document #{document_id}",
        )

    file_path = get_version_file_path(version, document)
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stored document version file '{version.filename}' (v{version.version_number}) not found on disk",
        )

    with open(file_path, "rb") as f:
        current_hash = hashlib.sha256(f.read()).hexdigest()

    try:
        onchain_data = get_document_from_chain(f"{document.id}_v{version.version_number}")
        if (not onchain_data.get("document_hash") or onchain_data.get("timestamp") == 0) and version.version_number == 1:
            try:
                base_chain = get_document_from_chain(str(document.id))
                if base_chain.get("document_hash") and base_chain.get("timestamp") != 0:
                    onchain_data = base_chain
            except Exception:
                pass
    except BlockchainUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "BLOCKCHAIN_UNAVAILABLE",
                "message": "Blockchain node is offline. Start the local Hardhat node.",
                "technical_details": str(e),
            },
        )
    except ContractUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "CONTRACT_UNAVAILABLE",
                "message": "LegalVault smart contract could not be found at the configured address.",
                "contract_address": CONTRACT_ADDRESS,
                "technical_details": str(e),
            },
        )
    except ConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "BLOCKCHAIN_UNAVAILABLE",
                "message": "Blockchain node is offline. Start the local Hardhat node.",
                "technical_details": str(e),
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "CONTRACT_UNAVAILABLE",
                "message": f"Failed to retrieve document version proof from blockchain: {str(e)}",
                "technical_details": str(e),
            },
        )

    blockchain_hash = onchain_data.get("document_hash")
    timestamp = onchain_data.get("timestamp")

    if not blockchain_hash or blockchain_hash == "" or timestamp == 0:
        log_audit_event(
            db=db,
            action=AuditEventType.BLOCKCHAIN_PROOF_UNAVAILABLE,
            result=AuditResult.UNAVAILABLE,
            actor=current_user,
            document=document,
            version=version,
            version_number=version.version_number,
            reason=f"Version {version.version_number} exists in vault repository, but its blockchain proof is unavailable on the currently connected chain.",
        )
        return {
            "document_id": document.id,
            "version_id": version.id,
            "version_number": version.version_number,
            "filename": version.filename,
            "case_number": document.case_number,
            "uploaded_by": version.uploaded_by,
            "current_hash": current_hash,
            "blockchain_hash": None,
            "blockchain_status": version.blockchain_status,
            "verified": False,
            "result": "BLOCKCHAIN_PROOF_UNAVAILABLE",
            "message": f"Version {version.version_number} exists in the vault repository, but its blockchain proof is unavailable on the currently connected chain.",
            "blockchain_tx_hash": version.blockchain_tx_hash,
            "contract_address": CONTRACT_ADDRESS,
            "owner": None,
            "timestamp": None,
            "version": version.version_number,
            "is_current": (version.version_number == document.version),
        }

    is_verified = (current_hash.lower() == blockchain_hash.lower())
    result_text = "VERIFIED" if is_verified else "TAMPERED"

    if is_verified:
        log_audit_event(
            db=db,
            action=AuditEventType.VERSION_VERIFIED,
            result=AuditResult.VERIFIED,
            actor=current_user,
            document=document,
            version=version,
            version_number=version.version_number,
            metadata={"timestamp": timestamp},
        )
    else:
        log_audit_event(
            db=db,
            action=AuditEventType.VERSION_TAMPERED,
            result=AuditResult.TAMPERED,
            actor=current_user,
            document=document,
            version=version,
            version_number=version.version_number,
            reason=f"Local cryptographic hash does not match on-chain anchor for Version {version.version_number}",
            metadata={"current_hash": current_hash, "blockchain_hash": blockchain_hash},
        )

    return {
        "document_id": document.id,
        "version_id": version.id,
        "version_number": version.version_number,
        "filename": version.filename,
        "case_number": document.case_number,
        "uploaded_by": version.uploaded_by,
        "current_hash": current_hash,
        "blockchain_hash": blockchain_hash,
        "blockchain_status": version.blockchain_status,
        "verified": is_verified,
        "result": result_text,
        "blockchain_tx_hash": version.blockchain_tx_hash,
        "contract_address": CONTRACT_ADDRESS,
        "owner": onchain_data.get("owner"),
        "timestamp": onchain_data.get("timestamp"),
        "version": onchain_data.get("version") or version.version_number,
        "is_current": (version.version_number == document.version),
    }


# --- AI Metadata Extraction & Query Endpoints ---

@app.post("/documents/{document_id}/versions/{version_identifier}/metadata/extract", response_model=DocumentVersionMetadataResponse)
def extract_document_version_metadata(
    document_id: int,
    version_identifier: str,
    force: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Triggers or returns cached AI-assisted structured legal metadata extraction for a specific document version.
    - RBAC: Allowed only for Document Owner and Administrator.
    - Shared Judges / Clients: Blocked with HTTP 403 (ACTION_DENIED).
    - Caching: Returns cached COMPLETED metadata instantly for the immutable version SHA-256 hash unless force=True.
    - Fault Isolation: AI errors do not affect the underlying document, version, SHA-256, or blockchain state.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database",
        )

    # 1. Access Check: Must have access to the document
    if not check_document_access(document, current_user, db):
        log_audit_event(
            action=AuditEventType.ACCESS_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason=f"Access forbidden: You do not have permission to access document #{document_id}",
            metadata={"attempted_action": "EXTRACT_METADATA", "version_identifier": str(version_identifier)},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: You do not have permission to access document #{document_id}",
        )

    # 2. RBAC Guard: Only Owner or Admin can trigger extraction
    if not check_document_ownership(document, current_user):
        log_audit_event(
            action=AuditEventType.ACTION_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason="Access forbidden: Only the document owner or an administrator can trigger AI metadata extraction.",
            metadata={"attempted_action": "EXTRACT_METADATA", "version_identifier": str(version_identifier)},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Only the document owner or an administrator can trigger AI metadata extraction.",
        )

    # 3. Locate exact DocumentVersion
    version = find_document_version(document_id, version_identifier, db)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version '{version_identifier}' not found for document #{document_id}",
        )

    # 4. Check Cache (if force != True)
    existing_meta = db.query(DocumentVersionMetadata).filter(
        DocumentVersionMetadata.version_id == version.id
    ).first()

    if existing_meta and existing_meta.status == "COMPLETED" and existing_meta.source_hash == version.file_hash and not force:
        return format_version_metadata_response(
            existing_meta,
            document_id=document.id,
            version_id=version.id,
            version_number=version.version_number,
            source_hash=version.file_hash,
            is_owner_or_admin=True,
            cached=True,
        )

    # 5. Resolve File Path on disk
    file_path = get_version_file_path(version, document)
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stored document version file '{version.filename}' (v{version.version_number}) not found on disk",
        )

    # 6. Instantiate Extractor (Strictly validates provider configuration)
    try:
        extractor = AIExtractor()
    except AIConfigurationError as e:
        log_audit_event(
            db=db,
            action=AuditEventType.AI_METADATA_EXTRACTION_FAILED,
            result=AuditResult.FAILED,
            actor=current_user,
            document=document,
            version=version,
            version_number=version.version_number,
            reason=str(e),
            metadata={"status": "FAILED", "provider": "gemini"},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "AI_CONFIGURATION_ERROR",
                "message": str(e),
            },
        )

    # 7. Process extraction synchronously
    hint = {
        "filename": version.filename,
        "case_number": document.case_number,
    }
    metadata_dict, status_str, error_msg, duration_ms = extractor.process_document_version(
        file_path=file_path,
        file_type=version.file_type,
        document_hint=hint,
    )

    # 8. Upsert DocumentVersionMetadata record
    if not existing_meta:
        existing_meta = DocumentVersionMetadata(
            document_id=document.id,
            version_id=version.id,
            version_number=version.version_number,
            source_hash=version.file_hash,
            status=status_str,
            ai_provider=extractor.provider_name,
            ai_model=extractor.model_name,
            extraction_duration_ms=duration_ms,
            error_message=error_msg,
        )
        db.add(existing_meta)
    else:
        existing_meta.status = status_str
        existing_meta.source_hash = version.file_hash
        existing_meta.ai_provider = extractor.provider_name
        existing_meta.ai_model = extractor.model_name
        existing_meta.extraction_duration_ms = duration_ms
        existing_meta.error_message = error_msg

    if metadata_dict:
        existing_meta.document_type = metadata_dict.get("document_type")
        existing_meta.case_number = metadata_dict.get("case_number")
        existing_meta.court = metadata_dict.get("court")
        existing_meta.jurisdiction = metadata_dict.get("jurisdiction")
        existing_meta.subject = metadata_dict.get("subject")
        existing_meta.parties_json = json.dumps(metadata_dict.get("parties", []))
        existing_meta.dates_json = json.dumps(metadata_dict.get("dates", []))
        existing_meta.keywords_json = json.dumps(metadata_dict.get("keywords", []))
        existing_meta.confidence_json = json.dumps(metadata_dict.get("confidence", {}))

    db.commit()
    db.refresh(existing_meta)

    # 9. Audit Logging (Strictly sanitized, NO raw text)
    if status_str == "COMPLETED":
        field_count = sum(
            1 for v in [
                existing_meta.document_type,
                existing_meta.case_number,
                existing_meta.court,
                existing_meta.jurisdiction,
                existing_meta.subject,
            ] if v
        ) + (len(json.loads(existing_meta.parties_json)) if existing_meta.parties_json else 0) \
          + (len(json.loads(existing_meta.dates_json)) if existing_meta.dates_json else 0)

        log_audit_event(
            db=db,
            action=AuditEventType.AI_METADATA_EXTRACTED,
            result=AuditResult.SUCCESS,
            actor=current_user,
            document=document,
            version=version,
            version_number=version.version_number,
            metadata={
                "provider": extractor.provider_name,
                "model": extractor.model_name,
                "duration_ms": duration_ms,
                "fields_extracted": field_count,
                "document_type": existing_meta.document_type,
                "cached": False,
            },
        )
    else:
        audit_res = AuditResult.UNAVAILABLE if status_str == "EXTRACTION_UNAVAILABLE" else AuditResult.FAILED
        log_audit_event(
            db=db,
            action=AuditEventType.AI_METADATA_EXTRACTION_FAILED,
            result=audit_res,
            actor=current_user,
            document=document,
            version=version,
            version_number=version.version_number,
            reason=error_msg,
            metadata={
                "provider": extractor.provider_name,
                "model": extractor.model_name,
                "duration_ms": duration_ms,
                "status": status_str,
            },
        )

    return format_version_metadata_response(
        existing_meta,
        document_id=document.id,
        version_id=version.id,
        version_number=version.version_number,
        source_hash=version.file_hash,
        is_owner_or_admin=True,
        cached=False,
    )


@app.get("/documents/{document_id}/versions/{version_identifier}/metadata", response_model=DocumentVersionMetadataResponse)
def get_document_version_metadata(
    document_id: int,
    version_identifier: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieves existing AI-extracted metadata for a specific document version."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database",
        )

    if not check_document_access(document, current_user, db):
        log_audit_event(
            action=AuditEventType.ACCESS_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason=f"Access forbidden: You do not have permission to view metadata for document #{document_id}",
            metadata={"attempted_action": "GET_VERSION_METADATA", "version_identifier": str(version_identifier)},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: You do not have permission to view metadata for document #{document_id}",
        )

    version = find_document_version(document_id, version_identifier, db)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version '{version_identifier}' not found for document #{document_id}",
        )

    is_owner_or_admin = check_document_ownership(document, current_user)
    meta = db.query(DocumentVersionMetadata).filter(
        DocumentVersionMetadata.version_id == version.id
    ).first()

    return format_version_metadata_response(
        meta,
        document_id=document.id,
        version_id=version.id,
        version_number=version.version_number,
        source_hash=version.file_hash,
        is_owner_or_admin=is_owner_or_admin,
        cached=False,
    )


@app.get("/documents/{document_id}/metadata", response_model=DocumentVersionMetadataResponse)
def get_document_master_metadata(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieves existing AI-extracted metadata for the current master version of a document."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database",
        )

    if not check_document_access(document, current_user, db):
        log_audit_event(
            action=AuditEventType.ACCESS_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason=f"Access forbidden: You do not have permission to view metadata for document #{document_id}",
            metadata={"attempted_action": "GET_DOCUMENT_METADATA"},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: You do not have permission to view metadata for document #{document_id}",
        )

    is_owner_or_admin = check_document_ownership(document, current_user)
    version = find_document_version(document_id, document.version or 1, db)
    if not version:
        return format_version_metadata_response(
            None,
            document_id=document.id,
            version_id=None,
            version_number=document.version or 1,
            source_hash=document.file_hash,
            is_owner_or_admin=is_owner_or_admin,
            cached=False,
        )

    meta = db.query(DocumentVersionMetadata).filter(
        DocumentVersionMetadata.version_id == version.id
    ).first()

    return format_version_metadata_response(
        meta,
        document_id=document.id,
        version_id=version.id,
        version_number=version.version_number,
        source_hash=version.file_hash,
        is_owner_or_admin=is_owner_or_admin,
        cached=False,
    )


@app.post("/documents/{document_id}/verify")
def verify_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database",
        )

    if not check_document_access(document, current_user, db):
        log_audit_event(
            action=AuditEventType.ACCESS_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason=f"Access forbidden: You do not have permission to verify document #{document_id}",
            metadata={"attempted_action": "VERIFY_DOCUMENT"},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: You do not have permission to verify document #{document_id}",
        )

    # Find the current active version record if available
    current_ver = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == document.id,
        DocumentVersion.version_number == (document.version or 1),
    ).first()

    file_path = get_version_file_path(current_ver, document)
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stored document file '{document.filename}' not found on disk",
        )

    with open(file_path, "rb") as f:
        current_hash = hashlib.sha256(f.read()).hexdigest()

    try:
        # First query version-specific on-chain key e.g. "1_v2"
        onchain_data = get_document_from_chain(f"{document.id}_v{document.version or 1}")
        if (not onchain_data.get("document_hash") or onchain_data.get("timestamp") == 0):
            try:
                base_chain = get_document_from_chain(str(document.id))
                if base_chain.get("document_hash") and base_chain.get("timestamp") != 0:
                    onchain_data = base_chain
            except Exception:
                pass
    except BlockchainUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "BLOCKCHAIN_UNAVAILABLE",
                "message": "Blockchain node is offline. Start the local Hardhat node.",
                "technical_details": str(e),
            },
        )
    except ContractUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "CONTRACT_UNAVAILABLE",
                "message": "LegalVault smart contract could not be found at the configured address.",
                "contract_address": CONTRACT_ADDRESS,
                "technical_details": str(e),
            },
        )
    except ConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "BLOCKCHAIN_UNAVAILABLE",
                "message": "Blockchain node is offline. Start the local Hardhat node.",
                "technical_details": str(e),
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "CONTRACT_UNAVAILABLE",
                "message": f"Failed to retrieve document proof from blockchain: {str(e)}",
                "technical_details": str(e),
            },
        )

    blockchain_hash = onchain_data.get("document_hash")
    timestamp = onchain_data.get("timestamp")

    # If document has no registered hash on this chain instance (e.g. after local chain reset)
    if not blockchain_hash or blockchain_hash == "" or timestamp == 0:
        log_audit_event(
            db=db,
            action=AuditEventType.BLOCKCHAIN_PROOF_UNAVAILABLE,
            result=AuditResult.UNAVAILABLE,
            actor=current_user,
            document=document,
            version_number=document.version or 1,
            reason="Blockchain proof unavailable on the currently connected chain",
        )
        return {
            "document_id": document.id,
            "filename": document.filename,
            "case_number": document.case_number,
            "uploaded_by": document.uploaded_by,
            "current_hash": current_hash,
            "blockchain_hash": None,
            "blockchain_status": document.blockchain_status,
            "verified": False,
            "result": "BLOCKCHAIN_PROOF_UNAVAILABLE",
            "message": "This document exists in the local repository, but its blockchain proof is unavailable on the currently connected chain. The local development chain may have been reset.",
            "blockchain_tx_hash": document.blockchain_tx_hash,
            "contract_address": CONTRACT_ADDRESS,
            "owner": None,
            "timestamp": None,
            "version": document.version or 1,
        }

    is_verified = (current_hash.lower() == blockchain_hash.lower())
    result_text = "VERIFIED" if is_verified else "TAMPERED"

    if is_verified:
        log_audit_event(
            db=db,
            action=AuditEventType.DOCUMENT_VERIFIED,
            result=AuditResult.VERIFIED,
            actor=current_user,
            document=document,
            version_number=document.version or 1,
            metadata={"timestamp": timestamp},
        )
    else:
        log_audit_event(
            db=db,
            action=AuditEventType.DOCUMENT_TAMPERED,
            result=AuditResult.TAMPERED,
            actor=current_user,
            document=document,
            version_number=document.version or 1,
            reason=f"Master hash mismatch against on-chain anchor (Version v{document.version or 1})",
            metadata={"current_hash": current_hash, "blockchain_hash": blockchain_hash},
        )

    return {
        "document_id": document.id,
        "filename": document.filename,
        "case_number": document.case_number,
        "uploaded_by": document.uploaded_by,
        "current_hash": current_hash,
        "blockchain_hash": blockchain_hash,
        "blockchain_status": document.blockchain_status,
        "verified": is_verified,
        "result": result_text,
        "blockchain_tx_hash": document.blockchain_tx_hash,
        "contract_address": CONTRACT_ADDRESS,
        "owner": onchain_data.get("owner"),
        "timestamp": onchain_data.get("timestamp"),
        "version": onchain_data.get("version") or (document.version or 1),
    }


# --- Sharing Endpoints ---

@app.post("/documents/{document_id}/share")
def share_document(
    document_id: int,
    req: ShareRequest,
    current_user: User = Depends(require_roles(UserRole.LAWYER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found",
        )

    if not check_document_ownership(document, current_user):
        log_audit_event(
            action=AuditEventType.ACTION_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason="Access forbidden: You can only share documents you own.",
            metadata={"attempted_action": "SHARE_DOCUMENT"},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You can only share documents you own.",
        )

    target_user = None
    if req.shared_with_user_id:
        target_user = db.query(User).filter(User.id == req.shared_with_user_id).first()
    elif req.email:
        target_user = db.query(User).filter(User.email == req.email.lower().strip()).first()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target recipient user not found.",
        )

    if target_user.role not in [UserRole.JUDGE, UserRole.CLIENT]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Documents can only be shared with JUDGE or CLIENT accounts (target role is {target_user.role}).",
        )

    if target_user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot share a document with yourself.",
        )

    # Check for duplicate active share
    existing_share = db.query(DocumentShare).filter(
        DocumentShare.document_id == document.id,
        DocumentShare.shared_with_user_id == target_user.id,
    ).first()

    if existing_share:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document is already shared with {target_user.name} ({target_user.email}).",
        )

    share = DocumentShare(
        document_id=document.id,
        shared_with_user_id=target_user.id,
        shared_by_user_id=current_user.id,
    )
    db.add(share)
    db.commit()
    db.refresh(share)

    # Audit log for document sharing
    log_audit_event(
        db=db,
        action=AuditEventType.DOCUMENT_SHARED,
        result=AuditResult.SUCCESS,
        actor=current_user,
        document=document,
        metadata={
            "shared_with_user_id": target_user.id,
            "shared_with_name": target_user.name,
            "shared_with_email": target_user.email,
            "shared_with_role": target_user.role,
        },
    )

    return {
        "id": share.id,
        "document_id": document.id,
        "shared_with_user_id": target_user.id,
        "shared_with_name": target_user.name,
        "shared_with_email": target_user.email,
        "shared_with_role": target_user.role,
        "shared_by_user_id": current_user.id,
        "shared_by_name": current_user.name,
        "created_at": format_utc_iso(share.created_at),
    }


@app.get("/documents/{document_id}/shares")
def get_document_shares(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found",
        )

    if not check_document_ownership(document, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You can only view shares for documents you own.",
        )

    shares = db.query(DocumentShare).filter(DocumentShare.document_id == document_id).all()
    result = []
    for s in shares:
        target = db.query(User).filter(User.id == s.shared_with_user_id).first()
        creator = db.query(User).filter(User.id == s.shared_by_user_id).first()
        result.append({
            "id": s.id,
            "document_id": s.document_id,
            "shared_with_user_id": s.shared_with_user_id,
            "shared_with_name": target.name if target else "Unknown",
            "shared_with_email": target.email if target else "Unknown",
            "shared_with_role": target.role if target else "Unknown",
            "shared_by_user_id": s.shared_by_user_id,
            "shared_by_name": creator.name if creator else "Unknown",
            "created_at": format_utc_iso(s.created_at),
        })
    return result


@app.delete("/documents/{document_id}/shares/{share_id}")
def revoke_document_share(
    document_id: int,
    share_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found",
        )

    if not check_document_ownership(document, current_user):
        log_audit_event(
            action=AuditEventType.ACTION_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason="Access forbidden: You can only revoke shares for documents you own.",
            metadata={"attempted_action": "REVOKE_SHARE", "share_id": share_id},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You can only revoke shares for documents you own.",
        )

    share = db.query(DocumentShare).filter(
        DocumentShare.id == share_id,
        DocumentShare.document_id == document_id,
    ).first()

    if not share:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Share with ID {share_id} not found for document #{document_id}",
        )

    revoked_user_id = share.shared_with_user_id
    db.delete(share)
    db.commit()

    # Audit log for share revocation
    log_audit_event(
        db=db,
        action=AuditEventType.DOCUMENT_SHARE_REVOKED,
        result=AuditResult.SUCCESS,
        actor=current_user,
        document=document,
        metadata={
            "share_id": share_id,
            "revoked_user_id": revoked_user_id,
        },
    )

    return {
        "message": "Share revoked successfully",
        "share_id": share_id,
        "document_id": document_id,
    }


# --- Admin Development Utilities ---

@app.post("/admin/dev/reset-vault", response_model=ResetVaultResponse)
def dev_reset_vault(
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Development-only vault reset endpoint:
    - Strictly preserves the users table and seeded accounts
    - Deletes all document_shares records
    - Deletes all document records
    - Deletes all uploaded files in backend/uploads while preserving directory
    - Clears existing audit records and records a single surviving VAULT_RESET event
    - Rejects execution if LEGALVAULT_ENV is set to production
    """
    current_env = os.getenv("LEGALVAULT_ENV", "development").strip().lower()
    if current_env == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development vault reset is strictly forbidden when LEGALVAULT_ENV is set to production.",
        )

    # 1. Delete document metadata, versions, and shares first (maintains foreign key integrity)
    meta_count = db.query(DocumentVersionMetadata).count()
    db.query(DocumentVersionMetadata).delete()
    versions_count = db.query(DocumentVersion).count()
    db.query(DocumentVersion).delete()
    shares_count = db.query(DocumentShare).count()
    db.query(DocumentShare).delete()

    # 2. Delete all documents
    docs_count = db.query(Document).count()
    db.query(Document).delete()

    # 3. Clear existing audit records before creating the surviving reset event
    audit_count = db.query(AuditLog).count()
    db.query(AuditLog).delete()

    db.commit()

    # 4. Delete all files in uploads directory while preserving the folder
    files_deleted = 0
    if os.path.exists(UPLOAD_DIR):
        for filename in os.listdir(UPLOAD_DIR):
            file_path = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                    files_deleted += 1
                except Exception:
                    pass

    # 5. Create fresh VAULT_RESET audit log that survives the reset
    log_audit_event(
        db=db,
        action=AuditEventType.VAULT_RESET,
        result=AuditResult.SUCCESS,
        actor=current_user,
        reason="Development vault reset executed by Administrator",
        metadata={
            "documents_deleted": docs_count,
            "versions_deleted": versions_count,
            "shares_deleted": shares_count,
            "metadata_deleted": meta_count,
            "files_deleted": files_deleted,
        },
    )

    return {
        "message": "Development vault reset successfully. All documents, shares, and off-chain files have been cleared while preserving users.",
        "documents_deleted": docs_count,
        "shares_deleted": shares_count,
        "files_deleted": files_deleted,
        "audit_records_cleared": audit_count,
    }


# --- Audit Trail Endpoints ---

@app.get("/documents/{document_id}/audit", response_model=DocumentAuditResponse)
def get_document_audit_trail(
    document_id: int,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    version_number: int | None = None,
    result: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieves the forensic audit trail for a specific legal document.
    Enforces strict access control:
    - Document Owners (Lawyers) & Administrators have access.
    - Judicial & Client users have access ONLY IF the document is actively shared with them.
    - Unauthorized users receive 403 Forbidden with zero information leakage.
    - Sensitive login IP/auth metadata is hidden in document-level views.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database",
        )

    if not check_document_access(document, current_user, db):
        log_audit_event(
            action=AuditEventType.ACCESS_DENIED,
            result=AuditResult.DENIED,
            actor=current_user,
            document=document,
            reason=f"Access forbidden: You do not have permission to view the audit trail for document #{document_id}",
            metadata={"attempted_action": "VIEW_DOCUMENT_AUDIT"},
            isolated=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: You do not have permission to view the audit trail for document #{document_id}",
        )

    query = db.query(AuditLog).filter(AuditLog.document_id == document_id)

    if action:
        query = query.filter(AuditLog.action == action.strip().upper())
    if version_number is not None:
        query = query.filter(AuditLog.version_number == version_number)
    if result:
        query = query.filter(AuditLog.result == result.strip().upper())

    total_count = query.count()
    events = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()

    formatted_events = [
        format_audit_event_response(e, is_system_view=False)
        for e in events
    ]

    return {
        "document_id": document_id,
        "total_count": total_count,
        "events": formatted_events,
    }


@app.get("/audit", response_model=SystemAuditResponse)
def get_system_audit_trail(
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    actor_id: int | None = None,
    document_id: int | None = None,
    result: str | None = None,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Retrieves system-wide forensic audit logs across all users, dockets, and events.
    - Strictly restricted to ADMIN role.
    - Includes actor emails and IP addresses for security forensics.
    """
    query = db.query(AuditLog)

    if action:
        query = query.filter(AuditLog.action == action.strip().upper())
    if actor_id is not None:
        query = query.filter(AuditLog.actor_id == actor_id)
    if document_id is not None:
        query = query.filter(AuditLog.document_id == document_id)
    if result:
        query = query.filter(AuditLog.result == result.strip().upper())

    total_count = query.count()
    events = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()

    formatted_events = [
        format_audit_event_response(e, is_system_view=True)
        for e in events
    ]

    return {
        "total_count": total_count,
        "events": formatted_events,
    }


# --- Admin Dashboard Overview Endpoint ---

@app.get("/admin/dashboard", response_model=AdminDashboardResponse)
def get_admin_dashboard(
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Centralized administrative and forensic overview endpoint.
    - Strictly restricted to ADMIN role.
    - Performs server-side SQL aggregation across users, documents, versions, shares, audit events, and blockchain health.
    - Correctly calculates current integrity state based on the latest authoritative verification outcome per document.
    - Sanitizes blockchain info (no private keys or full RPC URLs exposed).
    """
    # 1. System Overview Metrics
    total_docs = db.query(Document).count()
    total_versions = db.query(DocumentVersion).count()
    total_size = db.query(func.coalesce(func.sum(DocumentVersion.file_size), 0)).scalar() or 0
    total_users = db.query(User).count()

    role_counts = {r: 0 for r in UserRole.ALL}
    for r, cnt in db.query(User.role, func.count(User.id)).group_by(User.role).all():
        role_counts[r] = cnt

    total_shares = db.query(DocumentShare).count()
    shared_docs_count = db.query(func.count(func.distinct(DocumentShare.document_id))).scalar() or 0

    system_overview = SystemOverviewStats(
        total_documents=total_docs,
        total_versions=total_versions,
        total_file_size_bytes=int(total_size),
        total_users=total_users,
        users_by_role=role_counts,
        total_active_shares=total_shares,
        shared_documents_count=int(shared_docs_count),
    )

    # 2. Authoritative Current Integrity State & Attention Documents
    # Query verification events in chronological order to find the latest state per document / version
    verification_actions = [
        AuditEventType.DOCUMENT_VERIFIED,
        AuditEventType.VERSION_VERIFIED,
        AuditEventType.DOCUMENT_TAMPERED,
        AuditEventType.VERSION_TAMPERED,
        AuditEventType.BLOCKCHAIN_PROOF_UNAVAILABLE,
    ]

    all_ver_logs = (
        db.query(AuditLog)
        .filter(AuditLog.action.in_(verification_actions))
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        .all()
    )

    # Map: document_id -> latest verification event
    # Map: (document_id, version_number) -> latest verification event
    latest_doc_ver_events: dict[int, AuditLog] = {}
    latest_version_events: dict[tuple[int, int], AuditLog] = {}

    for log in all_ver_logs:
        if log.document_id is not None:
            latest_doc_ver_events[log.document_id] = log
            if log.version_number is not None:
                latest_version_events[(log.document_id, log.version_number)] = log

    # Check all existing documents and their versions
    all_documents = db.query(Document).all()
    verified_doc_ids = set()
    tampered_doc_ids = set()
    proof_unavail_doc_ids = set()
    attention_docs_list: list[AttentionDocumentItem] = []

    for doc in all_documents:
        doc_has_tamper = False
        doc_has_unavail = False
        doc_has_missing_file = False
        doc_has_verified = False

        versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).all()

        # Check version by version
        for v in versions:
            v_file_path = os.path.join(UPLOAD_DIR, v.stored_filename) if v.stored_filename else None
            if not v_file_path or not os.path.exists(v_file_path):
                doc_has_missing_file = True
                attention_docs_list.append(
                    AttentionDocumentItem(
                        document_id=doc.id,
                        filename=v.filename or doc.filename,
                        case_number=doc.case_number,
                        version_number=v.version_number,
                        issue_type="MISSING_FILE",
                        detected_at=format_utc_iso(v.created_at),
                        reason=f"Stored off-chain file '{v.stored_filename}' missing on disk",
                    )
                )
                continue

            # Look up latest version-specific verification
            v_latest = latest_version_events.get((doc.id, v.version_number))
            if v_latest:
                if v_latest.result == AuditResult.TAMPERED or v_latest.action in [
                    AuditEventType.VERSION_TAMPERED,
                    AuditEventType.DOCUMENT_TAMPERED,
                ]:
                    doc_has_tamper = True
                    attention_docs_list.append(
                        AttentionDocumentItem(
                            document_id=doc.id,
                            filename=v.filename or doc.filename,
                            case_number=doc.case_number,
                            version_number=v.version_number,
                            issue_type="TAMPERED",
                            detected_at=format_utc_iso(v_latest.created_at),
                            reason=v_latest.reason or "Cryptographic SHA-256 hash mismatch detected against blockchain anchor",
                        )
                    )
                elif v_latest.result == AuditResult.UNAVAILABLE or v_latest.action == AuditEventType.BLOCKCHAIN_PROOF_UNAVAILABLE:
                    doc_has_unavail = True
                    attention_docs_list.append(
                        AttentionDocumentItem(
                            document_id=doc.id,
                            filename=v.filename or doc.filename,
                            case_number=doc.case_number,
                            version_number=v.version_number,
                            issue_type="PROOF_UNAVAILABLE",
                            detected_at=format_utc_iso(v_latest.created_at),
                            reason=v_latest.reason or "Blockchain proof missing or smart contract record unreachable",
                        )
                    )
                elif v_latest.result in [AuditResult.VERIFIED, AuditResult.SUCCESS]:
                    doc_has_verified = True

        # If document had a whole-document verification that was latest and not captured by versions
        if not versions and doc.id in latest_doc_ver_events:
            doc_latest = latest_doc_ver_events[doc.id]
            if doc_latest.result == AuditResult.TAMPERED:
                doc_has_tamper = True
                attention_docs_list.append(
                    AttentionDocumentItem(
                        document_id=doc.id,
                        filename=doc.filename,
                        case_number=doc.case_number,
                        version_number=doc.version or 1,
                        issue_type="TAMPERED",
                        detected_at=format_utc_iso(doc_latest.created_at),
                        reason=doc_latest.reason or "Master document integrity check failed",
                    )
                )
            elif doc_latest.result == AuditResult.UNAVAILABLE:
                doc_has_unavail = True
                attention_docs_list.append(
                    AttentionDocumentItem(
                        document_id=doc.id,
                        filename=doc.filename,
                        case_number=doc.case_number,
                        version_number=doc.version or 1,
                        issue_type="PROOF_UNAVAILABLE",
                        detected_at=format_utc_iso(doc_latest.created_at),
                        reason=doc_latest.reason or "Proof unavailable",
                    )
                )
            elif doc_latest.result in [AuditResult.VERIFIED, AuditResult.SUCCESS]:
                doc_has_verified = True

        # Categorize unique document
        if doc_has_tamper or doc_has_missing_file:
            tampered_doc_ids.add(doc.id)
        elif doc_has_unavail:
            proof_unavail_doc_ids.add(doc.id)
        elif doc_has_verified:
            verified_doc_ids.add(doc.id)

    integrity_overview = IntegrityOverviewStats(
        verified_documents=len(verified_doc_ids),
        tampered_documents=len(tampered_doc_ids),
        proof_unavailable_documents=len(proof_unavail_doc_ids),
        attention_required_count=len(attention_docs_list),
    )

    # 3. Security Threat Overview (24h Window & All-Time)
    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    failed_logins_all = db.query(AuditLog).filter(AuditLog.action == AuditEventType.LOGIN_FAILED).count()
    failed_logins_24h = (
        db.query(AuditLog)
        .filter(AuditLog.action == AuditEventType.LOGIN_FAILED, AuditLog.created_at >= cutoff_24h)
        .count()
    )

    access_denied_all = db.query(AuditLog).filter(AuditLog.action == AuditEventType.ACCESS_DENIED).count()
    access_denied_24h = (
        db.query(AuditLog)
        .filter(AuditLog.action == AuditEventType.ACCESS_DENIED, AuditLog.created_at >= cutoff_24h)
        .count()
    )

    action_denied_all = db.query(AuditLog).filter(AuditLog.action == AuditEventType.ACTION_DENIED).count()
    action_denied_24h = (
        db.query(AuditLog)
        .filter(AuditLog.action == AuditEventType.ACTION_DENIED, AuditLog.created_at >= cutoff_24h)
        .count()
    )

    security_overview = SecurityOverviewStats(
        window_hours=24,
        failed_logins_24h=failed_logins_24h,
        failed_logins_all_time=failed_logins_all,
        access_denied_24h=access_denied_24h,
        access_denied_all_time=access_denied_all,
        action_denied_24h=action_denied_24h,
        action_denied_all_time=action_denied_all,
    )

    # 4. Blockchain & Custody Overview
    is_connected = False
    chain_id = None
    network_name = "Local EVM"
    try:
        w3, contract = get_web3_and_contract()
        is_connected = w3.is_connected()
        if is_connected:
            chain_id = w3.eth.chain_id
            if chain_id == 31337 or chain_id == 1337:
                network_name = "Local Hardhat / Anvil EVM"
            elif chain_id == 11155111:
                network_name = "Ethereum Sepolia Testnet"
            elif chain_id == 1:
                network_name = "Ethereum Mainnet"
            else:
                network_name = f"EVM Chain (ID: {chain_id})"
    except Exception:
        is_connected = False
        chain_id = None
        network_name = "Offline / Unreachable"

    anchored_versions_count = (
        db.query(DocumentVersion).filter(DocumentVersion.blockchain_status == "confirmed").count()
    )
    pending_versions_count = (
        db.query(DocumentVersion)
        .filter((DocumentVersion.blockchain_status != "confirmed") | (DocumentVersion.blockchain_status == None))
        .count()
    )

    latest_ver = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.blockchain_status == "confirmed")
        .order_by(DocumentVersion.created_at.desc())
        .first()
    )
    latest_anchor_tx = latest_ver.blockchain_tx_hash if latest_ver else None
    latest_anchor_time = format_utc_iso(latest_ver.created_at) if latest_ver else None

    blockchain_overview = BlockchainOverviewStats(
        is_connected=is_connected,
        chain_id=chain_id,
        network_name=network_name,
        contract_address=CONTRACT_ADDRESS,
        anchored_versions_count=anchored_versions_count,
        pending_versions_count=pending_versions_count,
        latest_anchor_tx=latest_anchor_tx,
        latest_anchor_time=latest_anchor_time,
    )

    # 5. Recent Activity (Recent 10 Events)
    recent_logs = db.query(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(10).all()
    recent_activity = [format_audit_event_response(e, is_system_view=True) for e in recent_logs]

    return AdminDashboardResponse(
        system_overview=system_overview,
        integrity_overview=integrity_overview,
        security_overview=security_overview,
        blockchain_overview=blockchain_overview,
        attention_documents=attention_docs_list,
        recent_activity=recent_activity,
        generated_at=format_utc_iso(datetime.now(timezone.utc)),
    )