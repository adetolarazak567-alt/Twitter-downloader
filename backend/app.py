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
}

@app.route("/", methods=["GET"])
def home():
    return "Twitter Downloader Backend is LIVE"

@app.route("/api/fetch", methods=["POST"])
def fetch_video():
    data = request.get_json()
    url = data.get("url")

    if not url or "twitter.com" not in url and "x.com" not in url:
        return jsonify({"error": "Invalid Twitter/X URL"}), 400

    try:
        with tempfile.TemporaryDirectory() as tmp:
            ydl_opts = YDL_OPTS_BASE.copy()
            ydl_opts.update({
                "outtmpl": f"{tmp}/%(id)s.%(ext)s",
                "format": "bestvideo+bestaudio/best",
            })

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info or "formats" not in info:
                return jsonify({"error": "No video found"}), 404

            videos = []
            for f in info["formats"]:
                if f.get("vcodec") != "none" and f.get("url"):
                    videos.append({
                        "quality": f.get("height"),
                        "ext": f.get("ext"),
                        "url": f.get("url")
                    })

            videos = sorted(
                {v["quality"]: v for v in videos}.values(),
                key=lambda x: (x["quality"] or 0),
                reverse=True
            )

            return jsonify({
                "title": info.get("title"),
                "thumbnail": info.get("thumbnail"),
                "videos": videos
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 7700)))