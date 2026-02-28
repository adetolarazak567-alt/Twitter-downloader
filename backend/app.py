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
# DOWNLOAD ENDPOINT
# -----------------------------
@app.route("/download", methods=["POST"])
def download():
    STATS["requests"] += 1
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"success": False, "message": "No URL provided"}), 400

    url = normalize_twitter_url(url)
    now = time.time()

    # CACHE HIT
    if url in CACHE and now - CACHE[url]["time"] < CACHE_TTL:
        STATS["cache_hits"] += 1
        cached_data = CACHE[url]["data"]
        cached_data["stats"] = {"cache_hits": STATS["cache_hits"]}
        return jsonify(cached_data)

    try:
        info = fetch_video_info(url)
        info["stats"] = {"cache_hits": STATS["cache_hits"]}
        CACHE[url] = {"time": now, "data": info}
        return jsonify(info)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# -----------------------------
# PROXY FOR STREAMING + DOWNLOAD + RENAME
# -----------------------------
@app.route("/proxy")
def proxy():
    video_url = request.args.get("url")
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

    headers = {}
    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]

    r = requests.get(video_url, headers=headers, stream=True)

    # ✅ ToolifyX rename added here
    import random, string
    random_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    filename = f"ToolifyX Downloader_{random_id}.mp4"

    response_headers = {
        "Content-Type": r.headers.get("Content-Type", "video/mp4"),
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'attachment; filename="{filename}"'
    }

    if "Content-Range" in r.headers:
        response_headers["Content-Range"] = r.headers["Content-Range"]

    return Response(
        r.iter_content(chunk_size=8192),
        status=r.status_code,
        headers=response_headers
    )



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