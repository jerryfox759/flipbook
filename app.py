import os
import json
import mimetypes
import hashlib
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, render_template, request, Response, jsonify, send_from_directory, stream_with_context, g
from scraper import check_and_download_flipbook_gen, extract_ebook_links
from clerk_backend_api.security import authenticate_request
from clerk_backend_api.security.types import AuthenticateRequestOptions

load_dotenv()

app = Flask(__name__)

# Ensure output directory is the 'downloads' subdirectory in the workspace
WORKSPACE_DIR = os.path.abspath(os.path.dirname(__file__))
DOWNLOADS_DIR = os.path.join(WORKSPACE_DIR, 'downloads')
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

def clerk_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        secret_key = os.environ.get('CLERK_SECRET_KEY')
        options = AuthenticateRequestOptions(secret_key=secret_key)
        request_state = authenticate_request(request, options)
        if not request_state.is_signed_in:
            return jsonify({'error': 'Unauthorized', 'message': 'Authentication required', 'reason': str(request_state.reason)}), 401
        
        # Save user_id to Flask request globals
        g.user_id = request_state.payload.get("sub")
        return f(*args, **kwargs)
    return decorated

def get_user_downloads_dir():
    # Generate a safe, unique folder name for the user using SHA-256 hash of user ID
    user_hash = hashlib.sha256(g.user_id.encode('utf-8')).hexdigest()
    user_dir = os.path.join(DOWNLOADS_DIR, user_hash)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

@app.route('/')
def index():
    clerk_pub_key = os.environ.get('CLERK_PUBLISHABLE_KEY') or os.environ.get('NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY')
    print(f"DEBUG: clerk_pub_key={clerk_pub_key}", flush=True)
    return render_template('index.html', clerk_publishable_key=clerk_pub_key)


@app.route('/stream-download')
@clerk_login_required
def stream_download():
    url = request.args.get('url')
    if not url:
        def error_gen():
            yield f"data: {json.dumps({'status': 'error', 'message': 'Missing URL parameter'})}\n\n"
        response = Response(error_gen(), content_type='text/event-stream')
        response.headers['Cache-Control'] = 'no-cache, no-transform'
        response.headers['X-Accel-Buffering'] = 'no'
        response.headers['Connection'] = 'keep-alive'
        return response

    def generate_progress():
        try:
            # Call the generator from scraper.py inside the user-specific directory
            user_dir = get_user_downloads_dir()
            for event in check_and_download_flipbook_gen(url, output_dir=user_dir):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'message': f'Server exception: {str(e)}'})}\n\n"

    response = Response(stream_with_context(generate_progress()), content_type='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache, no-transform'
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Connection'] = 'keep-alive'
    return response

@app.route('/api/books')
@clerk_login_required
def list_books():
    books = []
    try:
        user_dir = get_user_downloads_dir()
        for file in os.listdir(user_dir):
            if file.endswith('.pdf'):
                file_path = os.path.join(user_dir, file)
                stat = os.stat(file_path)
                books.append({
                    'filename': file,
                    'size_bytes': stat.st_size,
                    'created_time': stat.st_mtime
                })
        # Sort by creation time descending (newest first)
        books.sort(key=lambda x: x['created_time'], reverse=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify(books)

@app.route('/download-file/<path:filename>')
@clerk_login_required
def download_file(filename):
    # Ensure secure filename and verify it ends with .pdf
    if not filename.endswith('.pdf'):
        return "Invalid file type. Only PDF downloads are allowed.", 400
    user_dir = get_user_downloads_dir()
    return send_from_directory(user_dir, filename, as_attachment=True)

if __name__ == '__main__':
    # Run server (default local: 127.0.0.1:5000, production: 0.0.0.0:PORT)
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Flipbook Scraper Web Server at http://{host}:{port}")
    app.run(host=host, port=port, debug=True)
