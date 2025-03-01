from __future__ import annotations

from flask import Flask, render_template, request, jsonify

from automail_client import AutoMailClient

# Initialize Flask
app = Flask(__name__)

# Global client instance
client = AutoMailClient()

@app.route('/')
def index():
    return render_template('automail.html')

@app.route('/api/user')
def get_user():
    return jsonify({"email": client.email})

@app.route('/api/contacts')
def get_contacts():
    contacts = client.contacts
    return jsonify({"contacts": contacts})

@app.route('/api/send', methods=['POST'])
def send_message():
    data = request.json
    recipient = data.get('recipient')
    message = data.get('message')
    
    if not recipient or not message:
        return jsonify({"error": "Missing recipient or message"}), 400
    
    # Send the message and get the response
    response = client.send_message(recipient, message)
    
    if response:
        return jsonify({
            "message": response.content,
            "timestamp": response.timestamp.isoformat(),
            "ai_generated": response.ai_generated
        })
    else:
        return jsonify({"error": "Failed to send message or receive response"}), 500

@app.route('/api/conversations/<contact>')
def get_conversation(contact):
    conversation = client.get_conversation(contact)
    
    # Convert to serializable format
    messages = []
    for msg in conversation:
        messages.append({
            "content": msg.content,
            "sender": msg.sender,
            "timestamp": msg.timestamp.isoformat(),
            "ai_generated": msg.ai_generated
        })
    
    return jsonify({"messages": messages})

if __name__ == '__main__':
    app.run(debug=True, port=5000) 