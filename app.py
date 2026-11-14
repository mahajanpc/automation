import json
import logging
import subprocess
import threading
from pathlib import Path
from flask import Flask, jsonify, render_template_string, send_file, request
from src.config import Config
from src.uploader import MediaUploader
from src.instagram import InstagramPublisher

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

STATE_FILE = Config.ROOT_DIR / "current_reel.json"
TOPICS_FILE = Config.ROOT_DIR / "topics.json"

def get_current_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error reading state file: {e}")
    return {
        "topic": "Daily Health Reel",
        "category": "Health",
        "hook": "Stay healthy with Arovia!",
        "video_path": None,
        "video_filename": None,
        "cloudinary_url": None,
        "caption": "Daily health tips in Telugu! #Arovia360",
        "scenes": [],
        "status": "idle",
        "published_post_id": None
    }

def get_topics_preview(limit=5):
    if TOPICS_FILE.exists():
        try:
            with open(TOPICS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data[:limit]
        except Exception:
            pass
    return []

# Background generation task tracker
generation_lock = threading.Lock()
generation_status = {"running": False, "message": "Idle"}

def run_generation_task(topic=None):
    global generation_status
    with generation_lock:
        generation_status = {"running": True, "message": "Generating script & voiceover..."}
        try:
            cmd = [str(Config.ROOT_DIR / ".venv" / "bin" / "python3"), "main.py", "--mode", "review"]
            if topic:
                cmd.extend(["--topic", topic])
            res = subprocess.run(cmd, cwd=str(Config.ROOT_DIR), capture_output=True, text=True)
            if res.returncode == 0:
                generation_status = {"running": False, "message": "Completed successfully!"}
            else:
                generation_status = {"running": False, "message": f"Error: {res.stderr[:200]}"}
        except Exception as e:
            generation_status = {"running": False, "message": f"Exception: {e}"}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arovia Health Reels - Creator Control Center</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; background-color: #0b0f19; color: #f3f4f6; }
        .glass-panel { background: rgba(17, 24, 39, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); }
        .accent-gradient { background: linear-gradient(135deg, #10b981 0%, #059669 100%); }
        .ig-gradient { background: linear-gradient(45deg, #f09433 0%, #e6683c 25%, #dc2743 50%, #cc2366 75%, #bc1888 100%); }
    </style>
</head>
<body class="min-h-screen pb-12">
    <!-- Navbar -->
    <header class="border-b border-gray-800 bg-gray-950/80 backdrop-blur sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
            <div class="flex items-center space-x-3">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-400 flex items-center justify-center text-white font-black text-xl shadow-lg shadow-emerald-500/20">
                    A
                </div>
                <div>
                    <h1 class="font-bold text-lg leading-tight tracking-wide text-white">AROVIA 360</h1>
                    <p class="text-xs text-emerald-400 flex items-center gap-1">
                        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
                        Automated Telugu Health Reels
                    </p>
                </div>
            </div>

            <div class="flex items-center space-x-3">
                <span class="text-xs px-3 py-1.5 rounded-full bg-gray-800 border border-gray-700 text-gray-300 flex items-center gap-2">
                    <span class="text-pink-500">📸</span> @arovia360
                    <span class="w-2 h-2 rounded-full bg-green-500"></span>
                </span>
                <button onclick="triggerGenerate()" id="genBtn" class="text-xs font-semibold px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 transition flex items-center gap-1.5">
                    <span>🔄</span> Generate Next Reel
                </button>
            </div>
        </div>
    </header>

    <!-- Main Container -->
    <main class="max-w-7xl mx-auto px-4 mt-6">
        <!-- Top Status Banner -->
        <div id="statusAlert" class="hidden mb-6 p-4 rounded-xl border"></div>

        <div class="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
            <!-- Left Column: Video Phone Mockup (5 cols) -->
            <div class="lg:col-span-5 flex flex-col items-center">
                <div class="relative w-[320px] sm:w-[350px] aspect-[9/16] rounded-[38px] p-2 bg-gradient-to-b from-gray-800 to-gray-900 border-4 border-gray-700 shadow-2xl overflow-hidden shadow-emerald-950/40">
                    <!-- Dynamic Island Mockup -->
                    <div class="absolute top-4 left-1/2 -translate-x-1/2 w-24 h-5 bg-black rounded-full z-20 flex items-center justify-center">
                        <div class="w-2.5 h-2.5 rounded-full bg-gray-900 ml-auto mr-2"></div>
                    </div>

                    <!-- Video Container -->
                    <div class="w-full h-full rounded-[30px] overflow-hidden bg-black relative">
                        {% if video_exists %}
                        <video id="reelVideo" controls autoplay loop playsinline class="w-full h-full object-cover">
                            <source src="/video?v={{ state.created_at }}" type="video/mp4">
                            Your browser does not support the video tag.
                        </video>
                        {% else %}
                        <div class="w-full h-full flex flex-col items-center justify-center p-6 text-center text-gray-400">
                            <span class="text-4xl mb-3">🎬</span>
                            <p class="font-medium">No Reel generated yet</p>
                            <p class="text-xs text-gray-500 mt-1">Click 'Generate Next Reel' to create today's video</p>
                        </div>
                        {% endif %}
                    </div>
                </div>

                <!-- Video Controls / Actions -->
                <div class="mt-4 flex items-center gap-3 w-[320px] sm:w-[350px]">
                    <a href="/video" download="{{ state.video_filename or 'health_reel.mp4' }}" class="flex-1 py-2.5 px-4 rounded-xl bg-gray-800 hover:bg-gray-700 border border-gray-700 text-center text-xs font-semibold flex items-center justify-center gap-2 transition">
                        <span>📥</span> Download MP4
                    </a>
                    {% if state.cloudinary_url %}
                    <a href="{{ state.cloudinary_url }}" target="_blank" class="py-2.5 px-4 rounded-xl bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs font-semibold flex items-center gap-1.5 transition">
                        <span>☁️</span> Cloud Link
                    </a>
                    {% endif %}
                </div>
            </div>

            <!-- Right Column: Reel Details, Actions & Story Breakdown (7 cols) -->
            <div class="lg:col-span-7 space-y-6">
                <!-- Action Header Card -->
                <div class="glass-panel p-6 rounded-2xl shadow-xl">
                    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
                        <span class="px-3 py-1 rounded-full text-xs font-semibold tracking-wide uppercase bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                            {{ state.category }}
                        </span>

                        <div id="publishBadge">
                            {% if state.status == 'published' %}
                            <span class="px-3 py-1 rounded-full text-xs font-bold bg-green-500/20 text-green-400 border border-green-500/30 flex items-center gap-1.5">
                                <span>✅</span> Live on Instagram
                            </span>
                            {% else %}
                            <span class="px-3 py-1 rounded-full text-xs font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 flex items-center gap-1.5">
                                <span>📝</span> Draft (Ready for Review)
                            </span>
                            {% endif %}
                        </div>
                    </div>

                    <h2 class="text-2xl font-extrabold text-white leading-tight mb-2">
                        {{ state.topic }}
                    </h2>
                    <p class="text-sm text-emerald-300/80 mb-6 italic">
                        "{{ state.hook }}"
                    </p>

                    <!-- Big 1-Click Publish Button -->
                    <div class="pt-2 border-t border-gray-800 flex flex-wrap items-center gap-4">
                        <button onclick="publishToInstagram()" id="publishBtn" class="flex-1 ig-gradient hover:opacity-95 text-white font-bold py-3.5 px-6 rounded-xl shadow-lg shadow-pink-600/25 flex items-center justify-center gap-2 transition transform active:scale-95 text-sm sm:text-base">
                            <span>🚀</span> Publish Live to Instagram (@arovia360)
                        </button>
                    </div>
                </div>

                <!-- Instagram Caption & Hashtags Box -->
                <div class="glass-panel p-6 rounded-2xl">
                    <div class="flex items-center justify-between mb-3">
                        <h3 class="text-sm font-bold text-gray-300 uppercase tracking-wider flex items-center gap-2">
                            <span>📋</span> Instagram Caption & Hashtags
                        </h3>
                        <button onclick="copyCaption()" id="copyBtn" class="text-xs bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 border border-emerald-500/30 px-3 py-1.5 rounded-lg transition flex items-center gap-1 font-semibold">
                            <span>Copy</span>
                        </button>
                    </div>
                    <div class="bg-gray-950/80 p-4 rounded-xl border border-gray-800/80 text-sm text-gray-300 whitespace-pre-line font-mono select-all" id="captionText">
{{ state.caption }}
                    </div>
                </div>

                <!-- 5-Beat Storytelling Breakdown -->
                <div class="glass-panel p-6 rounded-2xl">
                    <h3 class="text-sm font-bold text-gray-300 uppercase tracking-wider mb-4 flex items-center gap-2">
                        <span>🎬</span> 5-Beat Storytelling Arc
                    </h3>
                    <div class="space-y-3">
                        {% for scene in state.scenes %}
                        <div class="p-3.5 rounded-xl bg-gray-950/50 border border-gray-800/80 flex items-start gap-3">
                            <span class="w-6 h-6 rounded-full bg-emerald-500/20 text-emerald-400 font-bold text-xs flex items-center justify-center shrink-0 mt-0.5">
                                {{ loop.index }}
                            </span>
                            <div class="flex-1 min-w-0">
                                <p class="text-xs text-gray-400 mb-1">
                                    <span class="text-gray-500">Visual Query:</span> <code class="text-emerald-400 bg-emerald-950/50 px-1.5 py-0.5 rounded text-[11px]">{{ scene.visual_query }}</code>
                                </p>
                                <p class="text-sm font-semibold text-white mb-1.5">{{ scene.telugu_speech }}</p>
                                <div class="flex flex-wrap gap-1.5">
                                    {% for sub in scene.subtitles %}
                                    <span class="text-[11px] font-bold px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20">
                                        {{ sub }}
                                    </span>
                                    {% endfor %}
                                </div>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </div>
    </main>

    <!-- Script for Interactions -->
    <script>
        function copyCaption() {
            const text = document.getElementById("captionText").innerText;
            navigator.clipboard.writeText(text).then(() => {
                const btn = document.getElementById("copyBtn");
                btn.innerHTML = "<span>✅ Copied!</span>";
                btn.classList.add("bg-green-600/30", "text-green-300");
                setTimeout(() => {
                    btn.innerHTML = "<span>Copy</span>";
                    btn.classList.remove("bg-green-600/30", "text-green-300");
                }, 2000);
            });
        }

        async function publishToInstagram() {
            const btn = document.getElementById("publishBtn");
            const alertBox = document.getElementById("statusAlert");
            
            if (!confirm("Are you sure you want to publish this Reel LIVE to Instagram (@arovia360)?")) {
                return;
            }

            btn.disabled = true;
            btn.innerHTML = "<span class='animate-spin'>⏳</span> Publishing to Instagram Reels...";

            try {
                const res = await fetch("/api/publish", { method: "POST" });
                const data = await res.json();

                if (data.success) {
                    alertBox.className = "mb-6 p-4 rounded-xl border bg-emerald-500/10 border-emerald-500/30 text-emerald-300 flex items-center justify-between";
                    alertBox.innerHTML = `
                        <div>
                            <p class="font-bold text-base">🎉 Successfully Published to Instagram!</p>
                            <p class="text-xs text-emerald-400 mt-0.5">Post ID: ${data.post_id} | Check your Instagram profile @arovia360</p>
                        </div>
                        <a href="https://instagram.com/arovia360" target="_blank" class="px-4 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white font-semibold text-xs">
                            View on Instagram
                        </a>
                    `;
                    alertBox.classList.remove("hidden");
                    btn.innerHTML = "<span>✅ Already Published</span>";
                    document.getElementById("publishBadge").innerHTML = `
                        <span class="px-3 py-1 rounded-full text-xs font-bold bg-green-500/20 text-green-400 border border-green-500/30 flex items-center gap-1.5">
                            <span>✅</span> Live on Instagram
                        </span>
                    `;
                } else {
                    alert("Publishing Failed: " + (data.error || "Unknown error"));
                    btn.disabled = false;
                    btn.innerHTML = "<span>🚀</span> Retry Publishing to Instagram";
                }
            } catch (err) {
                alert("Network error: " + err);
                btn.disabled = false;
                btn.innerHTML = "<span>🚀</span> Publish Live to Instagram (@arovia360)";
            }
        }

        async function triggerGenerate() {
            const btn = document.getElementById("genBtn");
            btn.disabled = true;
            btn.innerHTML = "<span class='animate-spin'>⏳</span> Generating...";

            try {
                const res = await fetch("/api/generate", { method: "POST" });
                const data = await res.json();
                alert(data.message);
                checkStatusInterval();
            } catch (e) {
                alert("Error starting generation: " + e);
                btn.disabled = false;
                btn.innerHTML = "<span>🔄</span> Generate Next Reel";
            }
        }

        function checkStatusInterval() {
            const interval = setInterval(async () => {
                const res = await fetch("/api/status");
                const data = await res.json();
                if (!data.running) {
                    clearInterval(interval);
                    location.reload();
                }
            }, 3000);
        }
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    state = get_current_state()
    video_path = Path(state.get("video_path", "")) if state.get("video_path") else None
    video_exists = bool(video_path and video_path.exists())
    return render_template_string(HTML_TEMPLATE, state=state, video_exists=video_exists)

@app.route("/video")
def serve_video():
    state = get_current_state()
    video_path = Path(state.get("video_path", "")) if state.get("video_path") else None
    if video_path and video_path.exists():
        return send_file(video_path, mimetype="video/mp4")
    return "Video not found", 404

@app.route("/api/publish", methods=["POST"])
def api_publish():
    state = get_current_state()
    video_path_str = state.get("video_path")
    if not video_path_str or not Path(video_path_str).exists():
        return jsonify({"success": False, "error": "No local video file found to publish."}), 400

    video_path = Path(video_path_str)
    public_url = state.get("cloudinary_url")

    # If not uploaded to Cloudinary yet, upload now
    if not public_url:
        try:
            uploader = MediaUploader()
            public_url = uploader.upload_video(video_path)
            state["cloudinary_url"] = public_url
        except Exception as e:
            return jsonify({"success": False, "error": f"Cloudinary upload failed: {e}"}), 500

    # Call Instagram Graph API
    try:
        publisher = InstagramPublisher()
        result = publisher.publish_video(
            video_url=public_url,
            caption=state.get("caption", "Health tips in Telugu #Arovia360"),
            media_type="REELS"
        )
        post_id = result.get("id")
        state["status"] = "published"
        state["published_post_id"] = post_id
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        return jsonify({"success": True, "post_id": post_id})
    except Exception as e:
        logger.error(f"Publishing failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/generate", methods=["POST"])
def api_generate():
    global generation_status
    if generation_status["running"]:
        return jsonify({"success": False, "message": "Generation already in progress!"}), 400

    req_data = request.get_json(silent=True) or {}
    topic = req_data.get("topic")

    t = threading.Thread(target=run_generation_task, args=(topic,))
    t.daemon = True
    t.start()
    return jsonify({"success": True, "message": "Reel generation started! Page will refresh when ready."})

@app.route("/api/status")
def api_status():
    global generation_status
    return jsonify(generation_status)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

