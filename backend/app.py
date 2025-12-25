import yt_dlp
import requests
from flask import Flask, request, jsonify, Response, render_template_string
from flask_cors import CORS
import time, os

app = Flask(__name__)
CORS(app)

# -----------------------------
CACHE = {}
CACHE_TTL = 600

STATS = {"requests": 0, "cache_hits": 0, "downloads": 0, "unique_ips": set(), "videos_served": 0}
DOWNLOAD_LOGS = []
ADMIN_PASSWORD = "razzyadminX567"

# -----------------------------
def normalize_twitter_url(url: str) -> str:
    if "x.com" in url:
        url = url.replace("x.com", "twitter.com")
    if "mobile.twitter.com" in url:
        url = url.replace("mobile.twitter.com", "twitter.com")
    return url

def get_guest_token():
    """Get a guest token from Twitter for yt-dlp headers."""
    resp = requests.post(
        "https://api.twitter.com/1.1/guest/activate.json",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
    )
    resp.raise_for_status()
    return resp.json().get("guest_token")

def fetch_video_info(url):
    guest_token = get_guest_token()
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "format": "bestvideo+bestaudio/best",
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "x-guest-token": guest_token,
        },
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        videos = []
        for f in info.get("formats", []):
            if f.get("ext") == "mp4" and f.get("vcodec") != "none":
                size = f.get("filesize") or f.get("filesize_approx") or 0
                videos.append({
                    "url": f.get("url"),
                    "quality": f"{f.get('height')}p" if f.get("height") else "auto",
                    "filesize": size,
                    "filesize_mb": round(size/1024/1024,2) if size else None,
                    "bitrate": f.get("tbr", 0),
                })
        videos.sort(key=lambda x: x["bitrate"], reverse=True)
        return {"success": True, "title": info.get("title"), "videos": videos}

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
# proxy endpoint, admin dashboard, stats endpoint remain unchanged
# -----------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)