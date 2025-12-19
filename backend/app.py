from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re

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

        # Look for the video URL in the meta tags
        # Twitter often has video URL in "og:video" meta tag
        match = re.search(r'<meta property="og:video" content="([^"]+)"', html)
        if match:
            video_url = match.group(1)
            return jsonify({"success": True, "url": video_url})
        else:
            return jsonify({"success": False, "message": "Video not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
