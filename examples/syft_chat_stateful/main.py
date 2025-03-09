#!/usr/bin/env python3
from __future__ import annotations

import argparse
from syft_core import Client

from .server import create_chat_app

def main():
    """Run as a standalone server (useful for debugging)"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Stateful Syft Chat Server")
    parser.add_argument(
        "--config", "-c", 
        type=str, 
        help="Path to a custom config.json file"
    )
    parser.add_argument(
        "--db", "-d",
        type=str,
        default="chat_messages.db",
        help="Path to SQLite database file"
    )
    args = parser.parse_args()
    
    # Initialize client with config if provided
    client = Client.load(args.config)
    print(f"Running as user: {client.email}")
    
    app = create_chat_app(client, args.db)
    
    try:
        print("Running Stateful Syft Chat server:", app.app_rpc_dir)
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