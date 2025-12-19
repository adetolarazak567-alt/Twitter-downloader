from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re
import json

app = Flask(__name__)
CORS(app)

@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"success": False, "message": "No URL provided"}), 400

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
            (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers)
        html = r.text

        # Twitter video info is often in a JavaScript object called window.__INITIAL_STATE__
        match = re.search(r'window\.__INITIAL_STATE__\s?=\s?({.*});', html)
        video_urls = []

        if match:
            data_json = json.loads(match.group(1))
            # Navigate JSON to find video variants (this may vary based on tweet structure)
            try:
                variants = data_json["entities"]["tweets"]
                for tweet in variants.values():
                    media = tweet.get("media", [])
                    for m in media:
                        if m.get("type") == "video":
                            for variant in m["video_info"]["variants"]:
                                if variant.get("content_type") == "video/mp4":
                                    video_urls.append({
                                        "url": variant["url"],
                                        "bitrate": variant.get("bitrate", 0)
                                    })
            except Exception:
                pass

        # If we found video URLs, sort by bitrate descending
        if video_urls:
            video_urls = sorted(video_urls, key=lambda x: x["bitrate"], reverse=True)
            return jsonify({"success": True, "videos": video_urls})

        # Fallback: og:video meta tag
        match2 = re.search(r'<meta property="og:video" content="([^"]+)"', html)
        if match2:
            return jsonify({"success": True, "videos": [{"url": match2.group(1), "bitrate": 0}]})

        return jsonify({"success": False, "message": "Video not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)