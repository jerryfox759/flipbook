import os
import json
import mimetypes
from flask import Flask, render_template, request, Response, jsonify, send_from_directory, stream_with_context
from scraper import check_and_download_flipbook_gen, extract_ebook_links

app = Flask(__name__)

# Ensure output directory is the 'downloads' subdirectory in the workspace
WORKSPACE_DIR = os.path.abspath(os.path.dirname(__file__))
DOWNLOADS_DIR = os.path.join(WORKSPACE_DIR, 'downloads')
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/stream-download')
def stream_download():
    url = request.args.get('url')
    if not url:
        def error_gen():
            yield f"data: {json.dumps({'status': 'error', 'message': 'Missing URL parameter'})}\n\n"
        return Response(error_gen(), content_type='text/event-stream')

    def generate_progress():
        try:
            # Call the generator from scraper.py
            for event in check_and_download_flipbook_gen(url, output_dir=DOWNLOADS_DIR):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'message': f'Server exception: {str(e)}'})}\n\n"

    return Response(stream_with_context(generate_progress()), content_type='text/event-stream')

@app.route('/api/books')
def list_books():
    books = []
    try:
        for file in os.listdir(DOWNLOADS_DIR):
            if file.endswith('.pdf'):
                file_path = os.path.join(DOWNLOADS_DIR, file)
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
def download_file(filename):
    # Ensure secure filename and verify it ends with .pdf
    if not filename.endswith('.pdf'):
        return "Invalid file type. Only PDF downloads are allowed.", 400
    return send_from_directory(DOWNLOADS_DIR, filename, as_attachment=True)

if __name__ == '__main__':
    # Run server (default local: 127.0.0.1:5000, production: 0.0.0.0:PORT)
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Flipbook Scraper Web Server at http://{host}:{port}")
    app.run(host=host, port=port, debug=True)
