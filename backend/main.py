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
from models import Document, User, UserRole, DocumentShare
from blockchain import register_document_on_chain, get_document_from_chain, CONTRACT_ADDRESS
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

    return {
        "id": document.id,
        "filename": document.filename,
        "case_number": document.case_number,
        "uploaded_by": document.uploaded_by,
        "file_hash": document.file_hash,
        "version": document.version,
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

    file_path = os.path.join(UPLOAD_DIR, document.filename)
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
    current_user: User = Depends(require_roles(UserRole.LAWYER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    with open(file_path, "rb") as uploaded_file:
        file_hash = hashlib.sha256(uploaded_file.read()).hexdigest()

    document = Document(
        filename=file.filename,
        case_number=case_number,
        uploaded_by=uploaded_by or current_user.name,
        owner_id=current_user.id,
        file_hash=file_hash,
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    blockchain_tx_hash = None
    blockchain_status = "failed"

    try:
        chain_result = register_document_on_chain(
            document_id=str(document.id),
            document_hash=file_hash,
            version=document.version,
        )
        blockchain_tx_hash = chain_result["blockchain_tx_hash"]
        blockchain_status = chain_result["blockchain_status"]
    except Exception:
        blockchain_status = "failed"

    document.blockchain_tx_hash = blockchain_tx_hash
    document.blockchain_status = blockchain_status
    db.commit()
    db.refresh(document)

    return {
        "message": "Document uploaded successfully",
        "document_id": document.id,
        "filename": document.filename,
        "file_hash": file_hash,
        "blockchain_tx_hash": document.blockchain_tx_hash,
        "blockchain_status": document.blockchain_status,
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

    file_path = os.path.join(UPLOAD_DIR, document.filename)
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stored document file '{document.filename}' not found on disk",
        )

    with open(file_path, "rb") as f:
        current_hash = hashlib.sha256(f.read()).hexdigest()

    try:
        onchain_data = get_document_from_chain(str(document.id))
    except ConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Blockchain service unavailable: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to retrieve document from blockchain: {str(e)}",
        )

    blockchain_hash = onchain_data.get("document_hash")
    if not blockchain_hash:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document ID {document_id} is not registered on the blockchain",
        )

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
        "version": onchain_data.get("version"),
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

    # 1. Delete document shares first (maintains foreign key integrity)
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