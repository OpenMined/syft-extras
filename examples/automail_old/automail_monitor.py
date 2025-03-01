from __future__ import annotations

import json
import time
import requests
from pathlib import Path
import os
import uuid

from flask import Flask, render_template, jsonify, request
from loguru import logger

# Set up Flask app
app = Flask(__name__)

# Path to the message log file
LOGS_DIR = Path("automail_logs")
MESSAGE_LOG = LOGS_DIR / "message_log.json"

# Track the last message timestamp for efficient updates
last_update_time = 0

@app.route('/')
def home():
    """Render the monitoring interface."""
    return render_template('monitor.html')


@app.route('/messages')
def get_messages():
    """Get all messages from the log file."""
    try:
        if MESSAGE_LOG.exists():
            with open(MESSAGE_LOG, "r") as f:
                try:
                    messages = json.load(f)
                    return jsonify(messages)
                except json.JSONDecodeError:
                    logger.error("Error reading message log")
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
    
    # Return empty list if no messages or error
    return jsonify([])


@app.route('/update_response', methods=['POST'])
def update_response():
    """Send a response override to the AI server."""
    data = request.json
    message_id = data.get('message_id')
    new_response = data.get('response')
    
    if not message_id or not new_response:
        return jsonify({"success": False, "error": "Missing message_id or response"})
    
    try:
        # Call the AI server's update endpoint using the correct endpoint
        # We need to use the SyftEvents endpoint, not the Ollama API
        
        # First, update our local log file
        if MESSAGE_LOG.exists():
            with open(MESSAGE_LOG, "r") as f:
                try:
                    log_data = json.load(f)
                    for entry in log_data:
                        if entry.get("id") == message_id:
                            entry["response"] = new_response
                            entry["ai_generated"] = False
                    
                    with open(MESSAGE_LOG, "w") as f:
                        json.dump(log_data, f)
                except (json.JSONDecodeError, IOError) as e:
                    logger.error(f"Error updating local log: {e}")
                    return jsonify({"success": False, "error": f"Error updating log: {e}"})
        
        # Now update on the AI server by making a request to our RPC endpoint
        # Look for a pingpong folder in the same directory as the SyftBox data
        syftbox_dir = os.environ.get('SYFTBOX_DIR', os.path.expanduser('~/SyftBox'))
        pingpong_dir = os.path.join(syftbox_dir, 'datasites', 'pingpong')
        
        # We need to write a file to the RPC directory with the update request
        update_request_data = {
            "message_id": message_id,
            "response": new_response
        }
        
        # Try to find the RPC directory
        rpc_dir = None
        for root, dirs, files in os.walk(pingpong_dir):
            if 'rpc' in dirs:
                rpc_dir = os.path.join(root, 'rpc', 'update_response')
                # Create the endpoint directory if it doesn't exist
                os.makedirs(rpc_dir, exist_ok=True)
                break
        
        if not rpc_dir:
            logger.error("Could not find RPC directory")
            return jsonify({"success": False, "error": "Could not find RPC directory"})
        
        # Create a unique request ID
        request_id = f"{uuid.uuid4()}.request"
        request_path = os.path.join(rpc_dir, request_id)
        
        # Write the request data
        with open(request_path, 'w') as f:
            json.dump(update_request_data, f)
        
        # Wait for a response file (up to 3 seconds)
        response_path = request_path.replace('.request', '.response')
        start_time = time.time()
        while not os.path.exists(response_path) and time.time() - start_time < 3:
            time.sleep(0.1)
        
        if os.path.exists(response_path):
            # Read the response
            with open(response_path, 'r') as f:
                result = json.load(f)
            return jsonify({"success": True})
        else:
            # If no response received, we'll consider the update successful anyway
            # since we already updated our local log
            return jsonify({"success": True, "warning": "No confirmation received from AI server"})
        
    except Exception as e:
        logger.error(f"Error in update_response: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route('/templates/monitor.html')
def monitor_template():
    """Return the HTML template for the monitor."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>AutoMail Monitor</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
            h1 { color: #333; margin-top: 0; }
            .message { border-bottom: 1px solid #eee; padding: 10px 0; position: relative; }
            .message:last-child { border-bottom: none; }
            .message .header { display: flex; justify-content: space-between; margin-bottom: 5px; }
            .message .from { font-weight: bold; }
            .message .timestamp { color: #888; font-size: 0.85em; }
            .message-content { background-color: #f0f8ff; padding: 8px; border-radius: 5px; margin-bottom: 5px; }
            .response-content { background-color: #f0fff0; padding: 8px; border-radius: 5px; position: relative; }
            .edit-btn { position: absolute; right: 8px; top: 8px; background: #007bff; color: white; border: none; border-radius: 3px; padding: 3px 8px; cursor: pointer; display: none; }
            .response-content:hover .edit-btn { display: block; }
            .edit-area { width: 100%; min-height: 80px; margin-top: 10px; box-sizing: border-box; border: 1px solid #ddd; border-radius: 4px; padding: 8px; }
            .edit-controls { display: flex; justify-content: flex-end; gap: 10px; margin-top: 5px; }
            .save-btn { background: #28a745; color: white; border: none; border-radius: 3px; padding: 5px 15px; cursor: pointer; }
            .cancel-btn { background: #dc3545; color: white; border: none; border-radius: 3px; padding: 5px 15px; cursor: pointer; }
            .human-edited { border-left: 4px solid #28a745; }
            .ai-generated { border-left: 4px solid #17a2b8; }
            .status { padding: 10px; margin-bottom: 15px; border-radius: 5px; }
            .connected { background-color: #d4edda; color: #155724; }
            .disconnected { background-color: #f8d7da; color: #721c24; }
            #auto-scroll { margin-bottom: 15px; }
            .controls { margin-bottom: 15px; display: flex; align-items: center; }
            .refresh-button { margin-left: 20px; padding: 5px 15px; background-color: #007bff; color: white; border: none; border-radius: 3px; cursor: pointer; }
            .refresh-button:hover { background-color: #0056b3; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>AutoMail Monitoring Dashboard</h1>
            <div id="status" class="status connected">Monitor active - watching for messages</div>
            
            <div class="controls">
                <div>
                    <input type="checkbox" id="auto-scroll" checked>
                    <label for="auto-scroll">Auto-scroll to new messages</label>
                </div>
                <button class="refresh-button" onclick="fetchMessages()">Refresh</button>
            </div>
            
            <div id="messages-container"></div>
        </div>

        <script>
            // Store messages to avoid duplicates
            let messagesMap = {};
            let isAutoScrollEnabled = true;
            let currentlyEditing = null;
            
            // Initialize
            document.addEventListener('DOMContentLoaded', function() {
                // Set auto-scroll checkbox handler
                document.getElementById('auto-scroll').addEventListener('change', function() {
                    isAutoScrollEnabled = this.checked;
                });
                
                // Initial fetch
                fetchMessages();
                
                // Set up polling
                setInterval(fetchMessages, 1000);
            });
            
            function fetchMessages() {
                fetch('/messages')
                    .then(response => response.json())
                    .then(messages => {
                        if (messages.length > 0) {
                            updateMessagesDisplay(messages);
                        }
                    })
                    .catch(error => {
                        console.error('Error fetching messages:', error);
                        document.getElementById('status').className = 'status disconnected';
                        document.getElementById('status').textContent = 'Disconnected - unable to fetch messages';
                    });
            }
            
            function updateMessagesDisplay(messages) {
                const container = document.getElementById('messages-container');
                
                // Don't rebuild if we're currently editing
                if (currentlyEditing) {
                    return;
                }
                
                // Clear and rebuild the messages container
                container.innerHTML = '';
                
                // Add all messages to the display
                messages.forEach(message => {
                    const msgDiv = document.createElement('div');
                    msgDiv.className = 'message';
                    msgDiv.dataset.id = message.id || '';
                    
                    const header = document.createElement('div');
                    header.className = 'header';
                    
                    const from = document.createElement('div');
                    from.className = 'from';
                    from.textContent = message.from || 'Unknown user';
                    
                    const timestamp = document.createElement('div');
                    timestamp.className = 'timestamp';
                    timestamp.textContent = message.timestamp || '';
                    
                    header.appendChild(from);
                    header.appendChild(timestamp);
                    
                    const messageContent = document.createElement('div');
                    messageContent.className = 'message-content';
                    messageContent.textContent = message.message || '';
                    
                    const responseContent = document.createElement('div');
                    responseContent.className = message.ai_generated !== false ? 'response-content ai-generated' : 'response-content human-edited';
                    responseContent.textContent = message.response || '';
                    
                    // Add edit button for response
                    const editBtn = document.createElement('button');
                    editBtn.className = 'edit-btn';
                    editBtn.textContent = 'Edit';
                    editBtn.onclick = function(e) {
                        e.stopPropagation();
                        showEditMode(message.id, message.response);
                    };
                    responseContent.appendChild(editBtn);
                    
                    msgDiv.appendChild(header);
                    msgDiv.appendChild(messageContent);
                    msgDiv.appendChild(responseContent);
                    
                    container.appendChild(msgDiv);
                });
                
                // Auto-scroll to bottom if enabled
                if (isAutoScrollEnabled) {
                    container.scrollTop = container.scrollHeight;
                }
                
                // Update status
                document.getElementById('status').className = 'status connected';
                document.getElementById('status').textContent = 'Connected - ' + messages.length + ' messages received';
            }
            
            function showEditMode(messageId, currentText) {
                // Set currently editing flag
                currentlyEditing = messageId;
                
                // Find the message div
                const msgDiv = document.querySelector(`.message[data-id="${messageId}"]`);
                if (!msgDiv) return;
                
                // Find and hide the response content
                const responseContent = msgDiv.querySelector('.response-content');
                if (!responseContent) return;
                responseContent.style.display = 'none';
                
                // Create edit area
                const editArea = document.createElement('textarea');
                editArea.className = 'edit-area';
                editArea.value = currentText || '';
                
                // Create edit controls
                const editControls = document.createElement('div');
                editControls.className = 'edit-controls';
                
                const saveBtn = document.createElement('button');
                saveBtn.className = 'save-btn';
                saveBtn.textContent = 'Save';
                saveBtn.onclick = function() {
                    saveEdit(messageId, editArea.value);
                };
                
                const cancelBtn = document.createElement('button');
                cancelBtn.className = 'cancel-btn';
                cancelBtn.textContent = 'Cancel';
                cancelBtn.onclick = function() {
                    cancelEdit(messageId);
                };
                
                editControls.appendChild(cancelBtn);
                editControls.appendChild(saveBtn);
                
                // Add edit components to message
                msgDiv.appendChild(editArea);
                msgDiv.appendChild(editControls);
            }
            
            function saveEdit(messageId, newText) {
                // Send update to server
                fetch('/update_response', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        message_id: messageId,
                        response: newText
                    }),
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // Reset editing state and refresh
                        currentlyEditing = null;
                        fetchMessages();
                    } else {
                        alert('Failed to update: ' + (data.error || 'Unknown error'));
                    }
                })
                .catch(error => {
                    console.error('Error updating response:', error);
                    alert('Failed to save changes. Please try again.');
                });
            }
            
            function cancelEdit(messageId) {
                // Reset editing state and refresh
                currentlyEditing = null;
                fetchMessages();
            }
        </script>
    </body>
    </html>
    """


if __name__ == "__main__":
    logger.info("Starting AutoMail monitoring server")
    
    # Run the Flask app
    app.run(debug=False, port=5001) 