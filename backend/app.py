from flask import Flask, request, jsonify, Response, render_template_string
from flask_cors import CORS
import yt_dlp
import requests
import time
import os

app = Flask(__name__)
CORS(app)

# -----------------------------
# CACHE & STATS
# -----------------------------
CACHE = {}  # url -> {"time": ts, "data": ...}
CACHE_TTL = 600  # 10 min

STATS = {
    "requests": 0,
    "cache_hits": 0,
    "downloads": 0,
    "unique_ips": set(),
    "videos_served": 0
}

DOWNLOAD_LOGS = []  # store last 100 downloads

ADMIN_PASSWORD = "razzyadminX567"

# -----------------------------
# HELPERS
# -----------------------------
def normalize_twitter_url(url: str) -> str:
    if "x.com" in url:
        url = url.replace("x.com", "twitter.com")
    if "mobile.twitter.com" in url:
        url = url.replace("mobile.twitter.com", "twitter.com")
    return url

def fetch_video_info(url):
    """Fetch both public & sensitive videos."""
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "format": "bestvideo+bestaudio/best",
        "extractor_args": {
            "twitter": {
                "include_ext_tw_video": True,
                "include_ext_alt_text": False
            }
        },
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
            if f.get("ext") == "mp4" and f.get("vcodec") != "none" and f.get("acodec") != "none":
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
            raise Exception("No downloadable video found")
        videos.sort(key=lambda x: x["bitrate"], reverse=True)
        return {"success": True, "title": info.get("title"), "videos": videos}

# -----------------------------
# DOWNLOAD ENDPOINT
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
        return jsonify(CACHE[url]["data"])

    try:
        info = fetch_video_info(url)
        CACHE[url] = {"time": now, "data": info}
        return jsonify(info)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# -----------------------------
# PROXY FOR STREAMING
# -----------------------------
@app.route("/proxy")
def proxy():
    video_url = request.args.get("url")
    if not video_url:
        return "No URL", 400

    STATS["downloads"] += 1
    STATS["videos_served"] += 1
    STATS["unique_ips"].add(request.remote_addr)

    # log download
    DOWNLOAD_LOGS.append({
        "ip": request.remote_addr,
        "url": video_url,
        "timestamp": int(time.time())
    })
    if len(DOWNLOAD_LOGS) > 100:
        DOWNLOAD_LOGS.pop(0)

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

    return Response(r.iter_content(chunk_size=8192), status=r.status_code, headers=response_headers)

# -----------------------------
# ADMIN DASHBOARD
# -----------------------------
@app.route("/admin")
def admin():
    password = request.args.get("password")
    if password != ADMIN_PASSWORD:
        return "Unauthorized", 401
    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin Dashboard</title>
<style>
body { font-family: 'Segoe UI', sans-serif; background:#0f1720; color:#fff; margin:0; padding:20px; }
h1 { color:#1da1f2; text-align:center; margin-bottom:30px; }
.stats { display:flex; flex-wrap:wrap; gap:20px; justify-content:center; margin-bottom:40px; }
.card { background:#192734; padding:20px; border-radius:15px; min-width:150px; text-align:center; box-shadow:0 4px 15px rgba(0,0,0,0.5); transition: transform 0.2s, box-shadow 0.2s; }
.card:hover { transform: translateY(-5px); box-shadow:0 8px 25px rgba(29,161,242,0.45); }
.card h2 { margin:0 0 10px 0; font-size:18px; color:#fff; }
.card p { margin:0; font-size:24px; font-weight:600; }
button { display:block; margin:0 auto 40px auto; padding:12px 25px; border:none; border-radius:9999px; background:#1da1f2; color:#fff; cursor:pointer; font-weight:600; font-size:16px; transition:0.2s; }
button:hover { background:#0d8ae5; transform:translateY(-2px); box-shadow:0 5px 15px rgba(29,161,242,0.35); }
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>

<h1>Admin Dashboard</h1>

<div class="stats">
<div class="card"><h2>Total Requests</h2><p>{{requests}}</p></div>
<div class="card"><h2>Cache Hits</h2><p>{{cache_hits}}</p></div>
<div class="card"><h2>Total Downloads</h2><p>{{downloads}}</p></div>
<div class="card"><h2>Unique IPs</h2><p>{{unique_ips|length}}</p></div>
<div class="card"><h2>Videos Served</h2><p>{{videos_served}}</p></div>
</div>

<canvas id="requestsChart" height="200"></canvas>

<h2 style="text-align:center;">Download Logs</h2>
<table id="logsTable">
<thead>
<tr><th>#</th><th>IP Address</th><th>Video URL</th><th>Timestamp</th></tr>
</thead>
<tbody></tbody>
</table>

<button onclick="fetchStats()">Refresh Stats</button>

<script>
const BACKEND = location.origin; // auto use current domain
let logs = [];

const ctx = document.getElementById('requestsChart').getContext('2d');
const requestsChart = new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [{ label: 'Requests Over Time', data: [], borderColor: '#1da1f2', backgroundColor: 'rgba(29,161,242,0.2)', tension:0.3, fill:true }] },
    options: { responsive:true, plugins:{legend:{display:true}}, scales:{y:{beginAtZero:true}} }
});

async function fetchStats(){
    try{
        const res = await fetch(`${BACKEND}/stats`);
        const data = await res.json();

        document.querySelector("#totalRequests").textContent = data.requests || 0;
        document.querySelector("#cacheHits").textContent = data.cache_hits || 0;
        document.querySelector("#totalDownloads").textContent = data.downloads || 0;
        document.querySelector("#uniqueIps").textContent = data.unique_ips ? data.unique_ips.length : 0;
        document.querySelector("#videosServed").textContent = data.videos_served || 0;

        const now = new Date().toLocaleTimeString();
        requestsChart.data.labels.push(now);
        requestsChart.data.datasets[0].data.push(data.requests || 0);
        if(requestsChart.data.labels.length>10){
            requestsChart.data.labels.shift();
            requestsChart.data.datasets[0].data.shift();
        }
        requestsChart.update();

        // logs table
        const tbody = document.querySelector('#logsTable tbody');
        tbody.innerHTML = '';
        if(data.download_logs && data.download_logs.length){
            data.download_logs.slice(-10).forEach((log,i)=>{
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${i+1}</td>
                                <td>${log.ip}</td>
                                <td><a href="${log.url}" target="_blank">${log.url}</a></td>
                                <td>${new Date(log.timestamp*1000).toLocaleString()}</td>`;
                tbody.appendChild(tr);
            });
        }

    } catch(e){
        alert("Failed to fetch stats/logs");
    }
}

fetchStats();
</script>
</body>
</html>
""", **STATS)

# -----------------------------
# STATS ENDPOINT
# -----------------------------
@app.route("/stats")
def stats():
    return jsonify({
        "requests": STATS["requests"],
        "cache_hits": STATS["cache_hits"],
        "downloads": STATS["downloads"],
        "unique_ips": list(STATS["unique_ips"]),
        "videos_served": STATS["videos_served"],
        "download_logs": DOWNLOAD_LOGS
    })

# -----------------------------
# RUN APP
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)