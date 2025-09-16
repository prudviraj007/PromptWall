import os
import json
import base64
from io import BytesIO
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template
import psycopg
from psycopg.rows import dict_row
from PIL import Image
from google import genai
from google.genai import types

app = Flask(__name__)

def _with_sslmode_require(url: str) -> str:
    if "sslmode=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}sslmode=require"

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")
DATABASE_URL = _with_sslmode_require(DATABASE_URL)

def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def init_db():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
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
            """
        )
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

@app.route("/image-lab", methods=["GET"])
def image_lab():
    defaults = {
        "model": "gemini-2.5-flash-image-preview",
        "count": 2,
        "api_key": "",
    }
    return render_template("image_lab.html", results=None, defaults=defaults)

def _data_url_from_bytes(img_bytes: bytes, mime: str = "image/png") -> str:
    b64 = base64.b64encode(img_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"

@app.route("/image-lab/generate", methods=["POST"])
def image_lab_generate():
    form_api_key = (request.form.get("api_key") or "").strip()
    model = "gemini-2.5-flash-image-preview"
    count = max(1, min(int(request.form.get("count") or 1), 4))
    prompts_json = request.form.get("prompts_json") or "[]"

    try:
        prompts = [p.strip() for p in json.loads(prompts_json) if p and p.strip()]
    except Exception:
        prompts = []

    ref_file = request.files.get("reference")
    ref_image = None
    if ref_file and ref_file.filename:
        ref_image = Image.open(ref_file.stream).convert("RGB")

    client = genai.Client(api_key=form_api_key) if form_api_key else genai.Client()
    results = []

    for prompt in prompts:
        for _ in range(count):
            try:
                contents = [prompt]
                if ref_image:
                    contents.append(ref_image)

                resp = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_modalities=[types.Modality.IMAGE]
                    ),
                )

                added = False
                for part in resp.candidates[0].content.parts:
                    if getattr(part, "inline_data", None):
                        mime = getattr(part.inline_data, "mime_type", "image/png")
                        img_bytes = part.inline_data.data
                        results.append({
                            "prompt": prompt,
                            "data_url": _data_url_from_bytes(img_bytes, mime),
                        })
                        added = True
                        break
                if not added:
                    results.append({
                        "prompt": prompt,
                        "error": "No image returned; try refining the prompt.",
                    })

            except Exception as e:
                results.append({"prompt": prompt, "error": str(e)})

    defaults = {
        "model": model,
        "count": count,
        "api_key": form_api_key,
    }
    return render_template("image_lab.html", results=results, defaults=defaults)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
