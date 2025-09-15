import os
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template_string
import psycopg
from psycopg.rows import dict_row

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

TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Workshop Submissions</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      :root { --card-bg: #fff; --card-border: #e5e7eb; --muted: #6b7280; --ink: #111827; --bg: #f6f7f9; }
      html, body { margin: 0; background: var(--bg); color: var(--ink); font-family: system-ui, Arial, sans-serif; }
      .wrap { max-width: 840px; margin: 24px auto; padding: 0 16px; }
      h1, h2 { margin: 0 0 12px; }
      p { color: var(--muted); }
      form { display: grid; gap: 12px; margin-top: 12px; }
      input, textarea { padding: 10px; font-size: 16px; width: 100%; box-sizing: border-box; border: 1px solid var(--card-border); border-radius: 6px; background: #fff; }
      button { padding: 10px 14px; font-size: 16px; background: #111; color: #fff; border: 0; border-radius: 6px; cursor: pointer; }
      .card { display: grid; grid-template-columns: 6px 1fr; gap: 12px; border: 1px solid var(--card-border); border-radius: 10px; background: var(--card-bg); padding: 12px; }
      .bar { background: #e5e7eb; border-radius: 4px; }
      .topline { font-weight: 600; display: flex; gap: 8px; align-items: center; }
      .meta { color: var(--muted); font-weight: 400; font-size: 12px; }
      .muted { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
      pre { white-space: pre-wrap; margin: 0; }
      .grid { display: grid; gap: 12px; }
      img.thread-image { max-width: 100%; height: auto; display: block; margin-top: 8px; border-radius: 6px; }
      .pastezone { border: 1px dashed #c7cdd4; border-radius: 8px; padding: 16px; color: var(--muted); background: #fbfcfe; }
      .pastezone.focus { outline: 2px solid #4f46e5; outline-offset: 2px; }
      .two-col { display: grid; gap: 8px; }
      @media (min-width: 720px) { .two-col { grid-template-columns: 1fr 1fr; } }
    </style>
  </head>
  <body>
    <div class="wrap">
      <h1>Workshop Submissions</h1>
      <p>Submit name, prompt, and result; paste a screenshot in the box or provide an image URL; append <code>?w=TEAM</code> to segment groups.</p>

      <form method="post" action="{{ url_for('submit') }}">
        <input type="hidden" name="workshop" value="{{ workshop or '' }}" />
        <input required maxlength="100" name="name" placeholder="Name" />
        <textarea required maxlength="5000" name="prompt" placeholder="Prompt" rows="4"></textarea>
        <textarea required maxlength="10000" name="result" placeholder="Result (paste model output)" rows="6"></textarea>

        <div class="two-col">
          <div>
            <div class="muted">Paste Screenshot</div>
            <div id="pastezone" class="pastezone" tabindex="0">
              Click and press Ctrl+V/Cmd+V to paste an image, or drop an image file.
            </div>
            <input type="hidden" id="image_data_url" name="image_data_url" />
            <img id="image_preview" class="thread-image" style="display:none" alt="pasted screenshot preview" draggable="false" />
          </div>
          <div>
            <div class="muted">Image URL (optional)</div>
            <input name="image_url" placeholder="https://example.com/image.png" />
          </div>
        </div>

        <button type="submit">Submit</button>
      </form>

      <h2 style="margin-top:32px">Recent Submissions {{ '(' + workshop + ')' if workshop else '' }}</h2>
      <div class="grid" style="margin-top:8px">
        {% if submissions %}
          {% for s in submissions %}
            <div class="card">
              <div class="bar"></div>
              <div>
                <div class="topline">
                  <span>{{ s['name'] }}</span>
                  <span class="meta">• {{ s['created_at'] }}{% if s['workshop'] %} • {{ s['workshop'] }}{% endif %}</span>
                </div>

                <div style="margin-top:10px">
                  <div class="muted">Prompt</div>
                  <pre>{{ s['prompt'] }}</pre>
                </div>

                <div style="margin-top:10px">
                  <div class="muted">Result</div>
                  <pre>{{ s['result'] }}</pre>
                </div>

                {% if s['image_data_url'] %}
                  <div class="muted" style="margin-top:10px">Screenshot</div>
                  <img src="{{ s['image_data_url'] }}" alt="pasted screenshot" class="thread-image" draggable="false" />
                {% elif s['image_url'] %}
                  <div class="muted" style="margin-top:10px">Image</div>
                  <img src="{{ s['image_url'] }}" alt="linked image" class="thread-image" draggable="false" />
                {% endif %}
              </div>
            </div>
          {% endfor %}
        {% else %}
          <div>No submissions yet.</div>
        {% endif %}
      </div>
    </div>

    <script>
      const pasteZone = document.getElementById('pastezone');
      const hiddenInput = document.getElementById('image_data_url');
      const preview = document.getElementById('image_preview');

      function setPreview(dataUrl) {
        hiddenInput.value = dataUrl;
        preview.src = dataUrl;
        preview.style.display = 'block';
        pasteZone.textContent = 'Screenshot attached. Paste again or drop another image to replace.';
      }

      function compressImageFile(file, maxW = 1280, maxH = 1280, quality = 0.8) {
        return new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onerror = reject;
          reader.onload = () => {
            const img = new Image();
            img.onload = () => {
              const ratio = Math.min(maxW / img.width, maxH / img.height, 1);
              const w = Math.round(img.width * ratio);
              const h = Math.round(img.height * ratio);
              const canvas = document.createElement('canvas');
              canvas.width = w;
              canvas.height = h;
              const ctx = canvas.getContext('2d');
              ctx.drawImage(img, 0, 0, w, h);
              const dataUrl = canvas.toDataURL('image/jpeg', quality);
              resolve(dataUrl);
            };
            img.onerror = reject;
            img.src = reader.result;
          };
          reader.readAsDataURL(file);
        });
      }

      pasteZone.addEventListener('focus', () => pasteZone.classList.add('focus'));
      pasteZone.addEventListener('blur', () => pasteZone.classList.remove('focus'));

      pasteZone.addEventListener('paste', async (e) => {
        if (!e.clipboardData) return;
        for (const item of e.clipboardData.items) {
          if (item.kind === 'file' && item.type.startsWith('image/')) {
            e.preventDefault();
            const file = item.getAsFile();
            if (file) {
              const dataUrl = await compressImageFile(file);
              setPreview(dataUrl);
            }
            break;
          }
        }
      });

      pasteZone.addEventListener('dragover', (e) => { e.preventDefault(); pasteZone.classList.add('focus'); });
      pasteZone.addEventListener('dragleave', () => pasteZone.classList.remove('focus'));
      pasteZone.addEventListener('drop', async (e) => {
        e.preventDefault();
        pasteZone.classList.remove('focus');
        const file = e.dataTransfer.files && e.dataTransfer.files;
        if (file && file.type.startsWith('image/')) {
          const dataUrl = await compressImageFile(file);
          setPreview(dataUrl);
        }
      });
    </script>
  </body>
</html>
"""

def fetch_submissions(workshop=None, limit=100):
    where = "WHERE workshop = %s" if workshop else ""
    params = (workshop, limit) if workshop else (limit,)
    q = f"""
        SELECT name, prompt, result, workshop,
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
    return render_template_string(TEMPLATE, submissions=submissions, workshop=workshop)

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

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
