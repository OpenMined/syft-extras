import argparse
import os
from typing import List
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from syft_event import EventRouter, SyftEvents
from syft_core import Client

# SQLAlchemy imports
from sqlalchemy import create_engine, Column, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Create SQLAlchemy Base class for models
Base = declarative_base()

# Define the SQLAlchemy model for User
class UserModel(Base):
    __tablename__ = "users"
    
    uid = Column(String, primary_key=True)
    name = Column(String, nullable=False)


# Define Pydantic models for API requests/responses
class User(BaseModel):
    uid: UUID = Field(default_factory=uuid4)
    name: str


class UserList(BaseModel):
    users: List[User]


# Create a router for user-related API endpoints
user_router = EventRouter()


@user_router.on_request("/create")
def create_user(user: User, app: SyftEvents) -> User:
    session = app.state["db_session"]
    
    # Convert Pydantic model to SQLAlchemy model
    db_user = UserModel(uid=str(user.uid), name=user.name)
    
    # Add and commit to database
    session.add(db_user)
    session.commit()
    
    return user


@user_router.on_request("/get")
def get_user(uid: UUID, app: SyftEvents) -> User:
    session = app.state["db_session"]
    
    # Query the user by UID
    db_user = session.query(UserModel).filter(UserModel.uid == str(uid)).first()
    
    if db_user:
        return User(uid=UUID(db_user.uid), name=db_user.name)
    return None


@user_router.on_request("/delete")
def delete_user(uid: UUID, app: SyftEvents) -> User:
    session = app.state["db_session"]
    
    # First get the user to return
    user = get_user(uid, app)
    
    if user:
        # Delete the user
        db_user = session.query(UserModel).filter(UserModel.uid == str(uid)).first()
        session.delete(db_user)
        session.commit()
    
    return user


@user_router.on_request("/list")
def list_users(app: SyftEvents) -> UserList:
    session = app.state["db_session"]
    
    # Query all users
    db_users = session.query(UserModel).all()
    
    # Convert SQLAlchemy models to Pydantic models
    users = [User(uid=UUID(db_user.uid), name=db_user.name) for db_user in db_users]
    return UserList(users=users)


def init_database(engine):
    """Initialize the SQLite database schema."""
    # Create tables if they don't exist
    Base.metadata.create_all(engine)


def create_app(client=None, db_path="users.db") -> SyftEvents:
    """
    Create the SyftEvents application with SQLAlchemy database connection.
    """
    if client is None:
        client = Client.load()
        
    app = SyftEvents("my-crud-sql-app", client=client)
    
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
    
    # Store the session in the app state
    app.state["db_session"] = session
    app.state["db_engine"] = engine
    
    # Include the router with the "/user" prefix
    app.include_router(user_router, prefix="/user")
    
    return app


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="SQLite CRUD Server with SQLAlchemy")
    parser.add_argument(
        "--config", "-c", 
        type=str, 
        help="Path to a custom config.json file"
    )
    parser.add_argument(
        "--db", "-d",
        type=str,
        default="users.db",
        help="Path to SQLite database file"
    )
    args = parser.parse_args()
    
    # Initialize client with config if provided
    client = Client.load(args.config)
    print(f"Running as user: {client.email}")
    
    app = create_app(client, args.db)
    
    try:
        print("Running SQLite CRUD server with SQLAlchemy:", app.app_rpc_dir)
        app.run_forever()
    except KeyboardInterrupt:
        print("Server stopped.")
        # Close the database session
        if "db_session" in app.state:
            app.state["db_session"].close()
    except Exception as e:
        print(f"Error: {e}")
        # Close the database session
        if "db_session" in app.state:
            app.state["db_session"].close()


if __name__ == "__main__":
    main()
