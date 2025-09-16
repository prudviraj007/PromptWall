import os
from flask import Flask, request, redirect, url_for, render_template
import psycopg
from psycopg.rows import dict_row
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)

# CSRF requires a SECRET_KEY; set via env in production
# e.g., export SECRET_KEY="a-strong-random-secret"
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
CSRFProtect(app)  # Global CSRF protection for POST/PUT/PATCH/DELETE

def _with_sslmode_require(url: str) -> str:
    if "sslmode=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}sslmode=require"

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")
DATABASE_URL = _with_sslmode_require(DATABASE_URL)

def get_conn():
    # psycopg3 dict_row returns rows as dicts: row["column"] access
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def init_db():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            prompt TEXT NOT NULL,
            result TEXT NOT NULL,
            workshop TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            image_url TEXT,
            image_data_url TEXT
        );
        """)
        conn.commit()

init_db()

def fetch_submissions(workshop=None, limit=100):
    where = "WHERE workshop = %s" if workshop else ""
    params = (workshop, limit) if workshop else (limit,)
    q = f"""
        SELECT id, name, prompt, result, workshop,
               to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') as created_at,
               image_url, image_data_url
        FROM submissions
        {where}
        ORDER BY id DESC
        LIMIT %s
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(q, params)
        return cur.fetchall()

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
    image_url = (request.form.get("image_url") or "").strip() or None
    image_data_url = (request.form.get("image_data_url") or "").strip() or None

    # Basic image data URL validation
    if image_data_url and not image_data_url.startswith("data:image/"):
        image_data_url = None
    if image_data_url and len(image_data_url) > 2_000_000:
        image_data_url = None

    if not name or not prompt or not result:
        return redirect(url_for("index", w=workshop) if workshop else url_for("index"))

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO submissions (name, prompt, result, workshop, image_url, image_data_url)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (name, prompt, result, workshop, image_url, image_data_url),
        )
        conn.commit()

    return redirect(url_for("index", w=workshop) if workshop else url_for("index"))

@app.route("/delete", methods=["POST"])
def delete():
    sid = (request.form.get("id") or "").strip()
    workshop = (request.form.get("workshop") or None)
    try:
        sid_int = int(sid)
    except ValueError:
        return redirect(url_for("index", w=workshop) if workshop else url_for("index"))

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM submissions WHERE id = %s", (sid_int,))
        conn.commit()

    return redirect(url_for("index", w=workshop) if workshop else url_for("index"))

if __name__ == "__main__":
    # Run locally; set host/port as needed
    app.run(host="127.0.0.1", port=8000, debug=True)
