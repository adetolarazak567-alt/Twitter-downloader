from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"success": False, "message": "No URL provided"}), 400

    try:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "format": "bestvideo+bestaudio/best",
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get("formats", [])

            # Get all mp4 video formats
            videos = []
            for f in formats:
                if f.get("vcodec") != "none" and f.get("acodec") != "none":
                    videos.append({
                        "url": f["url"],
                        "bitrate": f.get("tbr", 0)
                    })

            if videos:
                # Sort by bitrate descending
                videos.sort(key=lambda x: x["bitrate"], reverse=True)
                return jsonify({"success": True, "videos": videos})

        return jsonify({"success": False, "message": "Video not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)