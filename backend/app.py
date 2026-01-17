from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
import os
import tempfile

app = Flask(__name__)
CORS(app)

COOKIES_PATH = "cookies.txt"

YDL_OPTS_BASE = {
    "quiet": True,
    "no_warnings": True,
    "cookiefile": COOKIES_PATH,
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "retries": 3,
    "fragment_retries": 3,
    "concurrent_fragment_downloads": 3,
    "http_chunk_size": 10485760,
    "noplaylist": True,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
                  " Chrome/119.0.0.0 Safari/537.36"
}

@app.route("/", methods=["GET"])
def home():
    return "Twitter/X Downloader Backend is LIVE"

@app.route("/download", methods=["POST"])
def download_video():
    data = request.get_json()
    url = data.get("url")

    if not url or ("twitter.com" not in url and "x.com" not in url):
        return jsonify({"success": False, "message": "Invalid Twitter/X URL"}), 400

    try:
        with tempfile.TemporaryDirectory() as tmp:
            ydl_opts = YDL_OPTS_BASE.copy()
            ydl_opts.update({
                "outtmpl": f"{tmp}/%(id)s.%(ext)s",
                "format": "bestvideo+bestaudio/best",
                "skip_download": True
            })

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info or "formats" not in info:
                return jsonify({"success": False, "message": "No video found"}), 404

            videos = []
            for f in info["formats"]:
                if f.get("vcodec") != "none" and f.get("url"):
                    videos.append({
                        "quality": f.get("height") or "auto",
                        "ext": f.get("ext") or "mp4",
                        "url": f.get("url"),
                        "filesize_mb": round(f.get("filesize", 0) / 1024 / 1024, 2) if f.get("filesize") else None
                    })

            # Remove duplicates by quality
            unique_videos = {str(v["quality"]): v for v in videos}.values()
            videos_sorted = sorted(
                unique_videos,
                key=lambda x: (x["quality"] if isinstance(x["quality"], int) else 0),
                reverse=True
            )

            # Keep admin stats, title, thumbnail, etc.
            return jsonify({
                "success": True,
                "title": info.get("title"),
                "thumbnail": info.get("thumbnail"),
                "uploader": info.get("uploader"),
                "upload_date": info.get("upload_date"),
                "description": info.get("description"),
                "extractor": info.get("extractor_key"),
                "stats": {
                    "requested_formats": len(info.get("formats", [])),
                    "cache_hits": info.get("extractor_key", "yt_dlp")
                },
                "videos": videos_sorted
            })

    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 7700)))