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
    inspector = inspect(engine)
    if "documents" in inspector.get_table_names():
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
