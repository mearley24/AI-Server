#!/usr/bin/env python3
"""
Voice Webhook Server — iPad to Bob via Tailscale

Direct HTTP API for voice commands. Routes to appropriate handlers.
Endpoint: POST /ask with {"message": "user's spoken text"}
Returns: {"reply": "Bob's response"}

Usage:
    python3 api/voice_webhook.py
    # Listens on 0.0.0.0:8088
"""
import os
import subprocess
import shlex
from pathlib import Path
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

app = Flask(__name__)

AI_SERVER = Path(os.environ.get('AI_SERVER_DIR', Path.home() / 'AI-Server'))
TASK_BOARD = AI_SERVER / 'orchestrator' / 'task_board.py'
POLYMARKET = AI_SERVER / 'integrations' / 'polymarket' / 'polymarket_client.py'

def run_command(cmd, timeout=30):
    """Run a command and return output."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(AI_SERVER)
        )
        return result.stdout.strip() or result.stderr.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out"
    except Exception as e:
        return f"Error: {e}"

def process_message(message):
    """Route voice message to appropriate handler."""
    msg = message.lower().strip()
    
    # Task queries
    if any(w in msg for w in ['task', 'todo', 'what should', 'work on']):
        if 'add' in msg or 'create' in msg:
            return "To add a task, please be more specific. What's the task title and description?"
        output = run_command(['python3', str(TASK_BOARD), 'list', '--status', 'pending'])
        lines = output.split('\n')[:10]  # Limit for voice
        if 'No tasks' in output:
            return "You have no pending tasks."
        return "Here are your pending tasks: " + '. '.join([l for l in lines if l.strip()])
    
    # Polymarket
    if any(w in msg for w in ['polymarket', 'market', 'prediction', 'betting', 'poly']):
        if 'trending' in msg or 'hot' in msg or 'popular' in msg:
            output = run_command(['python3', str(POLYMARKET), '--trending'])
            return output[:500] if output else "Could not fetch trending markets."
        if 'arbitrage' in msg or 'arb' in msg:
            output = run_command(['python3', str(POLYMARKET), '--arbitrage'])
            return output[:500] if output else "No arbitrage opportunities found."
        return "Polymarket commands: say 'trending markets' or 'arbitrage opportunities'"
    
    # Status
    if any(w in msg for w in ['status', 'how are', 'running', 'health']):
        return "All systems operational. Bob is online, task board is active, and the team is ready."
    
    # Time/date
    if any(w in msg for w in ['time', 'date', 'today']):
        from datetime import datetime
        now = datetime.now()
        return f"It's {now.strftime('%A, %B %d at %I:%M %p')}."
    
    # Help
    if any(w in msg for w in ['help', 'what can', 'commands']):
        return ("I can help with: checking tasks, Polymarket trends and arbitrage, "
                "system status, and the current time. What would you like to know?")
    
    # Default - echo back for now (can integrate LLM later)
    return f"I heard: {message}. Try asking about tasks, Polymarket, or system status."

@app.route('/ask', methods=['POST', 'GET'])
def ask():
    """Receive voice message, process it, return reply."""
    # Support both POST JSON and GET query param
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        message = data.get('message', '').strip()
    else:
        message = request.args.get('q', '').strip()
    
    if not message:
        return jsonify({'error': 'No message provided'}), 400
    
    reply = process_message(message)
    return jsonify({'reply': reply})

@app.route('/say/<path:message>', methods=['GET', 'POST'])
def say(message):
    """Ultra-simple endpoint - just returns plain text reply."""
    reply = process_message(message)
    return reply, 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/say', methods=['POST'])
def say_post():
    """POST version - accepts plain text body or JSON."""
    # Try JSON first
    data = request.get_json(force=True, silent=True)
    if data and data.get('message'):
        message = data.get('message', '').strip()
    else:
        # Fall back to raw body text
        message = request.get_data(as_text=True).strip()
    
    if not message:
        return "Please say something", 400
    
    reply = process_message(message)
    return reply, 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'ok', 'service': 'voice-webhook'})

@app.route('/', methods=['GET'])
def index():
    """Root endpoint with usage info."""
    return jsonify({
        'service': 'Bob Voice API',
        'endpoint': 'POST /ask',
        'body': '{"message": "your spoken text"}',
        'example': 'curl -X POST http://100.89.1.51:8088/ask -H "Content-Type: application/json" -d \'{"message": "what are my tasks"}\''
    })

if __name__ == '__main__':
    port = int(os.environ.get('VOICE_WEBHOOK_PORT', 8088))
    print(f"🎤 Voice webhook starting on http://0.0.0.0:{port}")
    print(f"   Tailscale: http://100.89.1.51:{port}/ask")
    app.run(host='0.0.0.0', port=port, debug=False)
