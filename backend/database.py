from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./legalvault.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def migrate_schema() -> None:
    import os
    from datetime import datetime, timezone

    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    if "documents" in table_names:
        existing_columns = {column["name"] for column in inspector.get_columns("documents")}
        migrations = {
            "blockchain_tx_hash": "ALTER TABLE documents ADD COLUMN blockchain_tx_hash VARCHAR",
            "blockchain_status": "ALTER TABLE documents ADD COLUMN blockchain_status VARCHAR",
            "owner_id": "ALTER TABLE documents ADD COLUMN owner_id INTEGER",
        }

        with engine.begin() as connection:
            for column_name, statement in migrations.items():
                if column_name not in existing_columns:
                    connection.execute(text(statement))

    # Ensure document_version_metadata, document_version_summaries, document_version_comparisons, and timeline tables exist
    if "document_version_metadata" not in table_names:
        from models import DocumentVersionMetadata
        DocumentVersionMetadata.__table__.create(bind=engine, checkfirst=True)

    if "document_version_summaries" not in table_names:
        from models import DocumentVersionSummary
        DocumentVersionSummary.__table__.create(bind=engine, checkfirst=True)

    if "document_version_comparisons" not in table_names:
        from models import DocumentVersionComparison
        DocumentVersionComparison.__table__.create(bind=engine, checkfirst=True)

    if "document_version_timelines" not in table_names:
        from models import DocumentVersionTimeline
        DocumentVersionTimeline.__table__.create(bind=engine, checkfirst=True)

    if "document_version_timeline_events" not in table_names:
        from models import DocumentVersionTimelineEvent
        DocumentVersionTimelineEvent.__table__.create(bind=engine, checkfirst=True)

    # Backfill legacy documents into document_versions purely off-chain (no blockchain calls)
    if "document_versions" in inspector.get_table_names() and "documents" in inspector.get_table_names():
        from models import Document, DocumentVersion
        db = SessionLocal()
        try:
            documents = db.query(Document).all()
            for doc in documents:
                existing_ver = db.query(DocumentVersion).filter(
                    DocumentVersion.document_id == doc.id,
                    DocumentVersion.version_number == (doc.version or 1),
                ).first()

                if not existing_ver:
                    # Determine file size if file is available on disk
                    file_size = 0
                    upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
                    fpath = os.path.join(upload_dir, doc.filename) if doc.filename else None
                    if fpath and os.path.exists(fpath):
                        try:
                            file_size = os.path.getsize(fpath)
                        except Exception:
                            file_size = 0

                    ext = os.path.splitext(doc.filename)[1].lower() if doc.filename else None

                    v1 = DocumentVersion(
                        document_id=doc.id,
                        version_number=doc.version or 1,
                        filename=doc.filename,
                        stored_filename=doc.filename,
                        file_size=file_size,
                        file_type=ext,
                        file_hash=doc.file_hash or "",
                        uploaded_by=doc.uploaded_by or "Unknown",
                        uploader_id=doc.owner_id,
                        blockchain_tx_hash=doc.blockchain_tx_hash,
                        blockchain_status=doc.blockchain_status or "pending",
                        created_at=doc.created_at or datetime.now(timezone.utc),
                    )
                    db.add(v1)
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[DB MIGRATION WARNING] Failed backfilling legacy document versions: {e}")
        finally:
            db.close()


def seed_initial_users() -> None:
    from models import User, UserRole
    from auth import hash_password

    seed_data = [
        {
            "name": "Advocate Rajesh Sharma",
            "email": "lawyer@legalvault.local",
            "password": "lawyer123",
            "role": UserRole.LAWYER,
        },
        {
            "name": "Advocate Priya Patel",
            "email": "lawyer2@legalvault.local",
            "password": "lawyer123",
            "role": UserRole.LAWYER,
        },
        {
            "name": "Hon. Justice P. N. Rao",
            "email": "judge@legalvault.local",
            "password": "judge123",
            "role": UserRole.JUDGE,
        },
        {
            "name": "Vikramaditya Industries Ltd.",
            "email": "client@legalvault.local",
            "password": "client123",
            "role": UserRole.CLIENT,
        },
        {
            "name": "Chief Registrar / Vault Admin",
            "email": "admin@legalvault.local",
            "password": "admin123",
            "role": UserRole.ADMIN,
        },
    ]

    db = SessionLocal()
    try:
        for item in seed_data:
            existing = db.query(User).filter(User.email == item["email"]).first()
            if not existing:
                user = User(
                    name=item["name"],
                    email=item["email"],
                    password_hash=hash_password(item["password"]),
                    role=item["role"],
                )
                db.add(user)
        db.commit()
    finally:
        db.close()
