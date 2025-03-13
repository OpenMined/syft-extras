from datetime import datetime, timezone
from loguru import logger
from syft_event import EventRouter
from syft_event.types import Request

from .models import ChatRequest, ChatResponse, ChatHistoryRequest, ChatHistoryResponse, ChatMessage
from .database import MessageModel

# ----------------- Chat Router -----------------

chat_router = EventRouter()

@chat_router.on_request("/message")
def message_handler(request: ChatRequest, app: Request) -> ChatResponse:
    """Handle incoming chat messages"""
    session = app.state["db_session"]
    message = request.message
    
    logger.info(f"📨 RECEIVED: Message from {message.sender}: {message.content[:50]}...")
    
    # Convert to JSON serializable format for metadata
    metadata_str = str(message.metadata) if message.metadata else "{}"
    
    # Check if message already exists in database
    existing_message = session.query(MessageModel).filter(MessageModel.msg_id == message.msg_id).first()
    
    if not existing_message:
        # Create db model from message only if it doesn't exist
        db_message = MessageModel(
            msg_id=message.msg_id,
            sender=message.sender,
            content=message.content,
            timestamp=message.timestamp,
            thread_id=message.thread_id,
            reply_to=message.reply_to,
            meta_data=metadata_str
        )
        
        # Save to database
        session.add(db_message)
        try:
            session.commit()
        except Exception as e:
            # Rollback on error
            session.rollback()
            logger.error(f"Error saving message: {e}")
            # Continue processing even if save fails
    else:
        logger.info(f"Message with ID {message.msg_id} already exists, skipping database insert")
    
    # Check if this is a self-stored message (where sender == current user)
    is_self_stored = message.sender == app.state["client_email"]
    
    # Notify any registered message listeners, but only if not a self-stored message
    if "message_listeners" in app.state and not is_self_stored:
        for listener in app.state["message_listeners"]:
            try:
                listener(message)
            except Exception as e:
                logger.error(f"Error in message listener: {e}")
    
    return ChatResponse(
        status="delivered",
        message_id=message.msg_id,
        timestamp=datetime.now(timezone.utc)
    )


@chat_router.on_request("/history")
def history_handler(request: ChatHistoryRequest, app: Request) -> ChatHistoryResponse:
    """Handle requests for chat history"""
    session = app.state["db_session"]
    
    # Start with a base query for all messages
    query = session.query(MessageModel)
    
    # Apply filters based on request
    if request.thread_id:
        query = query.filter(MessageModel.thread_id == request.thread_id)
    
    if request.since:
        query = query.filter(MessageModel.timestamp >= request.since)
    
    # Filter by user if specified
    if request.with_user:
        current_user = app.state["client_email"]
        query = query.filter(
            ((MessageModel.sender == request.with_user) & (MessageModel.meta_data.like(f"%'recipient': '{current_user}'%"))) |
            ((MessageModel.sender == current_user) & (MessageModel.meta_data.like(f"%'recipient': '{request.with_user}'%")))
        )
    
    # Order by timestamp and limit results
    query = query.order_by(MessageModel.timestamp)
    
    if request.limit:
        query = query.limit(request.limit)
    
    # Execute query
    db_messages = query.all()
    
    # Convert SQLAlchemy models to Pydantic models
    messages = []
    for db_msg in db_messages:
        # Parse metadata from string
        try:
            metadata = eval(db_msg.meta_data) if db_msg.meta_data else {}
        except:
            metadata = {}
            
        messages.append(ChatMessage(
            msg_id=db_msg.msg_id,
            sender=db_msg.sender,
            content=db_msg.content,
            timestamp=db_msg.timestamp,
            thread_id=db_msg.thread_id,
            reply_to=db_msg.reply_to,
            metadata=metadata
        ))
    
    return ChatHistoryResponse(
        messages=messages,
        count=len(messages)
    ) 