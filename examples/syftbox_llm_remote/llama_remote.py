from __future__ import annotations

import httpx
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Set
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field, validator
from syft_event.types import Request

from syft_rpc_client import SyftRPCClient


# Configure logging based on environment
def configure_logging(verbose=True):
    """Configure logging based on the environment.
    
    Args:
        verbose: Whether to enable verbose logging regardless of environment
    """
    # Check if we're in a Jupyter notebook
    is_notebook = False
    try:
        # This will be defined in Jupyter/IPython environments
        shell = get_ipython().__class__.__name__
        if shell in ['ZMQInteractiveShell', 'TerminalInteractiveShell']:
            is_notebook = False
    except NameError:
        pass
    
    # Configure logger
    logger.remove()  # Remove all handlers
    
    if verbose or not is_notebook:
        # Full logging for command line or when verbose is requested
        logger.add(sys.stderr, level="DEBUG")
    else:
        # Minimal logging for notebooks (only errors and critical messages)
        logger.add(sys.stderr, level="ERROR")


# ----------------- Request/Response Models -----------------

class OllamaRequest(BaseModel):
    """Request to send to a remote Ollama instance."""
    model: str = Field(description="Name of the Ollama model to use")
    prompt: str = Field(description="The prompt text to send to the model")
    system: Optional[str] = Field(default=None, description="Optional system prompt")
    temperature: float = Field(default=0.7, description="Sampling temperature")
    max_tokens: Optional[int] = Field(default=None, description="Maximum tokens to generate")
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), 
                         description="Timestamp of the request")
    options: Optional[Dict[str, Any]] = Field(default=None, description="Additional Ollama options")
    files: Optional[List[str]] = Field(default=None, description="Files to include in context window")


class OllamaResponse(BaseModel):
    """Response from a remote Ollama instance."""
    model: str = Field(description="Model that generated the response")
    response: str = Field(description="Generated text response")
    error: Optional[str] = Field(default=None, description="Error message, if any")
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), 
                         description="Timestamp of the response")
    total_duration_ms: Optional[int] = Field(default=None, description="Processing time in milliseconds")
    
    @validator('error')
    def check_error(cls, v, values):
        if v and not values.get('response'):
            values['response'] = f"Error: {v}"
        return v


class FilePermissionRequest(BaseModel):
    """Request to set file permissions for a user."""
    user_email: str = Field(description="Email of the user to set permissions for")
    file_paths: List[str] = Field(description="List of file paths the user can execute against")
    operation: str = Field(description="Operation: 'add', 'remove', or 'set'")


class FilePermissionResponse(BaseModel):
    """Response for file permission operations."""
    user_email: str = Field(description="Email of the user permissions were modified for")
    allowed_files: List[str] = Field(description="Current list of allowed files for the user")
    success: bool = Field(description="Whether the operation was successful")
    error: Optional[str] = Field(default=None, description="Error message, if any")
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), 
                         description="Timestamp of the response")


# ----------------- Ollama Client Implementation -----------------

