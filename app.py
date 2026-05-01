import os
import re
import cloudinary
import cloudinary.uploader
from flask import Flask, render_template, request, redirect, session, g, jsonify, url_for
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "secret-key-change-in-production"

DATABASE = "tasks.db"

# =======================
# Cloudinary設定
# =======================
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)


# =======================
# DB管理
# =======================
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()


# =======================
# DB初期化
# =======================
def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        avatar_url TEXT DEFAULT NULL
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        done INTEGER DEFAULT 0,
        deadline TEXT,
        position INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """)
    db.commit()

with app.app_context():
    init_db()


# =======================
# ユーティリティ
# =======================
def require_login():
    return "user_id" in session

def validate_password(password):
    if len(password) < 8:
        return False
    if not re.search(r"[A-Za-z]", password):
        return False
    if not re.search(r"[0-9]", password):
        return False
    return True

def get_current_user():
    if not require_login():
        return None
    return get_db().execute(
        "SELECT * FROM users WHERE id=?", (session["user_id"],)
    ).fetchone()


# =======================
# ページ: メイン
# =======================
@app.route("/")
def index():
    if not require_login():
        return redirect("/login")
    user = get_current_user()
    if not user:
        return redirect("/login")
    return render_template("index.html", username=user["username"], avatar_url=user["avatar_url"])


# =======================
# ページ: プロフィール
# =======================
@app.route("/profile", methods=["GET", "POST"])
def profile():
    if not require_login():
        return redirect("/login")

    user = get_current_user()
    db = get_db()
    errors = {}
    success = None

    if request.method == "POST":
        action = request.form.get("action")

        # ユーザー名変更
        if action == "username":
            new_username = request.form.get("username", "").strip()
            if not new_username:
                errors["username"] = "ユーザー名を入力してください"
            else:
                try:
                    db.execute("UPDATE users SET username=? WHERE id=?", (new_username, user["id"]))
                    db.commit()
                    success = "ユーザー名を変更しました"
                except:
                    errors["username"] = "そのユーザー名は既に使われています"

        # パスワード変更
        elif action == "password":
            current_pw = request.form.get("current_password", "")
            new_pw = request.form.get("new_password", "")
            confirm_pw = request.form.get("confirm_password", "")

            if not check_password_hash(user["password"], current_pw):
                errors["password"] = "現在のパスワードが正しくありません"
            elif not validate_password(new_pw):
                errors["password"] = "パスワードは英字と数字を含む8文字以上にしてください"
            elif new_pw != confirm_pw:
                errors["password"] = "新しいパスワードが一致しません"
            else:
                db.execute("UPDATE users SET password=? WHERE id=?",
                           (generate_password_hash(new_pw), user["id"]))
                db.commit()
                success = "パスワードを変更しました"

        # アバター変更（Cloudinaryにアップロード）
        elif action == "avatar":
            file = request.files.get("avatar")
            if file and file.filename:
                try:
                    # Cloudinaryにアップロード（user_idをpublic_idに使い上書き可能にする）
                    result = cloudinary.uploader.upload(
                        file,
                        public_id=f"avatars/user_{user['id']}",
                        overwrite=True,
                        transformation=[
                            {"width": 200, "height": 200, "crop": "fill", "gravity": "face"}
                        ]
                    )
                    avatar_url = result["secure_url"]
                    db.execute("UPDATE users SET avatar_url=? WHERE id=?", (avatar_url, user["id"]))
                    db.commit()
                    success = "プロフィール画像を変更しました"
                except Exception as e:
                    errors["avatar"] = f"アップロードに失敗しました: {str(e)}"
            else:
                errors["avatar"] = "画像ファイルを選択してください"

        user = get_current_user()

    return render_template("profile.html", user=user, avatar_url=user["avatar_url"], errors=errors, success=success)


# =======================
# API: タスク一覧
# =======================
@app.route("/api/tasks")
def api_tasks():
    if not require_login():
        return jsonify({"error": "unauthorized"}), 401

    db = get_db()
    user_id = session["user_id"]
    sort = request.args.get("sort", "deadline")
    today = datetime.today().strftime("%Y-%m-%d")

    if sort == "manual":
        rows = db.execute("""
            SELECT id, title, done, deadline FROM tasks
            WHERE user_id=? ORDER BY position ASC
        """, (user_id,)).fetchall()
    else:
        rows = db.execute("""
            SELECT id, title, done, deadline FROM tasks
            WHERE user_id=?
            ORDER BY
                CASE WHEN deadline IS NULL OR deadline='' THEN 1 ELSE 0 END,
                deadline ASC, id DESC
        """, (user_id,)).fetchall()

    return jsonify([{
        "id": r["id"],
        "title": r["title"],
        "done": bool(r["done"]),
        "deadline": r["deadline"] or "",
        "overdue": bool(r["deadline"] and r["deadline"] < today)
    } for r in rows])


# =======================
# API: タスク追加
# =======================
@app.route("/api/tasks", methods=["POST"])
def api_add_task():
    if not require_login():
        return jsonify({"error": "unauthorized"}), 401

    db = get_db()
    user_id = session["user_id"]
    data = request.get_json()
    title = data.get("title", "").strip()
    deadline = data.get("deadline", "") or None

    if not title:
        return jsonify({"error": "title required"}), 400

    row = db.execute("SELECT MAX(position) as m FROM tasks WHERE user_id=?", (user_id,)).fetchone()
    new_pos = (row["m"] + 1) if row["m"] is not None else 0

    db.execute(
        "INSERT INTO tasks (user_id, title, done, deadline, position) VALUES (?, ?, 0, ?, ?)",
        (user_id, title, deadline, new_pos)
    )
    db.commit()
    new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    today = datetime.today().strftime("%Y-%m-%d")

    return jsonify({
        "id": new_id, "title": title, "done": False,
        "deadline": deadline or "",
        "overdue": bool(deadline and deadline < today)
    }), 201


# =======================
# API: 完了切替
# =======================
@app.route("/api/tasks/<int:id>/toggle", methods=["POST"])
def api_toggle(id):
    if not require_login():
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()
    user_id = session["user_id"]
    row = db.execute("SELECT done FROM tasks WHERE id=? AND user_id=?", (id, user_id)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    new_done = 1 - row["done"]
    db.execute("UPDATE tasks SET done=? WHERE id=? AND user_id=?", (new_done, id, user_id))
    db.commit()
    return jsonify({"id": id, "done": bool(new_done)})


# =======================
# API: 編集
# =======================
@app.route("/api/tasks/<int:id>", methods=["PATCH"])
def api_edit(id):
    if not require_login():
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()
    user_id = session["user_id"]
    data = request.get_json()
    title = data.get("title", "").strip()
    deadline = data.get("deadline", "") or None
    if not title:
        return jsonify({"error": "title required"}), 400
    db.execute("UPDATE tasks SET title=?, deadline=? WHERE id=? AND user_id=?",
               (title, deadline, id, user_id))
    db.commit()
    today = datetime.today().strftime("%Y-%m-%d")
    return jsonify({
        "id": id, "title": title,
        "deadline": deadline or "",
        "overdue": bool(deadline and deadline < today)
    })


# =======================
# API: 削除
# =======================
@app.route("/api/tasks/<int:id>", methods=["DELETE"])
def api_delete(id):
    if not require_login():
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (id, session["user_id"]))
    db.commit()
    return jsonify({"status": "ok"})


# =======================
# API: 並び替え
# =======================
@app.route("/api/reorder", methods=["POST"])
def api_reorder():
    if not require_login():
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()
    user_id = session["user_id"]
    order = request.get_json().get("order", [])
    for index, task_id in enumerate(order):
        db.execute("UPDATE tasks SET position=? WHERE id=? AND user_id=?",
                   (index, task_id, user_id))
    db.commit()
    return jsonify({"status": "ok"})


# =======================
# register
# =======================
@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username:
            error = "ユーザー名を入力してください"
        elif not validate_password(password):
            error = "パスワードは英字と数字を含む8文字以上にしてください"
        else:
            try:
                db = get_db()
                db.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                           (username, generate_password_hash(password)))
                db.commit()
                return redirect("/login")
            except:
                error = "そのユーザー名は既に使われています"
    return render_template("register.html", error=error)


# =======================
# login
# =======================
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            return redirect("/")
        error = "ユーザー名またはパスワードが正しくありません"
    return render_template("login.html", error=error)


# =======================
# logout
# =======================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


if __name__ == "__main__":
    app.run(debug=True)