"""Local artifact preview with HTTP Range support for synchronized video seeking."""
from pathlib import Path
import argparse
from flask import Flask, send_from_directory
from config import OUTPUT_DIR

parser = argparse.ArgumentParser()
parser.add_argument('--folder', default='scene_reference_five')
parser.add_argument('--port', type=int, default=8769)
args = parser.parse_args()
folder = Path(OUTPUT_DIR, args.folder)
app = Flask(__name__, static_folder=str(folder), static_url_path='')


@app.get('/')
def index():
    return send_from_directory(folder, 'index.html')


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=args.port, debug=False)
