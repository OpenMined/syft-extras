from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base

# Create SQLAlchemy Base class for models
Base = declarative_base()

class MessageModel(Base):
    """SQLAlchemy model for chat messages"""
    __tablename__ = "messages"
    
    msg_id = Column(String, primary_key=True)
    sender = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    thread_id = Column(String, nullable=True)
    reply_to = Column(String, nullable=True)
    meta_data = Column(Text, nullable=True)  # JSON serialized - renamed from metadata

def init_database(engine):
    """Initialize the SQLite database schema."""
    # Create tables if they don't exist
    Base.metadata.create_all(engine) 