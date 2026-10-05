import json
import os
import secrets
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(file))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATA_DIR, "data.json")

_env_code = os.environ.get("TEACHER_CODE")
TEACHER_CODE = (_env_code if _env_code else "ogretmen").strip().strip("\"'").strip()

GRADES = [9, 10, 11, 12]
SECTIONS = ["ATP", "A", "B", "C", "D", "Özel Sınıf"]
DEFAULT_CLASSES = [f"{g}-{s}" for g in GRADES for s in SECTIONS]

MAX_TEXT_CHARS = 400_000

app = Flask(name)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
lock = threading.Lock()

def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d.get("classes"), list) and isinstance(d.get("tasks"), dict):
            return d
    except (OSError, ValueError, AttributeError):
        pass
    return {"classes": DEFAULT_CLASSES[:], "tasks": {}}


def save_data(d):
    fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, DATA_FILE) 
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def code_ok(code):
    return secrets.compare_digest(str(code).strip().encode("utf-8"), TEACHER_CODE.encode("utf-8"))


def teacher_only(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not code_ok(request.headers.get("X-Teacher-Code", "")):
            return jsonify(error="Kod yanlış"), 403
        return fn(*args, **kwargs)
    return wrapper

@app.route("/")
def home():
    return send_from_directory(os.path.join(BASE_DIR, "templates"), "index.html")

@app.get("/api/data")
def get_data():
    with lock:
        d = load_data()
    resp = jsonify(d)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/health")
def health():
    return jsonify(version="v3", teacher_code_from_env=bool(_env_code))


@app.post("/api/login")
def login():
    body = request.get_json(silent=True) or {}
    if code_ok(body.get("code", "")):
        return "", 204
    return jsonify(error="Kod yanlış"), 403


@app.post("/api/classes")
@teacher_only
def add_class():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    if not name or len(name) > 20:
        return jsonify(error="Sınıf adı 1-20 karakter olmalı"), 400
    with lock:
        d = load_data()
        if any(c.lower() == name.lower() for c in d["classes"]):
            return jsonify(error="Bu sınıf zaten var"), 409
        d["classes"].append(name)
        save_data(d)
    return jsonify(name=name), 201


@app.post("/api/tasks")
@teacher_only
def add_task():
    body = request.get_json(silent=True) or {}
    cls = str(body.get("cls", ""))
    text = body.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="Dosya boş"), 400
    if len(text) > MAX_TEXT_CHARS:
        return jsonify(error="Dosya çok büyük"), 413
    task = { "id": uuid.uuid4().hex[:12],
        "cls": cls,
        "subject": str(body.get("subject", "")).strip()[:60],
        "teacher": str(body.get("teacher", "")).strip()[:100],
        "fileName": str(body.get("fileName", "odev.txt"))[:200],
        "text": text,
        "date": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }
    with lock:
        d = load_data()
        if cls not in d["classes"]:
            return jsonify(error="Böyle bir sınıf yok"), 400
        d["tasks"].setdefault(cls, []).append(task)
        save_data(d)
    return jsonify(task), 201


@app.delete("/api/tasks/<task_id>")
@teacher_only
def delete_task(task_id):
    with lock:
        d = load_data()
        for cls, items in d["tasks"].items():
            kept = [t for t in items if t.get("id") != task_id]
            if len(kept) != len(items):
                d["tasks"][cls] = kept
                save_data(d)
                return "", 204
    return jsonify(error="Ödev bulunamadı"), 404


if name == "main":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
