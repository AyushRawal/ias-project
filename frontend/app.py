from flask import Flask, render_template, send_from_directory
import os

app = Flask(__name__, static_url_path='', static_folder='.')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/<path:path>')
def static_file(path):
    return send_from_directory('.', path)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080, debug=True)