from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

def normalize_twitter_url(url: str) -> str:
    if "x.com" in url:
        url = url.replace("x.com", "twitter.com")
    if "mobile.twitter.com" in url:
        url = url.replace("mobile.twitter.com", "twitter.com")
    return url

@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"success": False, "message": "No URL provided"}), 400

    # 🔥 FIX: normalize Twitter/X URLs
    url = normalize_twitter_url(url)

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
                # MP4 video + audio only
                if (
                    f.get("vcodec") != "none"
                    and f.get("acodec") != "none"
                    and f.get("ext") == "mp4"
                ):
                    videos.append({
                        "url": f.get("url"),
                        "quality": f.get("format_note") or f.get("height"),
                        "bitrate": f.get("tbr", 0)
                    })

            if videos:
                videos.sort(key=lambda x: x["bitrate"], reverse=True)
                return jsonify({
                    "success": True,
                    "videos": videos
                })

        return jsonify({"success": False, "message": "Video not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)