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

def normalize_twitter_url(url: str) -> str:
    if "x.com" in url:
        url = url.replace("x.com", "twitter.com")
    if "mobile.twitter.com" in url:
        url = url.replace("mobile.twitter.com", "twitter.com")
    return url


@app.route("/download", methods=["POST"])
def download():
    STATS["requests"] += 1

    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"success": False, "message": "No URL provided"}), 400

    url = normalize_twitter_url(url)
    now = time.time()

    # ✅ CACHE HIT
    if url in CACHE and now - CACHE[url]["time"] < CACHE_TTL:
        STATS["cache_hits"] += 1
        return jsonify(CACHE[url]["data"])

    try:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "format": "bestvideo+bestaudio/best",
            "noplaylist": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get("formats", [])

            videos = []
            for f in formats:
                if (
                    f.get("vcodec") != "none"
                    and f.get("acodec") != "none"
                    and f.get("ext") == "mp4"
                ):
                    size = f.get("filesize") or f.get("filesize_approx") or 0
                    videos.append({
                        "url": f.get("url"),
                        "height": f.get("height"),
                        "quality": f"{f.get('height')}p" if f.get("height") else "unknown",
                        "filesize": size,
                        "filesize_mb": round(size / 1024 / 1024, 2) if size else None,
                        "bitrate": f.get("tbr", 0)
                    })

            if not videos:
                return jsonify({"success": False, "message": "Video not found"}), 404

            videos.sort(key=lambda x: x["bitrate"], reverse=True)

            response = {
                "success": True,
                "videos": videos,
                "stats": STATS
            }

            CACHE[url] = {
                "time": now,
                "data": response
            }

            return jsonify(response)

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# -----------------------------
# STREAMING PROXY (WITH RANGE)
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

    return Response(
        r.iter_content(chunk_size=8192),
        status=r.status_code,
        content_type=r.headers.get("Content-Type", "video/mp4"),
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": r.headers.get("Content-Range", ""),
        }
    )


@app.route("/stats")
def stats():
    return jsonify(STATS)


if __name__ == "__main__":
    app.run(debug=True)