import sqlite3
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["TEMPLATES_AUTO_RELOAD"] = True

DB_PATH = "submissions.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Drop old tables to start fresh with a new schema.
    c.execute("DROP TABLE IF EXISTS images")
    c.execute("DROP TABLE IF EXISTS submissions")

    c.execute("""
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        prompt TEXT NOT NULL,
        result TEXT NOT NULL,
        workshop TEXT,
        created_at TEXT NOT NULL
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id INTEGER NOT NULL,
        image_data_url TEXT,
        image_url TEXT,
        FOREIGN KEY(submission_id) REFERENCES submissions(id) ON DELETE CASCADE
    )
    """)
    conn.commit()
    conn.close()

init_db()

def fetch_submissions(workshop=None, limit=100):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if workshop:
        c.execute("""SELECT * FROM submissions WHERE workshop=? ORDER BY id DESC LIMIT ?""", (workshop, limit))
    else:
        c.execute("""SELECT * FROM submissions ORDER BY id DESC LIMIT ?""", (limit,))

    submissions = [dict(r) for r in c.fetchall()]

    for submission in submissions:
        c.execute("""SELECT * FROM images WHERE submission_id=? ORDER BY id ASC""", (submission['id'],))
        submission['images'] = [dict(r) for r in c.fetchall()]
    
    conn.close()
    return submissions

@app.route("/", methods=["GET"])
def index():
    workshop = request.args.get("w")
    submissions = fetch_submissions(workshop=workshop, limit=100)
    return render_template("index.html", submissions=submissions, workshop=workshop)

@app.route("/submit", methods=["POST"])
def submit():
    name = (request.form.get("name") or "")[:100]
    prompt = (request.form.get("prompt") or "")[:5000]
    result = (request.form.get("result") or "")[:10000]
    workshop = (request.form.get("workshop") or None)

    if not name or not prompt or not result:
        return redirect(url_for("index", w=workshop) if workshop else url_for("index"))

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""INSERT INTO submissions (name, prompt, result, workshop, created_at)
                VALUES (?, ?, ?, ?, ?)""",
              (name, prompt, result, workshop, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    
    submission_id = c.lastrowid
    
    image_data_urls = request.form.getlist("image_data_url")
    image_url = request.form.get("image_url", "").strip() or None

    if image_url:
        c.execute("""INSERT INTO images (submission_id, image_url) VALUES (?, ?)""", (submission_id, image_url))
    
    for data_url in image_data_urls:
        data_url = data_url.strip()
        if data_url and data_url.startswith("data:image/") and len(data_url) <= 2_000_000:
            c.execute("""INSERT INTO images (submission_id, image_data_url) VALUES (?, ?)""", (submission_id, data_url))

    conn.commit()
    conn.close()
    return redirect(url_for("index", w=workshop) if workshop else url_for("index"))

@app.route("/delete", methods=["POST"])
def delete():
    sid = (request.form.get("id") or "").strip()
    workshop = (request.form.get("workshop") or None)
    try:
        sid_int = int(sid)
    except ValueError:
        return redirect(url_for("index", w=workshop) if workshop else url_for("index"))
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM submissions WHERE id = ?", (sid_int,))
    conn.commit()
    conn.close()
    
    return redirect(url_for("index", w=workshop) if workshop else url_for("index"))

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
