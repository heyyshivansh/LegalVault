from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
import shutil
import os
import hashlib
from datetime import datetime

from database import engine, Base, SessionLocal, migrate_schema, seed_initial_users
from models import Document, User, UserRole, DocumentShare, DocumentVersion
from sqlalchemy.exc import IntegrityError
from blockchain import (
    register_document_on_chain,
    get_document_from_chain,
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
def login(req: LoginRequest, db: Session = Depends(get_db)):
    email_clean = req.email.lower().strip()
    user = db.query(User).filter(User.email == email_clean).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role}
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user,
    }


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
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
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
                    "created_at": doc.created_at.isoformat() if doc.created_at else None,
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
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
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
        "created_at": document.created_at.isoformat() if document.created_at else None,
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
                        "created_at": existing_doc.created_at.isoformat() if existing_doc.created_at else None,
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
                "created_at": document.created_at.isoformat() if document.created_at else None,
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
            "created_at": v.created_at.isoformat() if v.created_at else None,
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
        "created_at": version.created_at.isoformat() if version.created_at else None,
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
                        "created_at": existing_version.created_at.isoformat() if existing_version.created_at else None,
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
        "created_at": new_version.created_at.isoformat() if new_version.created_at else None,
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

    return {
        "id": share.id,
        "document_id": document.id,
        "shared_with_user_id": target_user.id,
        "shared_with_name": target_user.name,
        "shared_with_email": target_user.email,
        "shared_with_role": target_user.role,
        "shared_by_user_id": current_user.id,
        "shared_by_name": current_user.name,
        "created_at": share.created_at.isoformat() if share.created_at else None,
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
            "created_at": s.created_at.isoformat() if s.created_at else None,
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

    db.delete(share)
    db.commit()

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
    - Rejects execution if LEGALVAULT_ENV is set to production
    """
    current_env = os.getenv("LEGALVAULT_ENV", "development").strip().lower()
    if current_env == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development vault reset is strictly forbidden when LEGALVAULT_ENV is set to production.",
        )

    # 1. Delete document versions and shares first (maintains foreign key integrity)
    db.query(DocumentVersion).delete()
    shares_count = db.query(DocumentShare).count()
    db.query(DocumentShare).delete()

    # 2. Delete all documents
    docs_count = db.query(Document).count()
    db.query(Document).delete()

    db.commit()

    # 3. Delete all files in uploads directory while preserving the folder
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

    return {
        "message": "Development vault reset successfully. All documents, shares, and off-chain files have been cleared while preserving users.",
        "documents_deleted": docs_count,
        "shares_deleted": shares_count,
        "files_deleted": files_deleted,
    }