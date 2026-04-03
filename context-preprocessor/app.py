"""
app.py — Flask web app for Auto-28 Context Preprocessor.
Runs on port 8028.
"""

import os
from flask import Flask, render_template, request, jsonify
from preprocessor import process

app = Flask(__name__)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/process', methods=['POST'])
def process_text():
    data = request.get_json(silent=True) or {}
    raw = data.get('text', '')

    if not raw.strip():
        return jsonify({
            'output': '',
            'format_type': '',
            'input_chars': 0,
            'output_chars': 0,
            'input_lines': 0,
            'output_lines': 0,
            'trimmed_lines': 0,
            'reduction_pct': 0.0,
        })

    result = process(raw)

    return jsonify({
        'output': result.output,
        'format_type': result.format_type,
        'input_chars': result.input_chars,
        'output_chars': result.output_chars,
        'input_lines': result.input_lines,
        'output_lines': result.output_lines,
        'trimmed_lines': result.trimmed_lines,
        'reduction_pct': result.reduction_pct,
    })


if __name__ == '__main__':
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 8028))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host=host, port=port, debug=debug)
