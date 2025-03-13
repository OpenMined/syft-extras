from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ChatMessage(BaseModel):
    """Model for chat messages exchanged between users."""
    msg_id: str = Field(description="Unique message ID")
    sender: str = Field(description="Email of the sender")
    content: str = Field(description="Message content")
    timestamp: datetime = Field(description="Message timestamp")
    thread_id: Optional[str] = Field(default=None, description="Thread ID for conversation grouping")
    reply_to: Optional[str] = Field(default=None, description="ID of message being replied to")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional message metadata")


class ChatRequest(BaseModel):
    """Request to send a chat message."""
    message: ChatMessage = Field(description="The chat message to send")


class ChatResponse(BaseModel):
    """Response to a chat message request."""
    status: str = Field(description="Status of the message delivery")
    message_id: str = Field(description="ID of the delivered message")
    timestamp: datetime = Field(description="Timestamp of the response")


class ChatHistoryRequest(BaseModel):
    """Request to retrieve chat history."""
    limit: int = Field(default=50, description="Maximum number of messages to retrieve")
    thread_id: Optional[str] = Field(default=None, description="Filter by thread ID")
    since: Optional[datetime] = Field(default=None, description="Retrieve messages since this time")
    with_user: Optional[str] = Field(default=None, description="Filter by user email")


class ChatHistoryResponse(BaseModel):
    """Response containing chat history."""
    messages: List[ChatMessage] = Field(description="List of chat messages")
    count: int = Field(description="Number of messages returned") 