class OllamaClient(SyftRPCClient):
    """Client for sending prompts to remote Ollama instances."""
    
    def __init__(self, 
                 config_path: Optional[str] = None, 
                 ollama_url: str = "http://localhost:11434"):
        """Initialize the Ollama client."""
        super().__init__(
            config_path=config_path,
            app_name="ollama_remote",
            endpoint="/generate",
            request_model=OllamaRequest,
            response_model=OllamaResponse
        )
        self.ollama_url = ollama_url
        # Register the endpoint after the server has started
        self._register_file_permission_endpoint()
    
    def _create_server(self):
        """Create and return the SyftEvents server."""
        self.box = super()._create_server()
        return self.box
        
    def _register_file_permission_endpoint(self):
        """Register the file permission endpoints."""
        @self.box.on_request("/set_file_permissions")
        def file_permission_handler(request_data: dict, ctx: Request) -> dict:
            # Convert to model
            request = FilePermissionRequest(**request_data)
            response = self._handle_file_permission_request(request, ctx)
            return response.model_dump()
        
        @self.box.on_request("/list_file_permissions")
        def list_permissions_handler(request_data: dict, ctx: Request) -> dict:
            
            # Convert to model
            request = FilePermissionRequest(**request_data)
            response = self._list_file_permissions(request, ctx)
            return response.model_dump()
    
    def _handle_file_permission_request(self, request: FilePermissionRequest, ctx: Request) -> FilePermissionResponse:
        """Process an incoming file permission request using .syftperm_exe files."""
        logger.info(f"🔔 RECEIVED: File permission request for user '{request.user_email}'")
        
        try:
            user_email = request.user_email
            allowed_files = []
            
            for file_path in request.file_paths:
                # Get the permission file path
                file_path = Path(file_path)
                perm_file = file_path.parent / f"{file_path.name}.syftperm_exe"
                
                # Create parent directory if it doesn't exist
                file_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Initialize permissions dict
                permissions = {"allowed_users": []}
                
                # Read existing permissions if file exists
                if perm_file.exists():
                    try:
                        with open(perm_file, 'r') as f:
                            permissions = json.load(f)
                    except Exception as e:
                        logger.error(f"Error reading permission file {perm_file}: {e}")
                
                # Handle the operation
                current_users = set(permissions.get("allowed_users", []))
                
                if request.operation == "add":
                    current_users.add(user_email)
                elif request.operation == "remove":
                    current_users.discard(user_email)
                elif request.operation == "set":
                    # For "set", we handle one file at a time
                    current_users.add(user_email)
                else:
                    return FilePermissionResponse(
                        user_email=user_email,
                        allowed_files=allowed_files,
                        success=False,
                        error=f"Invalid operation: {request.operation}. Must be 'add', 'remove', or 'set'.",
                        ts=datetime.now(timezone.utc)
                    )
                
                # Update permissions
                permissions["allowed_users"] = list(current_users)
                
                # Write back to file
                try:
                    with open(perm_file, 'w') as f:
                        json.dump(permissions, f, indent=2)
                    
                    # If successful, add to allowed_files list
                    if user_email in current_users:
                        allowed_files.append(str(file_path))
                except Exception as e:
                    logger.error(f"Error writing permission file {perm_file}: {e}")
            
            return FilePermissionResponse(
                user_email=user_email,
                allowed_files=allowed_files,
                success=True,
                ts=datetime.now(timezone.utc)
            )
            
        except Exception as e:
            logger.error(f"Error processing file permission request: {e}")
            return FilePermissionResponse(
                user_email=request.user_email,
                allowed_files=[],
                success=False,
                error=str(e),
                ts=datetime.now(timezone.utc)
            )
    
    def _check_file_permission(self, user_email: str, file_path: str) -> bool:
        """Check if a user has permission to access a file using both .syftperm_exe files
        and standard Syft permissions."""
        try:
            # First, check for .syftperm_exe specific permissions
            path = Path(file_path)
            perm_file = path.parent / f"{path.name}.syftperm_exe"
            
            logger.debug(f"Checking permissions for user {user_email} on file {file_path}")
            
            # If .syftperm_exe file exists, check its permissions
            if perm_file.exists():
                logger.debug(f"Found permission file: {perm_file}")
                try:
                    with open(perm_file, 'r') as f:
                        permissions = json.load(f)
                        
                    # Check if user is in allowed_users
                    allowed_users = permissions.get("allowed_users", [])
                    logger.debug(f"Users with explicit permission: {allowed_users}")
                    if user_email in allowed_users:
                        logger.debug(f"User {user_email} has explicit permission")
                        return True
                except Exception as e:
                    logger.error(f"Error reading .syftperm_exe file {perm_file}: {e}")
            
            # Fall back to checking standard Syft permissions
            logger.debug(f"No explicit permission found, checking standard Syft permissions")
            
            # Check if we can determine the datasite path
            if hasattr(self.box, 'client') and hasattr(self.box.client, 'datasite_path'):
                try:
                    # Get the datasite path
                    datasite_path = Path(self.box.client.datasite_path)
                    logger.debug(f"Datasite path: {datasite_path}")
                    
                    # Get the relative path - manually since relative_to might fail if not a subdirectory
                    file_path_str = str(path)
                    datasite_path_str = str(datasite_path)
                    
                    if file_path_str.startswith(datasite_path_str):
                        relative_path = file_path_str[len(datasite_path_str):].lstrip('/')
                        logger.debug(f"Relative path: {relative_path}")
                        
                        # Check if the client has the has_permission method
                        if hasattr(self.box.client, 'has_permission'):
                            try:
                                has_access = self.box.client.has_permission(
                                    user=user_email, 
                                    path=relative_path, 
                                    permission="read"
                                )
                                logger.debug(f"Standard permission check result: {has_access}")
                                return has_access
                            except Exception as e:
                                logger.warning(f"Error calling has_permission: {e}")
                        else:
                            logger.warning("Client does not have has_permission method")
                    else:
                        logger.warning(f"File {file_path} is not within datasite path {datasite_path}")
                except Exception as e:
                    logger.warning(f"Error checking standard permissions: {e}")
            else:
                logger.warning("Client or datasite_path not available for standard permission check")
                
            return False
            
        except Exception as e:
            logger.error(f"Error checking file permission: {e}")
            return False
    
    def _handle_request(self, request: OllamaRequest, ctx: Request, box) -> OllamaResponse:
        """Process an incoming Ollama request by forwarding to the local Ollama instance."""
        logger.info(f"🔔 RECEIVED: Ollama request for model '{request.model}'")
        
        try:
            # Check if request includes files and handle file context
            file_context = ""
            if request.files:
                # Debug the context object to see its structure
                logger.debug(f"Context attributes: {dir(ctx)}")
                
                # Try to get the sender email from context
                user_email = None
                
                # Try different ways to access the sender information
                if hasattr(ctx, 'sender'):
                    user_email = ctx.sender
                elif hasattr(ctx, 'email'):
                    user_email = ctx.email
                elif hasattr(ctx, 'user'):
                    user_email = ctx.user
                elif hasattr(ctx, 'author'):
                    user_email = ctx.author
                
                # If we still don't have the user_email, check the event info
                if not user_email and hasattr(ctx, 'event'):
                    event_info = ctx.event
                    if hasattr(event_info, 'sender'):
                        user_email = event_info.sender
                
                # Fall back to the box's owner email if we couldn't determine the sender
                if not user_email:
                    user_email = box.client.email
                    logger.warning(f"Could not determine sender, using box owner: {user_email}")
                
                logger.info(f"Processing file request from user: {user_email}")
                
                for file_path in request.files:
                    # Verify user has permission to access this file
                    if not self._check_file_permission(user_email, file_path):
                        return OllamaResponse(
                            model=request.model,
                            response="",
                            error=f"User {user_email} does not have permission to access file: {file_path}",
                            ts=datetime.now(timezone.utc)
                        )
                    
                    # Try to read the file
                    try:
                        if os.path.exists(file_path):
                            with open(file_path, 'r') as f:
                                file_content = f.read()
                                file_context += f"\n\nFile: {file_path}\n```\n{file_content}\n```\n"
                        else:
                            return OllamaResponse(
                                model=request.model,
                                response="",
                                error=f"File not found: {file_path}",
                                ts=datetime.now(timezone.utc)
                            )
                    except Exception as e:
                        return OllamaResponse(
                            model=request.model,
                            response="",
                            error=f"Error reading file {file_path}: {str(e)}",
                            ts=datetime.now(timezone.utc)
                        )
            
            # Combine original prompt with file context if any
            full_prompt = request.prompt
            if file_context:
                full_prompt = f"Context files:\n{file_context}\n\nPrompt: {request.prompt}"
            
            # Prepare the request payload for Ollama
            payload = {
                "model": request.model,
                "prompt": full_prompt,
                "stream": False,  # Ensure we're not getting a streaming response
            }
            
            # Add optional parameters
            if request.system:
                payload["system"] = request.system
            if request.temperature is not None:
                payload["temperature"] = request.temperature
            if request.max_tokens is not None:
                payload["max_tokens"] = request.max_tokens
            if request.options:
                payload.update(request.options)
                
            # Send request to the local Ollama instance
            response = httpx.post(
                f"{self.ollama_url}/api/generate", 
                json=payload,
                timeout=120.0  # Longer timeout for LLM generation
            )
            
            if response.status_code == 200:
                # Improved JSON parsing to handle different response formats
                try:
                    # Try to parse as normal JSON first
                    data = response.json()
                except json.JSONDecodeError as e:
                    # If that fails, try to extract the first valid JSON object
                    try:
                        text = response.text
                        # Find the first complete JSON object
                        json_start = text.find('{')
                        json_end = text.rfind('}') + 1
                        if json_start >= 0 and json_end > json_start:
                            data = json.loads(text[json_start:json_end])
                        else:
                            raise ValueError(f"Could not find valid JSON in response: {text[:100]}...")
                    except Exception as nested_e:
                        return OllamaResponse(
                            model=request.model,
                            response="",
                            error=f"JSON parsing error: {str(e)}. Nested error: {str(nested_e)}",
                            ts=datetime.now(timezone.utc)
                        )
                
                # Extract and return the response
                return OllamaResponse(
                    model=request.model,
                    response=data.get("response", ""),
                    total_duration_ms=data.get("total_duration", 0),
                    ts=datetime.now(timezone.utc)
                )
            else:
                return OllamaResponse(
                    model=request.model,
                    response="",
                    error=f"HTTP Error {response.status_code}: {response.text}",
                    ts=datetime.now(timezone.utc)
                )
        except Exception as e:
            logger.error(f"Error processing Ollama request: {e}")
            return OllamaResponse(
                model=request.model,
                response="",
                error=str(e),
                ts=datetime.now(timezone.utc)
            )
    
    def generate(self, 
                 to_email: str, 
                 model: str, 
                 prompt: str, 
                 system: Optional[str] = None,
                 temperature: float = 0.7,
                 max_tokens: Optional[int] = None,
                 files: Optional[List[str]] = None) -> Optional[OllamaResponse]:
        """Send a generation request to a remote Ollama instance.
        
        Args:
            to_email: Email of the datasite hosting the Ollama instance
            model: Name of the LLM model to use
            prompt: The prompt text to send
            system: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            files: List of file paths to include in the context window
            
        Returns:
            OllamaResponse with the generated text if successful, None otherwise
        """
        request = OllamaRequest(
            model=model,
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            files=files,
            ts=datetime.now(timezone.utc)
        )
        
        return self.send_request(to_email, request)
    
    def set_file_permissions(self, 
                           to_email: str,
                           user_email: str,
                           file_paths: List[str],
                           operation: str = "set") -> Optional[FilePermissionResponse]:
        """Set file permissions for a user on a remote Ollama instance.
        
        Args:
            to_email: Email of the datasite hosting the Ollama instance
            user_email: Email of the user to set permissions for
            file_paths: List of file paths the user should be allowed to execute against
            operation: 'add', 'remove', or 'set' (replaces all existing permissions)
            
        Returns:
            FilePermissionResponse with the updated permissions if successful, None otherwise
        """
        request = FilePermissionRequest(
            user_email=user_email,
            file_paths=file_paths,
            operation=operation
        )
        
        # Send to the file permission endpoint with the correct response model
        return self.send_request(
            to_email=to_email, 
            request_data=request, 
            endpoint="/set_file_permissions",
            response_model=FilePermissionResponse
        )
    
    def list_available_models(self) -> List[Dict[str, Any]]:
        """List all models available on the local Ollama instance.
        
        Returns:
            List of model information dictionaries
        """
        try:
            response = httpx.get(f"{self.ollama_url}/api/tags")
            if response.status_code == 200:
                return response.json().get("models", [])
            else:
                logger.error(f"Failed to get models: HTTP {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return []
    
        
    def _list_file_permissions(self, request: FilePermissionRequest, ctx: Request) -> FilePermissionResponse:
        """List all files a user has permission to access using both .syftperm_exe 
        and standard Syft permissions."""
        logger.info(f"🔔 RECEIVED: List file permissions request for user '{request.user_email}'")
        
        try:
            user_email = request.user_email
            allowed_files = []
            
            # Get the datasite path
            datasite_path = None
            datasite_owner = None
            
            if hasattr(self.box, 'client') and hasattr(self.box.client, 'datasite_path'):
                datasite_path = self.box.client.datasite_path
                
                # Try to determine datasite owner from path
                try:
                    path_str = str(datasite_path)
                    parts = path_str.split('/')
                    for part in parts:
                        if '@' in part:
                            datasite_owner = part
                            break
                except Exception as e:
                    logger.warning(f"Could not determine datasite owner: {e}")
            
            if not datasite_path:
                logger.warning("Could not determine datasite path - using limited permission checks")
                return FilePermissionResponse(
                    user_email=user_email,
                    allowed_files=[],
                    success=False,
                    error="Could not determine datasite path",
                    ts=datetime.now(timezone.utc)
                )
            
            logger.info(f"Using datasite path: {datasite_path}")
            
            # 1. First check .syftperm_exe files (explicit LLM permissions)
            logger.info(f"Checking explicit .syftperm_exe permissions for user {user_email}")
            for root, dirs, files in os.walk(datasite_path):
                for file in files:
                    if file.endswith('.syftperm_exe'):
                        original_file = file[:-13]  # Remove .syftperm_exe suffix
                        perm_file_path = os.path.join(root, file)
                        original_file_path = os.path.join(root, original_file)
                        
                        # Check if user has permission
                        try:
                            with open(perm_file_path, 'r') as f:
                                permissions = json.load(f)
                                
                            if user_email in permissions.get("allowed_users", []):
                                allowed_files.append(original_file_path)
                        except Exception as e:
                            logger.error(f"Error reading permission file {perm_file_path}: {e}")
            
            # 2. Try to use Syft's database permission system
            try:
                from syftbox.server.db.db import get_read_permissions_for_user
                from syftbox.server.db.schema import get_db
                
                logger.info(f"Checking database permissions for user {user_email}")
                
                # Get a database connection and check permissions
                try:
                    db_conn = get_db()
                    # Pass the datasite path to get_db()
                    db_conn = get_db(path=datasite_path)
                    
                    # Get all files the user has permission to read
                    file_permissions = get_read_permissions_for_user(db_conn, user_email)
                    
                    for file_perm in file_permissions:
                        if file_perm["read_permission"]:
                            file_path = file_perm["path"]
                            if os.path.exists(file_path) and file_path not in allowed_files:
                                allowed_files.append(file_path)
                    
                    logger.info(f"Found {len(allowed_files)} permitted files via database")
                    
                except Exception as db_error:
                    logger.warning(f"Error using database permissions: {db_error}")
                    
            except ImportError as e:
                logger.warning(f"Syft database modules not available: {e}")
            
            # 3. Try to use the in-memory permission system
            try:
                from syftbox.lib.constants import PERM_FILE
                from syftbox.lib.permissions import ComputedPermission, PermissionType, SyftPermission
                
                logger.info(f"Checking in-memory permission system for user {user_email}")
                
                # Find all files we want to check permissions for
                all_files = []
                for root, dirs, files in os.walk(datasite_path):
                    for file in files:
                        # Skip permission files and other system files
                        if (file.endswith('.syftperm_exe') or file.endswith('.request') 
                            or file.endswith('.response') or file == "rpc.schema.json"
                            or file == PERM_FILE):
                            continue
                        
                        all_files.append(os.path.join(root, file))
                
                logger.info(f"Found {len(all_files)} total files to check permissions for")
                
                # Group files by directory for more efficient permission checking
                files_by_dir = {}
                for file_path in all_files:
                    dir_path = os.path.dirname(file_path)
                    if dir_path not in files_by_dir:
                        files_by_dir[dir_path] = []
                    files_by_dir[dir_path].append(file_path)
                
                # Check permissions directory by directory
                for dir_path, dir_files in files_by_dir.items():
                    # Find all permission files that might apply to this directory
                    applicable_rules = []
                    current_dir = dir_path
                    
                    # Walk up the directory tree to find all applicable permission files
                    while current_dir and current_dir.startswith(str(datasite_path)):
                        perm_file_path = os.path.join(current_dir, PERM_FILE)
                        if os.path.exists(perm_file_path):
                            try:
                                # Convert datasite_path to Path object before passing to from_file
                                perm_file = SyftPermission.from_file(
                                    Path(perm_file_path),
                                    Path(datasite_path)  # Convert string to Path object
                                )
                                applicable_rules.extend(perm_file.rules)
                            except Exception as e:
                                logger.warning(f"Error parsing permission file {perm_file_path}: {str(e)}")
                        
                        # Move up one directory
                        parent_dir = os.path.dirname(current_dir)
                        if parent_dir == current_dir:  # We've reached the root
                            break
                        current_dir = parent_dir
                    
                    # Check each file in this directory
                    for file_path in dir_files:
                        try:
                            # Use a relative path from the datasite root for permission checking
                            rel_file_path = os.path.relpath(file_path, start=datasite_path)
                            
                            # Create a ComputedPermission object to check if the user has access
                            computed_permission = ComputedPermission.from_user_rules_and_path(
                                rules=applicable_rules,
                                user=user_email,
                                path=Path(rel_file_path)
                            )
                            
                            # If the user has read permission, add to allowed files
                            if computed_permission.has_permission(PermissionType.READ):
                                if file_path not in allowed_files:
                                    allowed_files.append(file_path)
                                    
                        except Exception as e:
                            logger.debug(f"Error checking permission for {file_path}: {e}")
                
                logger.info(f"Found {len(allowed_files)} total permitted files after in-memory checks")
                
            except ImportError as e:
                logger.warning(f"Syft permission modules not available: {e}")
            
            # 4. If user is datasite owner, they have access to all files
            if datasite_owner and user_email == datasite_owner:
                logger.info(f"User {user_email} is the datasite owner - adding all files")
                for root, dirs, files in os.walk(datasite_path):
                    for file in files:
                        # Skip specific file types
                        if (file.endswith('.syftperm_exe') or file.endswith('.request') 
                            or file.endswith('.response') or file == "rpc.schema.json"):
                            continue
                        
                        file_path = os.path.join(root, file)
                        if file_path not in allowed_files:
                            allowed_files.append(file_path)
            
            return FilePermissionResponse(
                user_email=user_email,
                allowed_files=allowed_files,
                success=True,
                ts=datetime.now(timezone.utc)
            )
            
        except Exception as e:
            logger.error(f"Error listing file permissions: {e}")
            return FilePermissionResponse(
                user_email=request.user_email,
                allowed_files=[],
                success=False,
                error=str(e),
                ts=datetime.now(timezone.utc)
            )

        
    def list_permitted_files(self, to_email: str, user_email: str) -> Optional[FilePermissionResponse]:
        """List all files a user has permission to access on a remote Ollama instance.
        
        Args:
            to_email: Email of the datasite hosting the Ollama instance
            user_email: Email of the user to check permissions for
            
        Returns:
            FilePermissionResponse with the list of allowed files if successful, None otherwise
        """
        request = FilePermissionRequest(
            user_email=user_email,
            file_paths=[],  # Empty list means "list all permissions"
            operation="list"
        )
        
        return self.send_request(
            to_email=to_email, 
            request_data=request, 
            endpoint="/list_file_permissions",
            response_model=FilePermissionResponse
        )


# ----------------- API Functions -----------------

def client(config_path: Optional[str] = None, 
           ollama_url: str = "http://localhost:11434",
           verbose: bool = False) -> OllamaClient:
    """Create and return a new Ollama client.
    
    Args:
        config_path: Optional path to a custom config.json file
        ollama_url: URL of the local Ollama instance
        verbose: Whether to enable verbose logging (default: False)
        
    Returns:
        An OllamaClient instance
    """
    # Configure logging based on environment and verbose flag
    configure_logging(verbose)
    
    return OllamaClient(config_path, ollama_url)
