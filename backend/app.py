from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import requests
import time
import os
import sqlite3
import random
import string
from datetime import datetime

app = Flask(__name__)
CORS(app)

DB_FILE = "stats.db"
ADMIN_PASSWORD = "razzyadminX567"
CACHE_TTL = 86400


# -----------------------------
# DATABASE INIT
# -----------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS stats (
        id INTEGER PRIMARY KEY,
        requests INTEGER DEFAULT 0,
        cache_hits INTEGER DEFAULT 0,
        downloads INTEGER DEFAULT 0,
        videos_served INTEGER DEFAULT 0,
        mb_served REAL DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        timestamp INTEGER
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS video_cache (
        url TEXT PRIMARY KEY,
        data TEXT,
        timestamp INTEGER
    )
    """)

    c.execute("INSERT OR IGNORE INTO stats (id) VALUES (1)")

    conn.commit()
    conn.close()

init_db()


# -----------------------------
# STATS FUNCTIONS
# -----------------------------
def increment_stat(field, amount=1):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute(
        f"UPDATE stats SET {field} = {field} + ? WHERE id = 1",
        (amount,)
    )

    conn.commit()
    conn.close()


# -----------------------------
# CACHE
# -----------------------------
def save_cache(url, data):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute(
        "INSERT OR REPLACE INTO video_cache(url,data,timestamp) VALUES(?,?,?)",
        (url, str(data), int(time.time()))
    )

    conn.commit()
    conn.close()


def load_cache(url):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute(
        "SELECT data,timestamp FROM video_cache WHERE url=?",
        (url,)
    )

    row = c.fetchone()
    conn.close()

    if not row:
        return None

    data, timestamp = row

    if time.time() - timestamp > CACHE_TTL:
        return None

    return eval(data)


# -----------------------------
# EMAIL API
# -----------------------------
@app.route("/save-email", methods=["POST"])
def save_email():

    data = request.get_json()
    email = data.get("email")

    if not email:
        return jsonify({"success": False})

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    try:
        c.execute(
            "INSERT OR IGNORE INTO emails(email,timestamp) VALUES(?,?)",
            (email, int(time.time()))
        )
        conn.commit()
    except:
        pass

    conn.close()

    return jsonify({"success": True})


@app.route("/admin/emails", methods=["POST"])
def get_emails():

    password = request.json.get("password")

    if password != ADMIN_PASSWORD:
        return jsonify({"success": False}), 401

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT email,timestamp FROM emails ORDER BY id DESC")
    emails = c.fetchall()

    conn.close()

    return jsonify({
        "success": True,
        "emails": [
            {
                "email": e[0],
                "timestamp": e[1]
            }
            for e in emails
        ]
    })


# -----------------------------
# URL NORMALIZER
# -----------------------------
def normalize_twitter_url(url):

    url = url.strip()

    if "x.com" in url:
        url = url.replace("x.com", "twitter.com")

    if "mobile.twitter.com" in url:
        url = url.replace("mobile.twitter.com", "twitter.com")

    if "?" in url:
        url = url.split("?")[0]

    return url


# -----------------------------
# DOWNLOAD INFO
# -----------------------------
@app.route("/download", methods=["POST"])
def download():
    # count the request
    increment_stat("requests")

    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"success": False, "message": "No URL provided"}), 400

    # normalize and check cache
    url = normalize_twitter_url(url)
    cached = load_cache(url)
    if cached:
        increment_stat("cache_hits")
        return jsonify(cached)

    try:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "format": "best",
            "nocheckcertificate": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            },
            "ignoreerrors": True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return jsonify({"success": False, "message": "Failed to extract video info"}), 500

        # desired qualities: 480, 720, 1080, 2160 (2k/4k)
        allowed_heights = [480, 720, 1080, 2160]
        added = set()
        videos = []

        # iterate formats and map each to the closest allowed height (one per allowed height)
        for f in info.get("formats", []):
            # require an mp4-like container (keeps compatibility with your frontend)
            if f.get("ext") != "mp4":
                continue

            # use explicit height if available
            h = f.get("height")
            if not h:
                # some formats don't have height; skip them (keeps results reliable)
                continue

            # map to closest allowed height
            closest = min(allowed_heights, key=lambda x: abs(x - h))

            # only add one format per allowed height
            if closest in added:
                continue

            size = f.get("filesize") or f.get("filesize_approx") or 0
            filesize_mb = round(size / 1024 / 1024, 2) if size else None

            # friendly label: treat 2160 as the "2k/4k" option per your request
            quality_label = "2k/4k (2160p)" if closest == 2160 else f"{closest}p"

            videos.append({
                "url": f.get("url"),
                "quality": quality_label,
                "height": closest,
                "filesize": size,
                "filesize_mb": filesize_mb
            })

            added.add(closest)

        if not videos:
            return jsonify({"success": False, "message": "No downloadable mp4 found"}), 404

        # sort from highest -> lowest so frontend picks best first
        videos.sort(key=lambda x: x["height"], reverse=True)

        result = {
            "success": True,
            "title": info.get("title") or "Untitled Video",
            "videos": videos
        }

        # cache the result
        save_cache(url, result)

        return jsonify(result)

    except Exception as e:
        import traceback
        print("DOWNLOAD ERROR:", traceback.format_exc())
        return jsonify({"success": False, "message": "Extraction failed"}), 500


# -----------------------------
# PROXY STREAM + RENAME
# -----------------------------
@app.route("/proxy")
def proxy():

    video_url = request.args.get("url")

    if not video_url:
        return "No URL", 400

    increment_stat("downloads")

    headers = {}

    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]

    r = requests.get(
        video_url,
        headers=headers,
        stream=True
    )

    random_id = ''.join(
        random.choices(
            string.ascii_uppercase +
            string.digits,
            k=6
        )
    )

    filename = f"ToolifyX Downloader_{random_id}.mp4"

    response_headers = {

        "Content-Type": "video/mp4",

        "Accept-Ranges": "bytes",

        "Content-Disposition":
        f'attachment; filename="{filename}"'
    }

    if "Content-Range" in r.headers:

        response_headers["Content-Range"] = \
        r.headers["Content-Range"]

    return Response(
        r.iter_content(chunk_size=8192),
        status=r.status_code,
        headers=response_headers
    )


# -----------------------------
# HEALTH
# -----------------------------
@app.route("/")
def home():

    return jsonify({

        "status": "ok",

        "service": "ToolifyX Downloader API"
    })


# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 5000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )