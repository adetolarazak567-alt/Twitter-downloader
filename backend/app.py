from flask import Flask, request, jsonify, Response, render_template_string
from flask_cors import CORS
import yt_dlp
import requests
import time
import os

app = Flask(__name__)
CORS(app)

# -----------------------------
# CACHE & STATS
# -----------------------------
CACHE = {}
CACHE_TTL = 600

STATS = {
    "requests": 0,
    "cache_hits": 0,
    "downloads": 0,
    "unique_ips": set(),
    "videos_served": 0
}

DOWNLOAD_LOGS = []
ADMIN_PASSWORD = "razzyadminX567"

# -----------------------------
# HELPERS
# -----------------------------
def normalize_twitter_url(url: str) -> str:
    return (
        url.replace("x.com", "twitter.com")
           .replace("mobile.twitter.com", "twitter.com")
    )

# -----------------------------
# SAFE EXTRACTION (PUBLIC + NSFW)
# -----------------------------
def fetch_video_info(url):
    formats_to_try = [
        "bestvideo+bestaudio/best",
        "bv*+ba/b",
        "best"
    ]

    last_error = None

    for fmt in formats_to_try:
        try:
            ydl_opts = {
                "quiet": True,
                "skip_download": True,
                "noplaylist": True,
                "merge_output_format": "mp4",
                "format": fmt,
                "extractor_args": {
                    "twitter": {
                        "include_ext_tw_video": True
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

            videos = []
            for f in info.get("formats", []):
                if f.get("ext") == "mp4" and f.get("url"):
                    size = f.get("filesize") or f.get("filesize_approx") or 0
                    videos.append({
                        "url": f["url"],
                        "quality": f"{f.get('height','auto')}p",
                        "height": f.get("height"),
                        "filesize_mb": round(size / 1024 / 1024, 2) if size else None,
                        "bitrate": f.get("tbr", 0),
                    })

            if videos:
                videos.sort(key=lambda x: x["bitrate"], reverse=True)
                return {
                    "success": True,
                    "title": info.get("title"),
                    "videos": videos
                }

        except Exception as e:
            last_error = str(e)
            continue

    return {
        "success": False,
        "message": last_error or "Failed to extract video"
    }

# -----------------------------
# DOWNLOAD ENDPOINT
# -----------------------------
@app.route("/download", methods=["POST"])
def download():
    STATS["requests"] += 1

    data = request.get_json(silent=True) or {}
    url = data.get("url")

    if not url:
        return jsonify({"success": False, "message": "No URL provided"}), 400

    url = normalize_twitter_url(url)
    now = time.time()

    if url in CACHE and now - CACHE[url]["time"] < CACHE_TTL:
        STATS["cache_hits"] += 1
        cached = CACHE[url]["data"]
        cached["stats"] = {"cache_hits": STATS["cache_hits"]}
        return jsonify(cached)

    result = fetch_video_info(url)

    if result["success"]:
        CACHE[url] = {"time": now, "data": result}
        result["stats"] = {"cache_hits": STATS["cache_hits"]}
        return jsonify(result)

    return jsonify(result), 500

# -----------------------------
# PROXY STREAM
# -----------------------------
@app.route("/proxy")
def proxy():
    video_url = request.args.get("url")
    if not video_url:
        return "No URL", 400

    STATS["downloads"] += 1
    STATS["videos_served"] += 1
    STATS["unique_ips"].add(request.remote_addr)

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
# ADMIN DASHBOARD
# -----------------------------
@app.route("/admin")
def admin():
    if request.args.get("password") != ADMIN_PASSWORD:
        return "Unauthorized", 401

    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<title>Admin Dashboard</title>
<style>
body{background:#0f1720;color:#fff;font-family:Segoe UI;padding:20px}
.card{background:#192734;padding:20px;border-radius:12px;margin:10px;display:inline-block}
</style>
</head>
<body>
<h1>Admin Dashboard</h1>
<div class="card">Requests: {{requests}}</div>
<div class="card">Cache Hits: {{cache_hits}}</div>
<div class="card">Downloads: {{downloads}}</div>
<div class="card">Unique IPs: {{unique_ips|length}}</div>
<div class="card">Videos Served: {{videos_served}}</div>
</body>
</html>
""", **STATS)

# -----------------------------
# STATS API
# -----------------------------
@app.route("/stats")
def stats():
    return jsonify({
        "requests": STATS["requests"],
        "cache_hits": STATS["cache_hits"],
        "downloads": STATS["downloads"],
        "unique_ips": list(STATS["unique_ips"]),
        "videos_served": STATS["videos_served"],
        "download_logs": DOWNLOAD_LOGS
    })

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port) 