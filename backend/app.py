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
CACHE_TTL = 86400  # 24 hours


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

    # Emails
    c.execute("""
    CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        timestamp INTEGER
    )
    """)

    # Video cache
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
# STAT FUNCTIONS
# -----------------------------
def increment_stat(field, amount=1):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f"UPDATE stats SET {field} = {field} + ? WHERE id = 1", (amount,))
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


def save_ip(ip):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO ips(ip) VALUES(?)", (ip,))
    conn.commit()
    conn.close()


def save_log(ip, url):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO logs(ip,url,timestamp) VALUES(?,?,?)", (ip, url, int(time.time())))
    conn.commit()
    conn.close()


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
    c.execute("SELECT data,timestamp FROM video_cache WHERE url=?", (url,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    data, timestamp = row
    if time.time() - timestamp > CACHE_TTL:
        return None
    return eval(data)


def get_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT requests, cache_hits, downloads, videos_served, mb_served FROM stats WHERE id=1")
    stats = c.fetchone()

    c.execute("SELECT COUNT(*) FROM ips")
    unique_ips = c.fetchone()[0]

    c.execute("SELECT date, downloads, mb_served FROM daily ORDER BY date DESC LIMIT 30")
    daily = c.fetchall()

    c.execute("SELECT ip,url,timestamp FROM logs ORDER BY id DESC LIMIT 100")
    logs = c.fetchall()

    conn.close()

    return {
        "requests": stats[0],
        "cache_hits": stats[1],
        "downloads": stats[2],
        "videos_served": stats[3],
        "mb_served": round(stats[4], 2),
        "unique_ips": unique_ips,
        "daily": [{"date": d[0], "downloads": d[1], "mb_served": round(d[2],2)} for d in daily],
        "logs": [{"ip": l[0], "url": l[1], "timestamp": l[2]} for l in logs]
    }


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
        c.execute("INSERT OR IGNORE INTO emails(email,timestamp) VALUES(?,?)", (email, int(time.time())))
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
    return jsonify({"success": True, "emails":[{"email":e[0],"timestamp":e[1]} for e in emails]})


# -----------------------------
# HELPERS
# -----------------------------
def normalize_twitter_url(url):
    url = url.strip()
    if "x.com" in url:
        url = url.replace("x.com", "twitter.com")
    if "mobile.twitter.com" in url:
        url = url.replace("mobile.twitter.com", "twitter.com")
    if "twitter.com" in url and "?" in url:
        url = url.split("?")[0]
    return url


# -----------------------------
# DOWNLOAD (Twitter/X)
# -----------------------------
@app.route("/download", methods=["POST"])
def download():

    increment_stat("requests")

    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({
            "success": False,
            "message": "No URL provided"
        }), 400

    url = normalize_twitter_url(url)

    # Check cache first
    cached = load_cache(url)
    if cached:
        increment_stat("cache_hits")
        return jsonify(cached)

    def extract_with_ytdlp(target_url):

        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "format": "best",
            "nocheckcertificate": True,
            "retries": 10,
            "fragment_retries": 10,
            "http_headers": {
                "User-Agent":
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://twitter.com/"
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(target_url, download=False)

    def extract_fallback(target_url):

        # Alternative extractor method
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "nocheckcertificate": True,
            "http_headers": {
                "User-Agent":
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(target_url, download=False)

    try:

        try:
            info = extract_with_ytdlp(url)
        except:
            info = extract_fallback(url)

        if not info:
            return jsonify({
                "success": False,
                "message": "Extraction failed"
            }), 500

        video_url = None
        height = 0

        for f in info.get("formats", []):

            if f.get("ext") == "mp4":

                h = f.get("height", 0)

                if h > height and f.get("url"):
                    height = h
                    video_url = f.get("url")

        if not video_url:

            return jsonify({
                "success": False,
                "message": "No video found"
            }), 404

        # VERY IMPORTANT: Use proxy URL for preview + download
        proxy_preview = f"/proxy?url={video_url}"
        proxy_download = f"/proxy?url={video_url}&download=1"

        result = {

            "success": True,

            "title": info.get("title", "Twitter Video"),

            "videos": [

                {
                    "url": proxy_download,
                    "preview": proxy_preview,
                    "quality": f"{height}p",
                    "height": height
                }

            ]

        }

        save_cache(url, result)

        return jsonify(result)

    except Exception as e:

        import traceback
        print(traceback.format_exc())

        return jsonify({
            "success": False,
            "message": "Extraction failed"
        }), 500


# -----------------------------
# PROXY FOR STREAMING + DOWNLOAD + RENAME
# -----------------------------
@app.route("/proxy")
def proxy():

    video_url = request.args.get("url")
    download = request.args.get("download")

    if not video_url:
        return "No URL", 400

    STATS["downloads"] += 1
    STATS["videos_served"] += 1
    STATS["unique_ips"].add(request.remote_addr)

    # log download
    DOWNLOAD_LOGS.append({
        "ip": request.remote_addr,
        "url": video_url,
        "timestamp": int(time.time())
    })

    if len(DOWNLOAD_LOGS) > 100:
        DOWNLOAD_LOGS.pop(0)

    try:

        headers = {}

        # IMPORTANT: allow streaming preview
        if "Range" in request.headers:
            headers["Range"] = request.headers["Range"]

        r = requests.get(video_url, headers=headers, stream=True, timeout=60)

        # Generate ToolifyX filename
        random_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        filename = f"ToolifyX Downloader_{random_id}.mp4"

        response_headers = {
            "Content-Type": r.headers.get("Content-Type", "video/mp4"),
            "Accept-Ranges": "bytes"
        }

        # CRITICAL: support video seeking
        if "Content-Range" in r.headers:
            response_headers["Content-Range"] = r.headers["Content-Range"]

        if "Content-Length" in r.headers:
            response_headers["Content-Length"] = r.headers["Content-Length"]

        # THIS enables rename when downloading
        if download == "1":
            response_headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        else:
            # THIS enables preview but still keeps ToolifyX name
            response_headers["Content-Disposition"] = f'inline; filename="{filename}"'

        return Response(
            r.iter_content(chunk_size=8192),
            status=r.status_code,
            headers=response_headers
        )

    except Exception as e:
        print(e)
        return "Proxy error", 500



# -----------------------------
# HOME / STATS
# -----------------------------
@app.route("/")
def home():
    return jsonify({"status":"ok","service":"ToolifyX Downloader API","version":"1.0"})


@app.route("/stats")
def stats():
    return jsonify(get_stats())


# -----------------------------
# ADMIN RESET
# -----------------------------
@app.route("/admin/reset", methods=["POST"])
def reset():
    password = request.json.get("password")
    if password != ADMIN_PASSWORD:
        return jsonify({"success":False}), 401
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE stats SET requests=0, cache_hits=0, downloads=0, videos_served=0, mb_served=0")
    c.execute("DELETE FROM ips")
    c.execute("DELETE FROM logs")
    c.execute("DELETE FROM daily")
    conn.commit()
    conn.close()
    return jsonify({"success":True})


# -----------------------------
# RUN
# -----------------------------
if __name__=="__main__":
    port = int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0", port=port)