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
CACHE_TTL = 86400


# ============================
# DATABASE INIT
# ============================

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


# ============================
# STATS
# ============================

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


def get_stats():

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        SELECT requests, cache_hits, downloads,
               videos_served, mb_served
        FROM stats WHERE id=1
    """)

    row = c.fetchone()

    conn.close()

    return {
        "requests": row[0],
        "cache_hits": row[1],
        "downloads": row[2],
        "videos_served": row[3],
        "mb_served": round(row[4], 2)
    }


# ============================
# CACHE
# ============================

def save_cache(url, data):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        INSERT OR REPLACE INTO video_cache
        VALUES (?, ?, ?)
    """, (url, str(data), int(time.time())))

    conn.commit()
    conn.close()


def load_cache(url):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        SELECT data, timestamp
        FROM video_cache
        WHERE url=?
    """, (url,))

    row = c.fetchone()

    conn.close()

    if not row:
        return None

    data, timestamp = row

    if time.time() - timestamp > CACHE_TTL:
        return None

    return eval(data)


# ============================
# URL NORMALIZER
# ============================

def normalize_url(url):

    url = url.strip()

    url = url.replace("x.com", "twitter.com")
    url = url.replace("mobile.twitter.com", "twitter.com")

    if "?" in url:
        url = url.split("?")[0]

    return url


# ============================
# DOWNLOAD ENDPOINT
# ============================

@app.route("/download", methods=["POST"])
def download():

    increment_stat("requests")

    try:

        data = request.get_json()

        if not data:
            return jsonify({
                "success": False,
                "message": "No JSON received"
            }), 400

        url = data.get("url")

        if not url:
            return jsonify({
                "success": False,
                "message": "No URL provided"
            }), 400

        url = normalize_url(url)

        # CHECK CACHE
        cached = load_cache(url)

        if cached:
            increment_stat("cache_hits")
            return jsonify(cached)


        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "format": "best",
            "nocheckcertificate": True,
            "retries": 10,
            "fragment_retries": 10,
            "http_headers": {
                "User-Agent": "Mozilla/5.0"
            }
        }


        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            info = ydl.extract_info(url, download=False)

        if not info:

            return jsonify({
                "success": False,
                "message": "Extraction failed"
            }), 500


        video_url = None
        height = 0

        for f in info.get("formats", []):

            if f.get("ext") == "mp4":

                if f.get("height", 0) > height:

                    height = f.get("height", 0)
                    video_url = f.get("url")


        if not video_url:

            return jsonify({
                "success": False,
                "message": "No video found"
            }), 404


        videos = [{
            "url": video_url,
            "quality": f"{height}p",
            "height": height,
            "filesize_mb": None
        }]


        result = {
            "success": True,
            "title": info.get("title", "Twitter Video"),
            "videos": videos
        }


        save_cache(url, result)

        return jsonify(result)


    except Exception as e:

        import traceback
        print(traceback.format_exc())

        return jsonify({
            "success": False,
            "message": "Server extraction error"
        }), 500


# ============================
# PROXY STREAM
# ============================

@app.route("/proxy")
def proxy():

    try:

        url = request.args.get("url")
        download = request.args.get("download")

        if not url:
            return "Missing URL", 400


        r = requests.get(url, stream=True, timeout=30)

        headers = {
            "Content-Type": "video/mp4",
            "Accept-Ranges": "bytes"
        }


        filename = "ToolifyX_Video.mp4"

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


# ============================
# HEALTHCHECK
# ============================

@app.route("/")
def home():

    return jsonify({
        "status": "ok",
        "service": "ToolifyX Downloader API",
        "version": "1.0"
    })


@app.route("/stats")
def stats():

    return jsonify(get_stats())


# ============================
# RUN
# ============================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )