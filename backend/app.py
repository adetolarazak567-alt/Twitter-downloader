from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import requests
import time
import os

app = Flask(__name__)
CORS(app)

# -----------------------------
# BASIC OPTIMIZATION SETTINGS
# -----------------------------
CACHE = {}
CACHE_TTL = 600  # 10 minutes

STATS = {
    "requests": 0,
    "cache_hits": 0,
    "downloads": 0
}

# -----------------------------
# HELPERS
# -----------------------------
def normalize_twitter_url(url):
    return (
        url.replace("x.com", "twitter.com")
           .replace("mobile.twitter.com", "twitter.com")
    )

# -----------------------------
# VIDEO EXTRACTION (ROBUST)
# -----------------------------
def extract_video(url):
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "extractor_args": {
            "twitter": {
                "include_ext_tw_video": True
            }
        },
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9"
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    formats = info.get("formats", [])
    videos = []

    for f in formats:
        if (
            f.get("ext") == "mp4"
            and f.get("vcodec") != "none"
            and f.get("acodec") != "none"
        ):
            size = f.get("filesize") or f.get("filesize_approx") or 0
            videos.append({
                "quality": f"{f.get('height', 'auto')}p",
                "height": f.get("height"),
                "url": f.get("url"),
                "filesize_mb": round(size / 1024 / 1024, 2) if size else None,
                "bitrate": f.get("tbr", 0)
            })

    if not videos:
        raise Exception("No downloadable video found")

    videos.sort(key=lambda x: x["bitrate"], reverse=True)

    return {
        "success": True,
        "title": info.get("title"),
        "videos": videos
    }

# -----------------------------
# FETCH ENDPOINT
# -----------------------------
@app.route("/download", methods=["POST"])
def download():
    STATS["requests"] += 1

    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"success": False, "message": "No URL"}), 400

    url = normalize_twitter_url(url)
    now = time.time()

    # CACHE
    if url in CACHE and now - CACHE[url]["time"] < CACHE_TTL:
        STATS["cache_hits"] += 1
        return jsonify(CACHE[url]["data"])

    try:
        info = extract_video(url)
        CACHE[url] = {"time": now, "data": info}
        return jsonify(info)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# -----------------------------
# STREAM PROXY (FAST + SAFE)
# -----------------------------
@app.route("/proxy")
def proxy():
    video_url = request.args.get("url")
    if not video_url:
        return "No URL", 400

    STATS["downloads"] += 1

    headers = {}
    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]

    r = requests.get(video_url, headers=headers, stream=True, timeout=10)

    return Response(
        r.iter_content(chunk_size=8192),
        status=r.status_code,
        headers={
            "Content-Type": r.headers.get("Content-Type", "video/mp4"),
            "Accept-Ranges": "bytes"
        }
    )

# -----------------------------
# SIMPLE STATS (OPTIONAL)
# -----------------------------
@app.route("/stats")
def stats():
    return jsonify(STATS)

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)