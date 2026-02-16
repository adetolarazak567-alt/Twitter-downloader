from flask import Flask, request, jsonify, Response, render_template_string
from flask_cors import CORS
import yt_dlp
import requests
import time
import os
import sqlite3

app = Flask(__name__)
CORS(app)

# -----------------------------
# DATABASE (NEW - permanent stats)
# -----------------------------

DB_FILE = "stats.db"
ADMIN_PASSWORD = "razzyadminX567"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS stats (
        id INTEGER PRIMARY KEY,
        requests INTEGER DEFAULT 0,
        cache_hits INTEGER DEFAULT 0,
        downloads INTEGER DEFAULT 0,
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
# STAT FUNCTIONS (NEW)
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


def get_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT requests, cache_hits, downloads, videos_served FROM stats WHERE id=1")
    stats = c.fetchone()

    c.execute("SELECT COUNT(*) FROM ips")
    unique_ips = c.fetchone()[0]

    c.execute("SELECT ip, url, timestamp FROM logs ORDER BY id DESC LIMIT 100")
    logs = c.fetchall()

    conn.close()

    return {
        "requests": stats[0],
        "cache_hits": stats[1],
        "downloads": stats[2],
        "videos_served": stats[3],
        "unique_ips": unique_ips,
        "download_logs": [
            {
                "ip": row[0],
                "url": row[1],
                "timestamp": row[2]
            }
            for row in logs
        ]
    }


# -----------------------------
# CACHE (UNCHANGED)
# -----------------------------

CACHE = {}
CACHE_TTL = 600


# -----------------------------
# HELPERS (UNCHANGED)
# -----------------------------

def normalize_twitter_url(url: str) -> str:
    if "x.com" in url:
        url = url.replace("x.com", "twitter.com")
    if "mobile.twitter.com" in url:
        url = url.replace("mobile.twitter.com", "twitter.com")
    return url


def fetch_video_info(url):
    """UNCHANGED"""
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "format": "bestvideo+bestaudio/best",
        "extractor_args": {
            "twitter": {
                "include_ext_tw_video": True,
                "include_ext_alt_text": False
            }
        },
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = info.get("formats", [])
        videos = []

        for f in formats:
            if f.get("ext") == "mp4" and f.get("vcodec") != "none" and f.get("acodec") != "none":
                size = f.get("filesize") or f.get("filesize_approx") or 0
                height = f.get("height")

                videos.append({
                    "url": f.get("url"),
                    "quality": f"{height}p" if height else "auto",
                    "height": height,
                    "filesize": size,
                    "filesize_mb": round(size / 1024 / 1024, 2) if size else None,
                    "bitrate": f.get("tbr", 0),
                })

        if not videos:
            raise Exception("No downloadable video found")

        videos.sort(key=lambda x: x["bitrate"], reverse=True)

        return {"success": True, "title": info.get("title"), "videos": videos}


# -----------------------------
# DOWNLOAD ENDPOINT (ONLY stats changed)
# -----------------------------

@app.route("/download", methods=["POST"])
def download():

    increment_stat("requests")

    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"success": False, "message": "No URL provided"}), 400

    url = normalize_twitter_url(url)
    now = time.time()

    if url in CACHE and now - CACHE[url]["time"] < CACHE_TTL:

        increment_stat("cache_hits")

        return jsonify(CACHE[url]["data"])

    try:

        info = fetch_video_info(url)

        CACHE[url] = {
            "time": now,
            "data": info
        }

        return jsonify(info)

    except Exception as e:

        return jsonify({"success": False, "message": str(e)}), 500


# -----------------------------
# PROXY (ONLY stats changed)
# -----------------------------

@app.route("/proxy")
def proxy():

    video_url = request.args.get("url")

    if not video_url:
        return "No URL", 400

    ip = request.remote_addr

    increment_stat("downloads")
    increment_stat("videos_served")

    save_ip(ip)
    save_log(ip, video_url)

    headers = {}

    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]

    r = requests.get(video_url, headers=headers, stream=True)

    response_headers = {
        "Content-Type": r.headers.get("Content-Type", "video/mp4"),
        "Accept-Ranges": "bytes",
    }

    if "Content-Range" in r.headers:
        response_headers["Content-Range"] = r.headers["Content-Range"]

    return Response(
        r.iter_content(chunk_size=8192),
        status=r.status_code,
        headers=response_headers
    )


# -----------------------------
# STATS ENDPOINT (UPDATED)
# -----------------------------

@app.route("/stats")
def stats():

    return jsonify(get_stats())


# -----------------------------
# RESET ENDPOINT (NEW)
# -----------------------------

@app.route("/admin/reset", methods=["POST"])
def reset():

    password = request.json.get("password")

    if password != ADMIN_PASSWORD:
        return jsonify({"success": False}), 401

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("UPDATE stats SET requests=0, cache_hits=0, downloads=0, videos_served=0")
    c.execute("DELETE FROM ips")
    c.execute("DELETE FROM logs")

    conn.commit()
    conn.close()

    return jsonify({"success": True})


# -----------------------------
# RUN APP (UNCHANGED)
# -----------------------------

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(host="0.0.0.0", port=port)