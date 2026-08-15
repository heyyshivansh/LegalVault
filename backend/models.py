from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

from database import Base


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
    created_at = Column(DateTime, default=datetime.utcnow)