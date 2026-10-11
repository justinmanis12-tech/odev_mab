import os
import secrets
import threading
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory
from supabase import create_client, Client

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Подключение к Supabase из переменных окружения Render
SUPABASE_URL = os.environ.get("SUPABASE_URL")
# Поддерживаем как service_role, так и anon ключ
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Критическая ошибка: SUPABASE_URL и SUPABASE_KEY должны быть заданы в переменных окружения Render!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

_env_code = os.environ.get("TEACHER_CODE")
TEACHER_CODE = (_env_code if _env_code else "ogretmen").strip().strip("\"'").strip()

GRADES = [9, 10, 11, 12]
SECTIONS = ["ATP", "A", "B", "C", "D", "Özel Sınıf"]
DEFAULT_CLASSES = [f"{g}-{s}" for g in GRADES for s in SECTIONS]

MAX_TEXT_CHARS = 400_000

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
lock = threading.Lock()


def load_data():
    """Загружает классы и задачи из Supabase, формируя структуру для фронтенда"""
    try:
        # Загружаем классы
        res_classes = supabase.table("classes").select("name").execute()
        classes = [row["name"] for row in (res_classes.data or [])]

        # Если таблица классов пуста, автоматически заполняем дефолтными
        if not classes:
            classes = DEFAULT_CLASSES[:]
            for c in classes:
                try:
                    supabase.table("classes").insert({"name": c}).execute()
                except Exception:
                    pass

        # Загружаем задачи
        res_tasks = supabase.table("tasks").select("*").execute()
        tasks_dict = {}
        for t in (res_tasks.data or []):
            cls_name = t.get("cls")
            task_obj = {
                "id": t.get("id"),
                "cls": cls_name,
                "subject": t.get("subject", ""),
                "teacher": t.get("teacher", ""),
                "fileName": t.get("file_name", "odev.txt"),
                "text": t.get("task_text", ""),
                "date": t.get("date"),
            }
            tasks_dict.setdefault(cls_name, []).append(task_obj)

        return {"classes": classes, "tasks": tasks_dict}
    except Exception as e:
        print(f"Ошибка при загрузке данных из Supabase: {e}")
        return {"classes": DEFAULT_CLASSES[:], "tasks": {}}


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
    return jsonify(version="v3-supabase-ready", teacher_code_from_env=bool(_env_code))


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
        try:
            # Проверяем, есть ли уже такой класс
            check = supabase.table("classes").select("name").eq("name", name).execute()
            if check.data and len(check.data) > 0:
                return jsonify(error="Bu sınıf zaten var"), 409

            res = supabase.table("classes").insert({"name": name}).execute()
            if not res.data:
                return jsonify(error="Bu sınıf zaten var"), 409
        except Exception as e:
            return jsonify(error=f"Kayıt hatası: {str(e)}"), 409
            
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

    task_id = uuid.uuid4().hex[:12]
    task_row = {
        "id": task_id,
        "cls": cls,
        "subject": str(body.get("subject", "")).strip()[:60],
        "teacher": str(body.get("teacher", "")).strip()[:100],
        "file_name": str(body.get("fileName", "odev.txt"))[:200],
        "task_text": text,
        "date": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }

    with lock:
        # Проверяем существование класса в базе
        cls_check = supabase.table("classes").select("name").eq("name", cls).execute()
        if not cls_check.data:
            return jsonify(error="Böyle bir sınıf yok"), 400

        try:
            supabase.table("tasks").insert(task_row).execute()
        except Exception as e:
            return jsonify(error=f"Kayıт hatası: {str(e)}"), 500

    task_response = {
        "id": task_id,
        "cls": cls,
        "subject": task_row["subject"],
        "teacher": task_row["teacher"],
        "fileName": task_row["file_name"],
        "text": text,
        "date": task_row["date"],
    }
    return jsonify(task_response), 201


@app.delete("/api/tasks/<task_id>")
@teacher_only
def delete_task(task_id):
    with lock:
        try:
            res = supabase.table("tasks").delete().eq("id", task_id).execute()
            if res.data and len(res.data) > 0:
                return "", 204
        except Exception:
            pass
    return jsonify(error="Ödev bulunamadı"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
