import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from syft_event import SyftEvents
from syft_core import Client

from .database import init_database
from .router import chat_router

def create_chat_app(client=None, db_path="chat_messages.db") -> SyftEvents:
    """Create the SyftEvents application with SQLAlchemy database connection."""
    if client is None:
        client = Client.load()
        
    app = SyftEvents("syft_chat", client=client)
    
    # Create database directory if it doesn't exist
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)
    
    # Initialize SQLAlchemy engine and session
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Initialize database schema
    init_database(engine)
    
    # Store session and client email in app state
    app.state["db_session"] = session
    app.state["db_engine"] = engine
    app.state["client_email"] = client.email
    app.state["message_listeners"] = []
    
    # Include the chat router
    app.include_router(chat_router)
    
    return app 