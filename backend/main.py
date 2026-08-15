from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session
import shutil
import os
import hashlib

from database import engine, Base, SessionLocal, migrate_schema
from models import Document
from blockchain import register_document_on_chain, get_document_from_chain

Base.metadata.create_all(bind=engine)
migrate_schema()

app = FastAPI(title="LegalVault API")

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
def home():
    return {
        "message": "LegalVault API is running"
    }


@app.post("/documents/upload")
def upload_document(
    file: UploadFile = File(...),
    case_number: str = Form(...),
    uploaded_by: str = Form(...),
    db: Session = Depends(get_db)
):
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    with open(file_path, "rb") as uploaded_file:
        file_hash = hashlib.sha256(uploaded_file.read()).hexdigest()

    document = Document(
        filename=file.filename,
        case_number=case_number,
        uploaded_by=uploaded_by,
        file_hash=file_hash
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
def verify_document(document_id: int, db: Session = Depends(get_db)):
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=404,
            detail=f"Document with ID {document_id} not found in database",
        )

    file_path = os.path.join(UPLOAD_DIR, document.filename)
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail=f"Stored document file '{document.filename}' not found on disk",
        )

    with open(file_path, "rb") as f:
        current_hash = hashlib.sha256(f.read()).hexdigest()

    try:
        onchain_data = get_document_from_chain(str(document.id))
    except ConnectionError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Blockchain service unavailable: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to retrieve document from blockchain: {str(e)}",
        )

    blockchain_hash = onchain_data.get("document_hash")
    if not blockchain_hash:
        raise HTTPException(
            status_code=404,
            detail=f"Document ID {document_id} is not registered on the blockchain",
        )

    is_verified = (current_hash.lower() == blockchain_hash.lower())
    result_text = "VERIFIED" if is_verified else "TAMPERED"

    return {
        "document_id": document.id,
        "filename": document.filename,
        "current_hash": current_hash,
        "blockchain_hash": blockchain_hash,
        "blockchain_status": document.blockchain_status,
        "verified": is_verified,
        "result": result_text,
    }