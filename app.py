import os
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route("/")
def home():
    files = []
    if os.path.exists(app.config['UPLOAD_FOLDER']):
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            parts = filename.split("_", 1)
            cls_name = parts[0] if len(parts) > 1 else "Genel"
            files.append({"name": filename, "cls": cls_name})
    return render_template("index.html", files=files)

@app.route("/upload", methods=["POST"])
def upload_file():
    if 'file' in request.files:
        file = request.files['file']
        class_name = request.form.get('class_name', 'Genel')
        if file.filename != '':
            filename = f"{class_name}_{file.filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
