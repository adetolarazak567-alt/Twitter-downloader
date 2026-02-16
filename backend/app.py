from flask import Flask, request, jsonify, Response, render_template_string
from flask_cors import CORS
import yt_dlp
import requests
import time
import os
import sqlite3

app = Flask(__name__)
CORS(app)

ADMIN_PASSWORD = "razzyadminX567"

DB_FILE = "stats.db"

# -----------------------------
# DATABASE INIT
# -----------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS stats (
        id INTEGER PRIMARY KEY,
        requests INTEGER DEFAULT 0,
        downloads INTEGER DEFAULT 0,
        cache_hits INTEGER DEFAULT 0,
        videos_served INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS ips (
        ip TEXT PRIMARY KEY
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip TEXT,
        url TEXT,
        timestamp INTEGER
    )
    """)

    c.execute("INSERT OR IGNORE INTO stats (id) VALUES (1)")

    conn.commit()
    conn.close()

init_db()

# -----------------------------
# STAT FUNCTIONS
# -----------------------------
def increment_stat(field):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f"UPDATE stats SET {field} = {field} + 1 WHERE id = 1")
    conn.commit()
    conn.close()

def save_ip(ip):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO ips (ip) VALUES (?)", (ip,))
    conn.commit()
    conn.close()

def save_log(ip, url):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO logs (ip, url, timestamp) VALUES (?, ?, ?)",
        (ip, url, int(time.time()))
    )
    conn.commit()
    conn.close()

# -----------------------------
# CACHE
# -----------------------------
CACHE = {}
CACHE_TTL = 600

def normalize_twitter_url(url):
    if "x.com" in url:
        url = url.replace("x.com", "twitter.com")
    if "mobile.twitter.com" in url:
        url = url.replace("mobile.twitter.com", "twitter.com")
    return url

# -----------------------------
# VIDEO FETCH
# -----------------------------
def fetch_video_info(url):

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "format": "bestvideo+bestaudio/best",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:

        info = ydl.extract_info(url, download=False)

        formats = info.get("formats", [])

        videos = []

        for f in formats:

            if f.get("ext") == "mp4":

                videos.append({
                    "url": f.get("url"),
                    "quality": f.get("format_note", "auto")
                })

        return {
            "success": True,
            "title": info.get("title"),
            "videos": videos
        }

# -----------------------------
# DOWNLOAD
# -----------------------------
@app.route("/download", methods=["POST"])
def download():

    increment_stat("requests")

    data = request.get_json(silent=True) or {}
url = data.get("url")

    if not url:
        return jsonify({"success": False, "message": "No URL provided"}), 400

    url = normalize_twitter_url(url)

    ip = request.remote_addr

    save_ip(ip)

    now = time.time()

    if url in CACHE and now - CACHE[url]["time"] < CACHE_TTL:

        increment_stat("cache_hits")

        return jsonify(CACHE[url]["data"])

    info = fetch_video_info(url)

    CACHE[url] = {
        "time": now,
        "data": info
    }

    return jsonify(info)

# -----------------------------
# PROXY
# -----------------------------
@app.route("/proxy")
def proxy():

    video_url = request.args.get("url")

    if not video_url:
        return jsonify({"success": False, "message": "No video URL"}), 400

    ip = request.remote_addr

    increment_stat("downloads")
    increment_stat("videos_served")

    save_ip(ip)
    save_log(ip, video_url)

    r = requests.get(video_url, stream=True)

    return Response(
        r.iter_content(chunk_size=8192),
        content_type="video/mp4"
    )

# -----------------------------
# STATS
# -----------------------------
@app.route("/stats")
def stats():

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute(
        "SELECT requests, downloads, cache_hits, videos_served FROM stats WHERE id=1"
    )

    s = c.fetchone()

    if not s:
        s = (0, 0, 0, 0)

    c.execute("SELECT COUNT(*) FROM ips")
    unique_ips = c.fetchone()[0]

    c.execute(
        "SELECT ip, url, timestamp FROM logs ORDER BY id DESC LIMIT 100"
    )

    logs = [
        {
            "ip": row[0],
            "url": row[1],
            "timestamp": row[2]
        }
        for row in c.fetchall()
    ]

    conn.close()

    return jsonify({
        "requests": s[0],
        "downloads": s[1],
        "cache_hits": s[2],
        "videos_served": s[3],
        "unique_ips": unique_ips,
        "download_logs": logs
    })

# -----------------------------
# RESET
# -----------------------------
@app.route("/admin/reset", methods=["POST"])
def reset():

    password = request.json.get("password")

    if password != ADMIN_PASSWORD:

        return jsonify({"success": False}), 401

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute(
        "UPDATE stats SET requests=0, downloads=0, cache_hits=0, videos_served=0"
    )

    c.execute("DELETE FROM ips")

    c.execute("DELETE FROM logs")

    conn.commit()
    conn.close()

    return jsonify({"success": True})

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(host="0.0.0.0", port=port)