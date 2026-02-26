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


def save_ip(ip):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute(
        "INSERT OR IGNORE INTO ips(ip) VALUES(?)",
        (ip,)
    )

    conn.commit()
    conn.close()


def save_log(ip, url):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        INSERT INTO logs(ip,url,timestamp)
        VALUES(?,?,?)
    """, (ip, url, int(time.time())))

    conn.commit()
    conn.close()


def get_stats():

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        SELECT requests, cache_hits, downloads,
               videos_served, mb_served
        FROM stats WHERE id=1
    """)

    stats = c.fetchone()

    c.execute("SELECT COUNT(*) FROM ips")
    unique_ips = c.fetchone()[0]

    c.execute("""
        SELECT date, downloads, mb_served
        FROM daily
        ORDER BY date DESC
        LIMIT 30
    """)

    daily = c.fetchall()

    c.execute("""
        SELECT ip,url,timestamp
        FROM logs
        ORDER BY id DESC
        LIMIT 100
    """)

    logs = c.fetchall()

    conn.close()

    return {

        "requests": stats[0],
        "cache_hits": stats[1],
        "downloads": stats[2],
        "videos_served": stats[3],
        "mb_served": round(stats[4], 2),
        "unique_ips": unique_ips,

        "daily": [
            {
                "date": d[0],
                "downloads": d[1],
                "mb_served": round(d[2], 2)
            }
            for d in daily
        ],

        "logs": [
            {
                "ip": l[0],
                "url": l[1],
                "timestamp": l[2]
            }
            for l in logs
        ]
    }


# -----------------------------
# CACHE
# -----------------------------

CACHE = {}
CACHE_TTL = 600


# -----------------------------
# HELPERS
# -----------------------------

def normalize_twitter_url(url):

    if "x.com" in url:
        url = url.replace("x.com", "twitter.com")

    if "mobile.twitter.com" in url:
        url = url.replace("mobile.twitter.com", "twitter.com")

    return url



# -----------------------------
# DOWNLOAD INFO (FILTERED RESOLUTIONS)
# -----------------------------
@app.route("/download", methods=["POST"])
def download():

    increment_stat("requests")

    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"success": False}), 400

    url = normalize_twitter_url(url)
    now = time.time()

    if url in CACHE and now - CACHE[url]["time"] < CACHE_TTL:
        increment_stat("cache_hits")
        return jsonify(CACHE[url]["data"])

    try:

        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "format": "best"
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            videos = []

            # Map heights to closest allowed resolution
            allowed_heights = [320, 720, 1080, 2160]  # 2160 = 2k
            added_heights = set()

            for f in info["formats"]:
                if f.get("ext") != "mp4":
                    continue
                h = f.get("height")
                if not h:
                    continue

                # Find closest allowed height
                closest = min(allowed_heights, key=lambda x: abs(x - h))

                # Only add one per allowed height
                if closest in added_heights:
                    continue

                size = f.get("filesize") or f.get("filesize_approx") or 0

                videos.append({
                    "url": f["url"],
                    "quality": f"{closest}p",
                    "height": closest,
                    "filesize": size,
                    "filesize_mb": round(size / 1024 / 1024, 2) if size else None
                })

                added_heights.add(closest)

        if not videos:
            raise Exception("No downloadable video found")

        # Sort by quality descending
        videos.sort(key=lambda x: x["height"], reverse=True)

        result = {"success": True, "title": info.get("title"), "videos": videos}

        CACHE[url] = {"time": now, "data": result}

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
# -----------------------------
# PROXY (PRO VERSION)
# -----------------------------
@app.route("/proxy")
def proxy():

    url = request.args.get("url")
    download = request.args.get("download")

    if not url:
        return "Missing URL", 400

    try:

        r = requests.get(url, stream=True, timeout=30)

        file_size = r.headers.get("Content-Length")

        headers = {
            "Content-Type": "video/mp4",
            "Accept-Ranges": "bytes"
        }

        # Generate random filename
        random_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        filename = f"ToolifyX Downloader_{random_id}.mp4"

        if download == "1":

            headers["Content-Disposition"] = \
                f"attachment; filename={filename}"

        else:

            headers["Content-Disposition"] = \
                f"inline; filename={filename}"

        if file_size:
            headers["Content-Length"] = file_size

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

    return jsonify(get_stats())


# -----------------------------
# ADMIN RESET
# -----------------------------

@app.route("/admin/reset", methods=["POST"])
def reset():

    password = request.json.get("password")

    if password != ADMIN_PASSWORD:
        return jsonify({"success": False}), 401

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        UPDATE stats
        SET requests=0,
            cache_hits=0,
            downloads=0,
            videos_served=0,
            mb_served=0
    """)

    c.execute("DELETE FROM ips")
    c.execute("DELETE FROM logs")
    c.execute("DELETE FROM daily")

    conn.commit()
    conn.close()

    return jsonify({"success": True})


# -----------------------------
# RUN
# -----------------------------

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(host="0.0.0.0", port=port)