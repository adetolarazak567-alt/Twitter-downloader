from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import requests
import time

app = Flask(__name__)
CORS(app)

# -----------------------------
# SIMPLE IN-MEMORY CACHE + STATS
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

    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"success": False, "message": "No URL provided"}), 400

    url = normalize_twitter_url(url)

    if "/status/" not in url:
        return jsonify({"success": False, "message": "Invalid Twitter video URL"}), 400

    now = time.time()

    # ✅ CACHE HIT
    if url in CACHE and now - CACHE[url]["time"] < CACHE_TTL:
        STATS["cache_hits"] += 1
        return jsonify(CACHE[url]["data"])

    try:
        # 🔥 CRITICAL OPTIONS FOR SENSITIVE VIDEOS
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "merge_output_format": "mp4",
            "format": "bestvideo+bestaudio/best",

            # 🔥 REQUIRED FOR SENSITIVE / NSFW VIDEOS
            "extractor_args": {
                "twitter": {
                    "include_ext_tw_video": True,
                    "include_ext_alt_text": False,
                }
            },

            # 🔥 PRETEND TO BE A REAL BROWSER
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
                        "filesize": size,
                        "filesize_mb": round(size / 1024 / 1024, 2) if size else None,
                        "bitrate": f.get("tbr", 0),
                    })

            if not videos:
                return jsonify({
                    "success": False,
                    "message": "No downloadable video found"
                }), 404

            # Highest quality first
            videos.sort(key=lambda x: x["bitrate"], reverse=True)

            response = {
                "success": True,
                "title": info.get("title"),
                "videos": videos,
                "stats": STATS
            }

            # SAVE TO CACHE
            CACHE[url] = {
                "time": now,
                "data": response
            }

            return jsonify(response)

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# -----------------------------
# STREAMING PROXY (RANGE SAFE)
# -----------------------------
@app.route("/proxy")
def proxy():
    video_url = request.args.get("url")
    if not video_url:
        return "No URL", 400

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
# STATS ENDPOINT
# -----------------------------
@app.route("/stats")
def stats():
    return jsonify(STATS)


if __name__ == "__main__":
    app.run()