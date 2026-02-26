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


# -----------------------------
# DATABASE INIT
# -----------------------------

def init_db():

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Main stats
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

    # Unique IPs
    c.execute("""
    CREATE TABLE IF NOT EXISTS ips (
        ip TEXT PRIMARY KEY
    )
    """)

    # Logs
    c.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip TEXT,
        url TEXT,
        timestamp INTEGER
    )
    """)

    # Daily stats
    c.execute("""
    CREATE TABLE IF NOT EXISTS daily (
        date TEXT PRIMARY KEY,
        downloads INTEGER DEFAULT 0,
        mb_served REAL DEFAULT 0
    )
    """)

    # EMAIL LIST TABLE (NEW)
    c.execute("""
    CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        timestamp INTEGER
    )
    """)

    # PERMANENT CACHE TABLE (NEW)
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
# EMAIL SAVE API (NEW)
# -----------------------------

@app.route("/save-email", methods=["POST"])
def save_email():

    data = request.json
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


# -----------------------------
# GET EMAILS ADMIN (NEW)
# -----------------------------

@app.route("/admin/emails", methods=["POST"])
def get_emails():

    password = request.json.get("password")

    if password != ADMIN_PASSWORD:
        return jsonify({"success": False}), 401

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        SELECT email,timestamp
        FROM emails
        ORDER BY id DESC
    """)

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
# STAT FUNCTIONS
# -----------------------------

def increment_stat(field, amount=1):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute(f"""
        UPDATE stats
        SET {field} = {field} + ?
        WHERE id = 1
    """, (amount,))

    conn.commit()
    conn.close()


def increment_daily(mb):

    today = datetime.utcnow().strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        INSERT INTO daily(date, downloads, mb_served)
        VALUES (?, 1, ?)
        ON CONFLICT(date)
        DO UPDATE SET
            downloads = downloads + 1,
            mb_served = mb_served + ?
    """, (today, mb, mb))

    conn.commit()
    conn.close()


# -----------------------------
# PERMANENT CACHE LOAD/SAVE (NEW)
# -----------------------------

def save_cache(url, data):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        INSERT OR REPLACE INTO video_cache(url,data,timestamp)
        VALUES(?,?,?)
    """, (url, str(data), int(time.time())))

    conn.commit()
    conn.close()


def load_cache(url):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        SELECT data FROM video_cache WHERE url=?
    """, (url,))

    row = c.fetchone()

    conn.close()

    if row:
        return eval(row[0])

    return None


# -----------------------------
# DOWNLOAD INFO
# -----------------------------

@app.route("/download", methods=["POST"])
def download():

    increment_stat("requests")

    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"success": False}), 400

    # CHECK PERMANENT CACHE FIRST
    cached = load_cache(url)
    if cached:
        increment_stat("cache_hits")
        return jsonify(cached)

    try:

        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "format": "bestvideo+bestaudio/best"
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            info = ydl.extract_info(url, download=False)
            videos = []

            allowed_heights = [320, 720, 1080, 2160]
            added = set()

            for f in info["formats"]:

                if f.get("ext") != "mp4":
                    continue

                h = f.get("height")
                if not h:
                    continue

                closest = min(allowed_heights, key=lambda x: abs(x-h))

                if closest in added:
                    continue

                size = f.get("filesize") or f.get("filesize_approx") or 0

                videos.append({
                    "url": f["url"],
                    "quality": f"{closest}p",
                    "height": closest,
                    "filesize": size,
                    "filesize_mb": round(size/1024/1024,2) if size else None
                })

                added.add(closest)

        videos.sort(key=lambda x:x["height"], reverse=True)

        result = {
            "success": True,
            "title": info.get("title"),
            "videos": videos
        }

        save_cache(url, result)

        return jsonify(result)

    except Exception as e:

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# -----------------------------
# PROXY FIXED SIZE ACCURACY
# -----------------------------

@app.route("/proxy")
def proxy():

    url = request.args.get("url")
    download = request.args.get("download")

    if not url:
        return "Missing URL", 400

    try:

        r = requests.get(url, stream=True)

        total = int(r.headers.get("Content-Length", 0))

        increment_stat("downloads")

        increment_stat("videos_served")

        mb = total / 1024 / 1024

        increment_stat("mb_served", mb)

        increment_daily(mb)

        headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(total),
            "Accept-Ranges": "bytes"
        }

        filename = "ToolifyX.mp4"

        if download == "1":

            headers["Content-Disposition"] = \
                f"attachment; filename={filename}"

        else:

            headers["Content-Disposition"] = \
                f"inline; filename={filename}"

        return Response(
            r.iter_content(chunk_size=8192),
            headers=headers
        )

    except Exception as e:

        return str(e), 500


# -----------------------------
# STATS API
# -----------------------------

@app.route("/stats")
def stats():

    return jsonify({"success": True})


# -----------------------------
# RUN
# -----------------------------

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(host="0.0.0.0", port=port)