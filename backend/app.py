from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re
import json

app = Flask(__name__)
CORS(app)

def extract_video_urls(tweet_html):
    """
    Extract all available Twitter video qualities from the tweet HTML.
    Returns a list of dicts: [{"url": ..., "bitrate": ...}, ...]
    """
    video_urls = []

    # Look for video variants in JavaScript objects
    try:
        # Sometimes Twitter stores JSON in window.__INITIAL_STATE__ or <script type="application/ld+json">
        # We'll try to extract video info from <script type="application/ld+json">
        ld_json_match = re.findall(r'<script type="application/ld\+json">(.*?)</script>', tweet_html, re.DOTALL)
        for js in ld_json_match:
            data_json = json.loads(js)
            # Only process if it's a videoObject
            if data_json.get("@type") == "VideoObject":
                url = data_json.get("contentUrl")
                if url:
                    video_urls.append({"url": url, "bitrate": 0})

        # Fallback: search for "variants" JSON in the HTML
        variants_match = re.findall(r'"variants":(\[.*?])', tweet_html)
        for vm in variants_match:
            variants = json.loads(vm)
            for v in variants:
                if v.get("content_type") == "video/mp4":
                    video_urls.append({
                        "url": v["url"].split("?")[0],  # clean URL
                        "bitrate": v.get("bitrate", 0)
                    })

    except Exception as e:
        print("Error extracting videos:", e)

    return video_urls

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

        video_urls = extract_video_urls(html)

        # Remove duplicates
        seen = set()
        unique_videos = []
        for v in video_urls:
            if v["url"] not in seen:
                seen.add(v["url"])
                unique_videos.append(v)

        # Sort by bitrate descending
        unique_videos.sort(key=lambda x: x.get("bitrate", 0), reverse=True)

        if unique_videos:
            return jsonify({"success": True, "videos": unique_videos})

        return jsonify({"success": False, "message": "Video not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)