from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import requests
import time
import socket

app = Flask(__name__)
CORS(app)

# -----------------------------
# CACHE + STATS (STEP 2 READY)
# -----------------------------
CACHE = {}
CACHE_TTL = 300  # 5 minutes

STATS = {
    "requests": 0,
    "cache_hits": 0
}

# -----------------------------
# HELPERS
# -----------------------------
def normalize_twitter_url(url: str) -> str:
    if "x.com" in url:
        url = url.replace("x.com", "twitter.com")
    if "mobile.twitter.com" in url:
        url = url.replace("mobile.twitter.com", "twitter.com")
    return url


# -----------------------------
# MAIN DOWNLOAD ENDPOINT
# -----------------------------
@app.route("/download", methods=["POST"])
def download():
    STATS["requests"] += 1

    data = request.get_json(silent=True) or {}
    url = data.get("url")

    if not url:
        return jsonify({"success": False, "message": "No URL provided"}), 400

    url = normalize_twitter_url(url)

    if "/status/" not in url:
        return jsonify({"success": False, "message": "Invalid Twitter URL"}), 400

    now = time.time()

    # ✅ CACHE HIT
    if url in CACHE and now - CACHE[url]["time"] < CACHE_TTL:
        STATS["cache_hits"] += 1
        return jsonify(CACHE[url]["data"])

    try:
        # 🔥 RENDER-SAFE yt-dlp OPTIONS
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "cachedir": False,

            # ⚠️ VERY IMPORTANT (prevents hanging)
            "socket_timeout": 10,
            "retries": 1,
            "fragment_retries": 1,
            "extractor_retries": 1,

            "format": "bestvideo+bestaudio/best",

            # 🔥 ALLOW SENSITIVE / NSFW VIDEOS
            "extractor_args": {
                "twitter": {
                    "include_ext_tw_video": True,
                }
            },

            # 🔥 BROWSER HEADERS
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get("formats") or []

            videos = []
            for f in formats:
                if (
                    f.get("ext") == "mp4"
                    and f.get("vcodec") != "none"
                    and f.get("acodec") != "none"
                ):
                    size = f.get("filesize") or f.get("filesize_approx") or 0
                    height = f.get("height")

                    videos.append({
                        "url": f.get("url"),
                        "quality": f"{height}p" if height else "auto",
                        "height": height,
                        "filesize_mb": round(size / 1024 / 1024, 2) if size else None,
                        "bitrate": f.get("tbr", 0),
                    })

            if not videos:
                return jsonify({
                    "success": False,
                    "message": "No downloadable video found"
                }), 404

            videos.sort(key=lambda x: x["bitrate"], reverse=True)

            response = {
                "success": True,
                "videos": videos,
                "available_qualities": len(videos),
                "cached_requests_saved": STATS["cache_hits"]
            }

            CACHE[url] = {
                "time": now,
                "data": response
            }

            return jsonify(response)

    except Exception as e:
        return jsonify({
            "success": False,
            "message": "Failed to fetch video (timeout or blocked)"
        }), 500


# -----------------------------
# FAST STREAMING PROXY (STEP 1)
# -----------------------------
@app.route("/proxy")
def proxy():
    video_url = request.args.get("url")
    if not video_url:
        return "No URL", 400

    headers = {}
    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]

    with requests.Session() as s:
        r = s.get(video_url, headers=headers, stream=True, timeout=10)

        resp_headers = {
            "Content-Type": r.headers.get("Content-Type", "video/mp4"),
            "Accept-Ranges": "bytes"
        }

        if "Content-Range" in r.headers:
            resp_headers["Content-Range"] = r.headers["Content-Range"]

        return Response(
            r.iter_content(chunk_size=16384),
            status=r.status_code,
            headers=resp_headers
        )


# -----------------------------
# PUBLIC SAFE STATS
# -----------------------------
@app.route("/stats")
def stats():
    return jsonify({
        "available_qualities": None,
        "cached_requests_saved": STATS["cache_hits"]
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)