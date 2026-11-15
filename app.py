import os
import json
import logging
import re
import subprocess
import threading
import time
import datetime
from pathlib import Path
from flask import Flask, jsonify, render_template_string, send_file, request, redirect

from src.config import Config
from src.uploader import MediaUploader
from src.instagram import InstagramPublisher
import cloudinary.api
import requests

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Ensure Cloudinary SDK is globally authenticated on startup
def configure_cloudinary():
    if Config.is_valid_key(Config.CLOUDINARY_URL):
        import urllib.parse
        try:
            parsed = urllib.parse.urlparse(Config.CLOUDINARY_URL)
            cloudinary.config(
                cloud_name=parsed.hostname,
                api_key=parsed.username,
                api_secret=parsed.password,
                secure=True
            )
        except Exception as e:
            logger.warning(f"Could not configure Cloudinary: {e}")

configure_cloudinary()

STATE_FILE = Config.ROOT_DIR / "current_reel.json"
TOPICS_FILE = Config.ROOT_DIR / "topics.json"
FEEDBACK_FILE = Config.ROOT_DIR / "feedback_history.json"
SCHEDULE_FILE = Config.ROOT_DIR / "schedule_config.json"
WORKFLOW_FILE = Config.ROOT_DIR / ".github" / "workflows" / "daily_reel.yml"
ENV_FILE = Config.ROOT_DIR / ".env"

# -------------------------------------------------------------
# Helpers
# -------------------------------------------------------------
def get_current_state():
    state = None
    local_path = None

    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                if state.get("video_path"):
                    local_path = Path(state["video_path"])
        except Exception as e:
            logger.warning(f"Error reading state file: {e}")

    # If running on Vercel or ephemeral container (where local_path does not exist on disk),
    # fetch the freshest state committed to GitHub main
    if not local_path or not local_path.exists():
        try:
            gh_raw_url = f"https://raw.githubusercontent.com/mahajanpc/automation/main/current_reel.json?t={int(time.time())}"
            r = requests.get(gh_raw_url, timeout=3)
            if r.status_code == 200:
                remote_state = r.json()
                if remote_state and remote_state.get("topic"):
                    state = remote_state
        except Exception as e:
            logger.debug(f"GitHub remote state fetch: {e}")

    if not state:
        state = {
            "topic": "Daily Health Reel",
            "category": "Nutrition and food",
            "hook": "Stay healthy with Arovia!",
            "video_path": None,
            "video_filename": None,
            "cloudinary_url": None,
            "caption": "Daily health tips in Telugu! #TeluguHealth #Arovia360",
            "scenes": [],
            "status": "ready_for_review",
            "published_post_id": None
        }

    # Query Cloudinary directly for the freshest uploaded stream
    configure_cloudinary()
    if Config.is_valid_key(Config.CLOUDINARY_URL):
        try:
            res = cloudinary.api.resources(
                resource_type="video",
                type="upload",
                prefix="instagram_automation",
                max_results=30
            )
            resources = res.get("resources", [])
            if resources:
                sorted_res = sorted(resources, key=lambda x: x.get("created_at", ""), reverse=True)
                latest = sorted_res[0]
                state["cloudinary_url"] = latest.get("secure_url")
                state["video_filename"] = latest.get("public_id")
                state["status"] = "ready_for_review"
        except Exception as e:
            logger.warning(f"Cloudinary fetch fallback: {e}")

    return state

def get_feedback_items():
    if FEEDBACK_FILE.exists():
        try:
            with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_feedback_items(items):
    with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

def get_schedule():
    if SCHEDULE_FILE.exists():
        try:
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "cron": "0 12 * * *",
        "time_ist": "17:30",
        "time_utc": "12:00",
        "timezone": "Asia/Kolkata",
        "label": "Daily at 5:30 PM IST (12:00 UTC)",
        "enabled": True
    }

def ist_to_utc_cron(ist_hour: int, ist_minute: int):
    total_ist_min = ist_hour * 60 + ist_minute
    total_utc_min = (total_ist_min - 330) % 1440
    utc_hour = total_utc_min // 60
    utc_min = total_utc_min % 60
    return f"{utc_min} {utc_hour} * * *", f"{utc_hour:02d}:{utc_min:02d}"

def update_workflow_cron(new_cron: str):
    if not WORKFLOW_FILE.exists():
        return False
    try:
        content = WORKFLOW_FILE.read_text(encoding="utf-8")
        updated = re.sub(r"- cron:\s*'[^']*'", f"- cron: '{new_cron}'", content)
        WORKFLOW_FILE.write_text(updated, encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"Error updating workflow cron: {e}")
        return False

def update_env_variable(key: str, value: str):
    if not ENV_FILE.exists():
        return
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f'{key}="{value}"')
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f'{key}="{value}"')
    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ[key] = value

# -------------------------------------------------------------
# Background Generation Tracker
# -------------------------------------------------------------
generation_lock = threading.Lock()
generation_status = {
    "running": False,
    "status": "idle",
    "progress": 0,
    "step": "Idle",
    "message": "Ready to generate",
    "error": None,
    "details": None,
    "target": "local",
    "topic": None,
    "run_id": None,
    "run_url": None,
    "start_time": 0
}

def run_local_generation(topic=None, category=None):
    global generation_status
    import traceback
    with generation_lock:
        generation_status.update({
            "running": True,
            "status": "running",
            "progress": 10,
            "step": "Initializing Pipeline",
            "message": "Starting generation pipeline...",
            "target": "local",
            "topic": topic,
            "error": None,
            "details": None,
            "start_time": time.time()
        })

        cmd = [str(Config.ROOT_DIR / ".venv" / "bin" / "python3"), "main.py", "--mode", "review"]
        if topic:
            cmd.extend(["--topic", topic])
        if category:
            cmd.extend(["--category", category])

        recent_logs = []
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(Config.ROOT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            for line in proc.stdout:
                line_str = line.strip()
                if not line_str:
                    continue
                logger.info(f"[pipeline] {line_str}")
                recent_logs.append(line_str)
                if len(recent_logs) > 50:
                    recent_logs.pop(0)

                if "Step 2: Content Generation" in line_str:
                    generation_status.update({"progress": 25, "step": "Gemini AI Scriptwriting", "message": "Drafting 5-beat viral script..."})
                elif "Step 3: Voiceover & Subtitles" in line_str:
                    generation_status.update({"progress": 45, "step": "Telugu Voiceover Synthesis", "message": "Synthesizing authentic native Telugu voice..."})
                elif "Step 4: Multi-clip Visual Fetching" in line_str:
                    generation_status.update({"progress": 65, "step": "HD Stock Video Fetch", "message": "Downloading 9:16 vertical clips from Pixabay..."})
                elif "Step 5: Video Assembly" in line_str:
                    generation_status.update({"progress": 85, "step": "FFmpeg Assembly & Subtitles", "message": "Burning kinetic subtitles and scaling to 1080x1920..."})
                elif "Upload to Cloudinary" in line_str:
                    generation_status.update({"progress": 95, "step": "Cloudinary Staging", "message": "Uploading cloud review stream..."})

            proc.wait()

            if proc.returncode == 0:
                generation_status.update({
                    "running": False,
                    "status": "completed",
                    "progress": 100,
                    "step": "Complete",
                    "message": "Reel successfully generated and ready for review!",
                    "error": None,
                    "details": None
                })
            else:
                err_lines = [l for l in recent_logs if "ERROR" in l or "Traceback" in l or "Exception" in l or "Error" in l]
                err_summary = err_lines[-1] if err_lines else f"Pipeline process exited with error code {proc.returncode}"
                generation_status.update({
                    "running": False,
                    "status": "failed",
                    "progress": 0,
                    "step": "Pipeline Process Error",
                    "error": err_summary,
                    "details": "\n".join(recent_logs),
                    "message": f"Pipeline failed: {err_summary}"
                })
        except Exception as e:
            generation_status.update({
                "running": False,
                "status": "failed",
                "progress": 0,
                "step": "Execution Exception",
                "error": str(e),
                "details": traceback.format_exc(),
                "message": f"Execution error: {e}"
            })

# -------------------------------------------------------------
# Frontend HTML Template
# -------------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Arovia 360 - Creator Studio & Automation Center</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚡</text></svg>">
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Plus Jakarta Sans', sans-serif; background-color: #080c14; color: #f3f4f6; }
        .font-mono { font-family: 'JetBrains Mono', monospace; }
        .glass-panel { background: rgba(15, 23, 42, 0.75); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.08); }
        .accent-gradient { background: linear-gradient(135deg, #10b981 0%, #059669 100%); }
        .ig-gradient { background: linear-gradient(45deg, #f09433 0%, #e6683c 25%, #dc2743 50%, #cc2366 75%, #bc1888 100%); }
        .tab-btn.active { background: rgba(16, 185, 129, 0.15); color: #34d399; border-color: rgba(16, 185, 129, 0.4); }
    </style>
</head>
<body class="min-h-screen pb-16">
    <!-- Navbar -->
    <header class="border-b border-gray-800/80 bg-gray-950/90 backdrop-blur sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 py-3 flex flex-wrap items-center justify-between gap-4">
            <div class="flex items-center space-x-3">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-400 flex items-center justify-center text-white font-extrabold text-xl shadow-lg shadow-emerald-500/25">
                    A
                </div>
                <div>
                    <div class="flex items-center gap-2">
                        <h1 class="font-bold text-lg leading-tight tracking-wide text-white">AROVIA 360</h1>
                        <span class="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">Studio v2</span>
                    </div>
                    <p class="text-xs text-gray-400 flex items-center gap-1.5 mt-0.5">
                        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                        Automated Telugu Health Reels & Stories
                    </p>
                </div>
            </div>

            <!-- Navigation Tabs -->
            <nav class="flex items-center gap-1.5 bg-gray-900/90 p-1.5 rounded-xl border border-gray-800">
                <button onclick="switchTab('review')" id="tab-review" class="tab-btn active px-3.5 py-1.5 rounded-lg text-xs font-semibold text-gray-300 border border-transparent transition flex items-center gap-1.5">
                    <span>📱</span> Review & Publish
                </button>
                <button onclick="switchTab('create')" id="tab-create" class="tab-btn px-3.5 py-1.5 rounded-lg text-xs font-semibold text-gray-300 border border-transparent transition flex items-center gap-1.5">
                    <span>⚡</span> Instant Studio
                </button>
                <button onclick="switchTab('schedule')" id="tab-schedule" class="tab-btn px-3.5 py-1.5 rounded-lg text-xs font-semibold text-gray-300 border border-transparent transition flex items-center gap-1.5">
                    <span>⏰</span> Schedule
                </button>
                <button onclick="switchTab('feedback')" id="tab-feedback" class="tab-btn px-3.5 py-1.5 rounded-lg text-xs font-semibold text-gray-300 border border-transparent transition flex items-center gap-1.5">
                    <span>🧠</span> AI Directives
                </button>
                <button onclick="switchTab('usage')" id="tab-usage" class="tab-btn px-3.5 py-1.5 rounded-lg text-xs font-semibold text-gray-300 border border-transparent transition flex items-center gap-1.5">
                    <span>📊</span> API Quotas
                </button>
            </nav>

            <div class="flex items-center space-x-3">
                <span class="text-xs px-3 py-1.5 rounded-full bg-gray-800/80 border border-gray-700 text-gray-300 flex items-center gap-2">
                    <span class="text-pink-500">📸</span> @arovia360
                    <span class="w-2 h-2 rounded-full bg-green-500"></span>
                </span>
            </div>
        </div>
    </header>

    <!-- Main Container -->
    <main class="max-w-7xl mx-auto px-4 mt-6">
        <!-- Top Status Alert Box -->
        <div id="statusAlert" class="hidden mb-6 p-4 rounded-xl border"></div>

        <!-- Global Live Generation Progress Banner (Stays visible until video is 100% ready) -->
        <div id="genProgressBanner" class="hidden mb-6 glass-panel p-6 rounded-2xl border border-emerald-500/40 shadow-2xl shadow-emerald-950/40 transition-all">
            <div class="flex flex-wrap items-center justify-between gap-3 mb-3">
                <div class="flex items-center gap-3">
                    <div class="relative flex items-center justify-center">
                        <div class="w-4 h-4 rounded-full bg-emerald-400 animate-ping"></div>
                        <div class="absolute w-2.5 h-2.5 rounded-full bg-emerald-300"></div>
                    </div>
                    <div>
                        <h3 class="font-extrabold text-base text-white tracking-wide flex items-center gap-2" id="progressStepTitle">
                            Generating 30s Telugu Health Reel...
                        </h3>
                        <p class="text-xs text-gray-400 mt-0.5" id="progressMsg">Starting multi-scene pipeline...</p>
                    </div>
                </div>
                <div class="flex items-center gap-2">
                    <span class="text-xs px-3 py-1 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-mono font-bold" id="progressPercent">
                        15%
                    </span>
                </div>
            </div>

            <!-- Animated Progress Bar -->
            <div class="w-full bg-gray-950 rounded-full h-3 overflow-hidden p-0.5 border border-gray-800 my-4">
                <div id="progressBar" class="accent-gradient h-full rounded-full transition-all duration-700 shadow-lg shadow-emerald-500/50" style="width: 15%"></div>
            </div>

            <!-- 5-Stage Stepper Indicators -->
            <div class="grid grid-cols-2 sm:grid-cols-5 gap-2 text-[11px] font-semibold text-gray-400">
                <div id="step-pill-1" class="p-2 rounded-xl bg-gray-950/60 border border-gray-800 flex items-center gap-1.5 transition">
                    <span class="text-xs">💡</span>
                    <span>1. Gemini Script</span>
                </div>
                <div id="step-pill-2" class="p-2 rounded-xl bg-gray-950/60 border border-gray-800 flex items-center gap-1.5 transition">
                    <span class="text-xs">🎙️</span>
                    <span>2. Telugu Voice</span>
                </div>
                <div id="step-pill-3" class="p-2 rounded-xl bg-gray-950/60 border border-gray-800 flex items-center gap-1.5 transition">
                    <span class="text-xs">🎥</span>
                    <span>3. HD Pixabay</span>
                </div>
                <div id="step-pill-4" class="p-2 rounded-xl bg-gray-950/60 border border-gray-800 flex items-center gap-1.5 transition">
                    <span class="text-xs">✂️</span>
                    <span>4. FFmpeg Subtitles</span>
                </div>
                <div id="step-pill-5" class="p-2 rounded-xl bg-gray-950/60 border border-gray-800 flex items-center gap-1.5 transition">
                    <span class="text-xs">☁️</span>
                    <span>5. Cloud Staging</span>
                </div>
            </div>
        </div>

        <!-- ============================================================== -->
        <!-- TAB 1: REVIEW & PUBLISH (Default)                              -->
        <!-- ============================================================== -->
        <section id="view-review" class="tab-view">
            <div class="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
                <!-- Phone Mockup (5 cols) -->
                <div class="lg:col-span-5 flex flex-col items-center">
                    <div class="relative w-[320px] sm:w-[350px] aspect-[9/16] rounded-[40px] p-2.5 bg-gradient-to-b from-gray-800 to-gray-900 border-4 border-gray-700 shadow-2xl overflow-hidden shadow-emerald-950/40">
                        <!-- Dynamic Island -->
                        <div class="absolute top-4 left-1/2 -translate-x-1/2 w-24 h-5 bg-black rounded-full z-20 flex items-center justify-center">
                            <div class="w-2.5 h-2.5 rounded-full bg-gray-900 ml-auto mr-2"></div>
                        </div>

                        <!-- Video Container -->
                        <div class="w-full h-full rounded-[30px] overflow-hidden bg-black relative">
                            {% if video_exists %}
                            <video id="reelVideo" controls autoplay loop playsinline class="w-full h-full object-cover">
                                <source src="{{ state.cloudinary_url or '/video' }}?t={{ state.video_filename or state.created_at }}" type="video/mp4">
                                Your browser does not support the video tag.
                            </video>
                            {% else %}
                            <div class="w-full h-full flex flex-col items-center justify-center p-6 text-center text-gray-400">
                                <span class="text-4xl mb-3">🎬</span>
                                <p class="font-medium">No Reel generated yet</p>
                                <p class="text-xs text-gray-500 mt-1">Use the Instant Studio or wait for daily schedule</p>
                            </div>
                            {% endif %}
                        </div>
                    </div>

                    <!-- Video Controls -->
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

                <!-- Story Breakdown & Publish Card (7 cols) -->
                <div class="lg:col-span-7 space-y-6">
                    <div class="glass-panel p-6 rounded-2xl shadow-xl">
                        <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
                            <span class="px-3 py-1 rounded-full text-xs font-semibold tracking-wide uppercase bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                {{ state.category }}
                            </span>

                            <div id="publishBadge">
                                {% if state.status == 'published' %}
                                <span class="px-3 py-1 rounded-full text-xs font-bold bg-green-500/20 text-green-400 border border-green-500/30 flex items-center gap-1.5">
                                    <span>✅</span> Live on Instagram (@arovia360)
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

                        <!-- 1-Click Publish Button -->
                        <div class="pt-2 border-t border-gray-800 flex flex-wrap items-center gap-4">
                            <button onclick="publishToInstagram()" id="publishBtn" class="flex-1 ig-gradient hover:opacity-95 text-white font-bold py-3.5 px-6 rounded-xl shadow-lg shadow-pink-600/25 flex items-center justify-center gap-2 transition transform active:scale-95 text-sm sm:text-base">
                                <span>🚀</span> 1-Click Publish Live to Instagram (@arovia360)
                            </button>
                        </div>
                    </div>

                    <!-- Instagram Caption & Hashtags -->
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
                            <span>🎬</span> 5-Beat Storytelling Breakdown
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
        </section>

        <!-- ============================================================== -->
        <!-- TAB 2: INSTANT STUDIO                                          -->
        <!-- ============================================================== -->
        <section id="view-create" class="tab-view hidden max-w-4xl mx-auto space-y-6">
            <div class="glass-panel p-6 sm:p-8 rounded-3xl shadow-xl">
                <div class="flex items-center justify-between mb-4">
                    <div>
                        <h2 class="text-xl font-extrabold text-white flex items-center gap-2">
                            <span>⚡</span> Instant Reel Creator
                        </h2>
                        <p class="text-xs text-gray-400 mt-1">Generate a brand new Telugu Health Reel on demand without waiting for cron schedule.</p>
                    </div>
                    <span class="text-xs font-semibold px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        100% Free Pipeline
                    </span>
                </div>

                <div class="space-y-5 mt-6">
                    <!-- Custom Topic Field -->
                    <div>
                        <label class="block text-xs font-bold uppercase tracking-wider text-gray-300 mb-2">
                            Health Topic / Question
                        </label>
                        <div class="relative">
                            <input type="text" id="customTopicInput" placeholder="e.g. Benefits of drinking warm lemon water every morning (or leave blank to auto-pick)" class="w-full px-4 py-3 rounded-xl bg-gray-950/90 border border-gray-800 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-emerald-500 transition">
                            <button onclick="pickRandomTopic()" class="absolute right-2 top-2 px-3 py-1 rounded-lg bg-gray-800 hover:bg-gray-700 text-xs text-gray-300 border border-gray-700 transition">
                                🎲 Surprise Me
                            </button>
                        </div>
                        <p class="text-[11px] text-gray-500 mt-1.5">Leaving this blank will automatically pick the next sequential topic from your 120-topic curriculum.</p>
                    </div>

                    <!-- Category Selector -->
                    <div>
                        <label class="block text-xs font-bold uppercase tracking-wider text-gray-300 mb-2">
                            Health Category
                        </label>
                        <select id="customCategoryInput" class="w-full px-4 py-3 rounded-xl bg-gray-950/90 border border-gray-800 text-sm text-white focus:outline-none focus:border-emerald-500 transition">
                            <option value="Nutrition and food">Nutrition & Food (Food items, superfoods, hydration)</option>
                            <option value="Disease prevention and conditions">Disease Prevention (Diabetes, BP, cholesterol, heart)</option>
                            <option value="Daily healthy habits">Daily Healthy Habits (Morning rituals, dental, posture)</option>
                            <option value="Sleep and mental wellness">Sleep & Mental Wellness (Anxiety, meditation, insomnia)</option>
                            <option value="Physical activity and movement">Physical Activity & Movement (Walking, stretching, exercise)</option>
                        </select>
                    </div>

                    <!-- Execution Runner Choice -->
                    <div>
                        <label class="block text-xs font-bold uppercase tracking-wider text-gray-300 mb-2">
                            Generation Engine
                        </label>
                        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <label class="p-3.5 rounded-xl border border-gray-800 bg-gray-950/60 hover:border-emerald-500/50 cursor-pointer flex items-start gap-3 transition">
                                <input type="radio" name="runnerType" value="github" checked class="mt-1 accent-emerald-500">
                                <div>
                                    <p class="text-xs font-bold text-white">☁️ Cloud Runner (GitHub Actions - Recommended)</p>
                                    <p class="text-[11px] text-gray-400 mt-0.5">Renders on cloud runner with FFmpeg & Telugu fonts, uploads to Cloudinary, and emails preview.</p>
                                </div>
                            </label>
                            <label class="p-3.5 rounded-xl border border-gray-800 bg-gray-950/60 hover:border-emerald-500/50 cursor-pointer flex items-start gap-3 transition">
                                <input type="radio" name="runnerType" value="local" class="mt-1 accent-emerald-500">
                                <div>
                                    <p class="text-xs font-bold text-white">⚡ Local Machine Runner</p>
                                    <p class="text-[11px] text-gray-400 mt-0.5">For running app.py locally on your own PC (http://localhost:5000).</p>
                                </div>
                            </label>
                        </div>
                    </div>

                    <!-- Action Button -->
                    <div class="pt-4 border-t border-gray-800 flex items-center justify-end gap-3">
                        <button onclick="startInstantGeneration()" id="startGenBtn" class="accent-gradient hover:opacity-95 text-white font-bold py-3.5 px-8 rounded-xl shadow-lg shadow-emerald-600/25 flex items-center gap-2 transition text-sm">
                            <span>⚡</span> Start Instant Reel Generation
                        </button>
                    </div>
                </div>
            </div>

            <!-- Quick Topics Catalog Preview -->
            <div class="glass-panel p-6 rounded-2xl">
                <h3 class="text-sm font-bold text-gray-300 uppercase tracking-wider mb-3 flex items-center gap-2">
                    <span>📚</span> Upcoming Topics In Catalog
                </h3>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    {% for topic in topics_preview %}
                    <div onclick="selectTopic('{{ topic.topic }}', '{{ topic.category }}')" class="p-3 rounded-xl bg-gray-950/50 border border-gray-800 hover:border-emerald-500/40 cursor-pointer transition flex items-center justify-between text-xs">
                        <span class="font-medium text-gray-200 truncate pr-2">{{ topic.topic }}</span>
                        <span class="text-[10px] uppercase font-bold text-emerald-400 shrink-0">Use ➜</span>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </section>

        <!-- ============================================================== -->
        <!-- TAB 3: SCHEDULE MANAGER                                        -->
        <!-- ============================================================== -->
        <section id="view-schedule" class="tab-view hidden max-w-4xl mx-auto space-y-6">
            <div class="glass-panel p-6 sm:p-8 rounded-3xl shadow-xl">
                <div class="flex items-center justify-between mb-4">
                    <div>
                        <h2 class="text-xl font-extrabold text-white flex items-center gap-2">
                            <span>⏰</span> Automated Daily Schedule Manager
                        </h2>
                        <p class="text-xs text-gray-400 mt-1">Configure when your automated Instagram reel is generated and delivered each day.</p>
                    </div>
                    <span id="scheduleStatusPill" class="text-xs font-semibold px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        Active Daily Cron
                    </span>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
                    <!-- Current Status Display -->
                    <div class="p-5 rounded-2xl bg-gray-950/80 border border-gray-800 space-y-3">
                        <span class="text-[11px] font-bold uppercase tracking-wider text-gray-400">Current Trigger Setting</span>
                        <p class="text-2xl font-black text-white" id="currentScheduleLabel">{{ schedule.label }}</p>
                        <div class="text-xs text-gray-400 space-y-1">
                            <p>Cron Expression: <code class="text-emerald-400 font-mono" id="currentCron">{{ schedule.cron }}</code></p>
                            <p>Target Timezone: <span class="text-white font-medium">Asia/Kolkata (IST)</span></p>
                            <p>Actions Workflow: <span class="text-emerald-400 font-mono">daily_reel.yml</span></p>
                        </div>
                    </div>

                    <!-- Schedule Presets & Time Picker -->
                    <div class="space-y-4">
                        <label class="block text-xs font-bold uppercase tracking-wider text-gray-300">
                            Choose Daily Posting Time (IST)
                        </label>
                        <div class="grid grid-cols-2 gap-2">
                            <button onclick="setPresetTime('09:00')" class="preset-btn p-2.5 rounded-xl border border-gray-800 bg-gray-950/60 hover:border-emerald-500/50 text-xs font-semibold text-gray-300 transition text-center">
                                🌅 9:00 AM IST
                            </button>
                            <button onclick="setPresetTime('13:00')" class="preset-btn p-2.5 rounded-xl border border-gray-800 bg-gray-950/60 hover:border-emerald-500/50 text-xs font-semibold text-gray-300 transition text-center">
                                ☀️ 1:00 PM IST
                            </button>
                            <button onclick="setPresetTime('17:30')" class="preset-btn p-2.5 rounded-xl border border-gray-800 bg-gray-950/60 hover:border-emerald-500/50 text-xs font-semibold text-gray-300 transition text-center">
                                🌆 5:30 PM IST (Default)
                            </button>
                            <button onclick="setPresetTime('20:00')" class="preset-btn p-2.5 rounded-xl border border-gray-800 bg-gray-950/60 hover:border-emerald-500/50 text-xs font-semibold text-gray-300 transition text-center">
                                🌙 8:00 PM IST
                            </button>
                        </div>

                        <div>
                            <label class="block text-[11px] font-semibold text-gray-400 mb-1">Or Enter Custom IST Time (24h format):</label>
                            <input type="time" id="customTimeInput" value="{{ schedule.time_ist }}" class="w-full px-4 py-2.5 rounded-xl bg-gray-950 border border-gray-800 text-sm text-white focus:outline-none focus:border-emerald-500">
                        </div>

                        <button onclick="saveSchedule()" id="saveScheduleBtn" class="w-full accent-gradient hover:opacity-95 text-white font-bold py-3 rounded-xl shadow-lg shadow-emerald-600/20 text-xs transition">
                            💾 Save & Synchronize Schedule with GitHub Actions
                        </button>
                    </div>
                </div>
            </div>
        </section>

        <!-- ============================================================== -->
        <!-- TAB 4: AI DIRECTIVES & FEEDBACK                                -->
        <!-- ============================================================== -->
        <section id="view-feedback" class="tab-view hidden max-w-4xl mx-auto space-y-6">
            <div class="glass-panel p-6 sm:p-8 rounded-3xl shadow-xl">
                <div class="flex items-center justify-between mb-4">
                    <div>
                        <h2 class="text-xl font-extrabold text-white flex items-center gap-2">
                            <span>🧠</span> AI Self-Learning & Continuous Feedback
                        </h2>
                        <p class="text-xs text-gray-400 mt-1">Every instruction below is automatically injected into Gemini prompts to refine future script, voiceover, and subtitle generations.</p>
                    </div>
                    <span class="text-xs font-mono font-bold px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" id="feedbackCountBadge">
                        {{ feedback_items|length }} Rules Active
                    </span>
                </div>

                <!-- Add New Directive Input -->
                <div class="bg-gray-950/80 p-4 rounded-2xl border border-gray-800 space-y-3">
                    <label class="block text-xs font-bold uppercase tracking-wider text-gray-300">
                        Add New Instruction for AI
                    </label>
                    <div class="flex gap-2">
                        <input type="text" id="newFeedbackInput" placeholder="e.g. Always emphasize drinking water before meals, use enthusiastic tone in Telugu..." class="flex-1 px-4 py-2.5 rounded-xl bg-gray-900 border border-gray-800 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-emerald-500 transition">
                        <button onclick="addFeedback()" id="addFeedbackBtn" class="accent-gradient hover:opacity-95 text-white font-bold px-5 py-2.5 rounded-xl text-xs flex items-center gap-1.5 transition">
                            <span>➕</span> Add Rule
                        </button>
                    </div>
                </div>

                <!-- Existing Rules List -->
                <div class="mt-6">
                    <h3 class="text-xs font-bold uppercase tracking-wider text-gray-400 mb-3">
                        Active AI Generation Directives
                    </h3>
                    <div class="space-y-2.5" id="feedbackList">
                        {% for item in feedback_items %}
                        <div class="p-3.5 rounded-xl bg-gray-950/50 border border-gray-800/80 flex items-start justify-between gap-3 group hover:border-gray-700 transition">
                            <div class="flex items-start gap-3">
                                <span class="w-5 h-5 rounded-full bg-emerald-500/10 text-emerald-400 font-bold text-xs flex items-center justify-center shrink-0 mt-0.5">
                                    {{ loop.index }}
                                </span>
                                <p class="text-xs text-gray-300 leading-relaxed">{{ item }}</p>
                            </div>
                            <button onclick="deleteFeedback({{ loop.index0 }})" class="text-gray-500 hover:text-red-400 text-xs px-2 py-1 rounded transition opacity-70 group-hover:opacity-100" title="Delete Rule">
                                🗑️
                            </button>
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </section>

        <!-- ============================================================== -->
        <!-- TAB 5: API QUOTAS & HEALTH MONITOR                             -->
        <!-- ============================================================== -->
        <section id="view-usage" class="tab-view hidden max-w-5xl mx-auto space-y-6">
            <div class="flex items-center justify-between">
                <div>
                    <h2 class="text-xl font-extrabold text-white flex items-center gap-2">
                        <span>📊</span> Real-Time API Usage & Health Monitor
                    </h2>
                    <p class="text-xs text-gray-400 mt-1">Live quotas, limits, and authentication status of all external services.</p>
                </div>
                <button onclick="refreshUsage()" id="refreshUsageBtn" class="px-4 py-2 rounded-xl bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs font-semibold text-gray-300 flex items-center gap-2 transition">
                    <span>🔄</span> Refresh Stats
                </button>
            </div>

            <!-- 4 Service Cards Grid -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6" id="usageGrid">
                <!-- Card 1: Google Gemini -->
                <div class="glass-panel p-6 rounded-2xl border-gray-800 space-y-3">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-2.5">
                            <span class="text-xl">✨</span>
                            <h3 class="font-bold text-sm text-white">Google Gemini AI</h3>
                        </div>
                        <span id="geminiStatusBadge" class="text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                            Checking...
                        </span>
                    </div>
                    <div class="space-y-1.5 text-xs text-gray-400">
                        <p>Model: <span class="text-white font-mono" id="geminiModel">gemini-3.1-flash-lite</span></p>
                        <p>Plan Quota: <span class="text-gray-300">15 RPM / 1M TPM / 1500 RPD</span></p>
                        <p>Monthly Cost: <span class="text-emerald-400 font-bold">$0.00 (Permanent Free Tier)</span></p>
                        <p id="geminiMsg" class="text-gray-500 italic mt-2"></p>
                    </div>
                </div>

                <!-- Card 2: Pixabay Stock Videos -->
                <div class="glass-panel p-6 rounded-2xl border-gray-800 space-y-3">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-2.5">
                            <span class="text-xl">🎥</span>
                            <h3 class="font-bold text-sm text-white">Pixabay HD Stock Videos</h3>
                        </div>
                        <span id="pixabayStatusBadge" class="text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                            Checking...
                        </span>
                    </div>
                    <div class="space-y-1.5 text-xs text-gray-400">
                        <p>Plan: <span class="text-white">Free Developer API</span></p>
                        <p>Rate Limit: <span class="text-gray-300" id="pixabayLimit">100 req / min</span></p>
                        <p>Remaining Requests: <span class="text-emerald-400 font-mono font-bold" id="pixabayRemaining">--</span></p>
                        <p id="pixabayMsg" class="text-gray-500 italic mt-2"></p>
                    </div>
                </div>

                <!-- Card 3: Cloudinary Storage -->
                <div class="glass-panel p-6 rounded-2xl border-gray-800 space-y-3">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-2.5">
                            <span class="text-xl">☁️</span>
                            <h3 class="font-bold text-sm text-white">Cloudinary Video Storage</h3>
                        </div>
                        <span id="cloudinaryStatusBadge" class="text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                            Checking...
                        </span>
                    </div>
                    <div class="space-y-1.5 text-xs text-gray-400">
                        <p>Plan: <span class="text-white" id="cloudinaryPlan">Free (25 Monthly Credits)</span></p>
                        <p>Storage Used: <span class="text-gray-300 font-mono" id="cloudinaryStorage">-- MB</span></p>
                        <p>Auto-Cleanup: <span class="text-emerald-400 font-semibold">Active (Deletes >24h old videos)</span></p>
                        <p id="cloudinaryMsg" class="text-gray-500 italic mt-2"></p>
                    </div>
                </div>

                <!-- Card 4: Instagram Graph API -->
                <div class="glass-panel p-6 rounded-2xl border-gray-800 space-y-3">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-2.5">
                            <span class="text-xl">📸</span>
                            <h3 class="font-bold text-sm text-white">Instagram Meta Graph API</h3>
                        </div>
                        <span id="instagramStatusBadge" class="text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-gray-800 text-gray-400 border border-gray-700">
                            Checking...
                        </span>
                    </div>
                    <div class="space-y-1.5 text-xs text-gray-400">
                        <p>Target Account: <span class="text-white font-bold">@arovia360</span> (ID: 17841464857297220)</p>
                        <p>Permissions: <span class="text-gray-300">instagram_content_publish</span></p>
                        <p id="instagramMsg" class="text-amber-300 text-[11px] mt-1"></p>
                    </div>
                    <div class="pt-2">
                        <button onclick="toggleTokenModal()" class="w-full py-2 rounded-xl bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs font-semibold text-gray-300 transition">
                            🔑 Update Access Token
                        </button>
                    </div>
                </div>
            </div>

            <!-- Token Update Modal / Drawer -->
            <div id="tokenUpdateBox" class="hidden glass-panel p-6 rounded-2xl border-amber-500/30 space-y-4">
                <h4 class="text-sm font-bold text-white flex items-center gap-2">
                    <span>🔑</span> Update Instagram Access Token
                </h4>
                <p class="text-xs text-gray-400 leading-relaxed">
                    Paste your renewed Meta User or Page Access Token below. The studio will automatically test it, update your local <code class="text-emerald-400">.env</code>, and reload credentials.
                </p>
                <div class="flex gap-2">
                    <input type="password" id="newTokenInput" placeholder="Paste EAA... access token here" class="flex-1 px-4 py-2.5 rounded-xl bg-gray-950 border border-gray-800 text-xs font-mono text-white focus:outline-none focus:border-emerald-500">
                    <button onclick="saveNewToken()" class="accent-gradient hover:opacity-95 text-white font-bold px-5 py-2.5 rounded-xl text-xs transition">
                        Verify & Save
                    </button>
                </div>
            </div>
        </section>

        <!-- Dedicated Exception & Diagnostic Modal -->
        <div id="errorModal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
            <div class="glass-panel border border-red-500/50 bg-gray-950/95 max-w-2xl w-full rounded-2xl p-6 shadow-2xl shadow-red-950/60 transition-all max-h-[90vh] flex flex-col">
                <div class="flex items-start justify-between gap-4 pb-4 border-b border-gray-800">
                    <div class="flex items-center gap-3">
                        <div class="w-10 h-10 rounded-xl bg-red-500/20 text-red-400 flex items-center justify-center text-xl font-bold border border-red-500/30">
                            ⚠️
                        </div>
                        <div>
                            <h3 class="text-base font-bold text-white tracking-wide" id="errorModalTitle">Pipeline Error</h3>
                            <p class="text-xs text-red-400 mt-0.5" id="errorModalSubtitle">An exception occurred during generation</p>
                        </div>
                    </div>
                    <button onclick="closeErrorModal()" class="text-gray-400 hover:text-white text-lg p-1">✕</button>
                </div>
                
                <div class="py-4 space-y-3 overflow-y-auto flex-1">
                    <div class="p-3.5 rounded-xl bg-red-950/30 border border-red-500/30 text-xs text-red-300 font-medium leading-relaxed" id="errorModalMessage">
                        Error message goes here...
                    </div>
                    
                    <div>
                        <div class="flex items-center justify-between mb-1.5">
                            <span class="text-[11px] font-bold uppercase tracking-wider text-gray-400">Diagnostic Details & Error Trace:</span>
                            <button onclick="copyErrorDiagnostics()" class="text-[11px] text-emerald-400 hover:text-emerald-300 font-mono flex items-center gap-1" id="copyDiagnosticsBtn">
                                <span>📋</span> Copy Log
                            </button>
                        </div>
                        <pre class="p-3.5 rounded-xl bg-black/80 border border-gray-800 text-[11px] font-mono text-gray-300 overflow-x-auto max-h-56 select-all whitespace-pre-wrap leading-relaxed" id="errorModalDetails">No trace available.</pre>
                    </div>

                    <div id="errorTroubleshooting" class="p-3.5 rounded-xl bg-blue-950/20 border border-blue-500/30 text-[11px] text-blue-300 space-y-1">
                        <p class="font-bold flex items-center gap-1.5 text-blue-200">
                            <span>💡</span> Suggested Fix / Next Steps:
                        </p>
                        <p id="errorSuggestionText" class="leading-relaxed text-blue-200/90">Check API quota or try another topic.</p>
                    </div>
                </div>

                <div class="pt-4 border-t border-gray-800 flex flex-wrap items-center justify-between gap-3">
                    <div id="errorModalActionContainer">
                        <!-- Dynamic external link (e.g. GitHub Actions Run) -->
                    </div>
                    <div class="flex items-center gap-2">
                        <button onclick="closeErrorModal()" class="px-4 py-2 rounded-xl bg-gray-800 hover:bg-gray-700 text-xs font-semibold text-gray-300 transition">
                            Dismiss
                        </button>
                        <button onclick="closeErrorModal(); startInstantGeneration();" class="accent-gradient hover:opacity-95 text-white text-xs font-bold px-4 py-2 rounded-xl transition flex items-center gap-1.5">
                            <span>🔄</span> Retry Generation
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </main>

    <!-- Client-Side Logic -->
    <script>
        // Tab Switching
        function switchTab(tabName) {
            document.querySelectorAll('.tab-view').forEach(el => el.classList.add('hidden'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

            document.getElementById('view-' + tabName).classList.remove('hidden');
            document.getElementById('tab-' + tabName).classList.add('active');

            if (tabName === 'usage') {
                refreshUsage();
            }
        }

        // Copy Caption
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

        // ==============================================================
        // Global Error & Exception Diagnostic Handler
        // ==============================================================
        function showErrorModal(title, subtitle, message, details, suggestion, actionUrl) {
            const modal = document.getElementById("errorModal");
            if (!modal) return;

            document.getElementById("errorModalTitle").innerText = title || "Pipeline Exception";
            document.getElementById("errorModalSubtitle").innerText = subtitle || "An error occurred during operation";
            document.getElementById("errorModalMessage").innerText = message || "Unknown error occurred.";
            document.getElementById("errorModalDetails").innerText = details || "No technical error trace available.";

            const suggEl = document.getElementById("errorSuggestionText");
            if (suggEl) {
                suggEl.innerText = suggestion || "Check your API keys in .env, verify server logs, or try another topic.";
            }

            const actionContainer = document.getElementById("errorModalActionContainer");
            if (actionContainer) {
                if (actionUrl) {
                    actionContainer.innerHTML = `
                        <a href="${actionUrl}" target="_blank" class="px-3.5 py-2 rounded-xl bg-gray-800 hover:bg-gray-700 text-xs font-semibold text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5 transition">
                            <span>🔗</span> View Run Logs on GitHub
                        </a>
                    `;
                } else {
                    actionContainer.innerHTML = "";
                }
            }

            modal.classList.remove("hidden");
        }

        function closeErrorModal() {
            const modal = document.getElementById("errorModal");
            if (modal) modal.classList.add("hidden");
        }

        function copyErrorDiagnostics() {
            const text = document.getElementById("errorModalDetails").innerText;
            const btn = document.getElementById("copyDiagnosticsBtn");
            navigator.clipboard.writeText(text).then(() => {
                if (btn) {
                    btn.innerHTML = "<span>✅ Copied!</span>";
                    setTimeout(() => { btn.innerHTML = "<span>📋 Copy Log</span>"; }, 2000);
                }
            }).catch(() => {
                alert("Log text ready to copy from the box.");
            });
        }

        function showStatusAlert(type, message, details) {
            const alertBox = document.getElementById("statusAlert");
            if (!alertBox) return;

            if (type === "error") {
                alertBox.className = "mb-6 p-4 rounded-xl border bg-red-500/10 border-red-500/40 text-red-300 flex items-start justify-between gap-4";
                alertBox.innerHTML = `
                    <div class="flex items-start gap-3">
                        <span class="text-xl">⚠️</span>
                        <div>
                            <p class="font-bold text-sm text-red-200">${message}</p>
                            ${details ? `<p class="text-xs text-red-400 font-mono mt-1">${details}</p>` : ''}
                        </div>
                    </div>
                    <button onclick="document.getElementById('statusAlert').classList.add('hidden')" class="text-red-400 hover:text-white text-xs">✕</button>
                `;
            } else if (type === "success") {
                alertBox.className = "mb-6 p-4 rounded-xl border bg-emerald-500/10 border-emerald-500/40 text-emerald-300 flex items-start justify-between gap-4";
                alertBox.innerHTML = `
                    <div class="flex items-start gap-3">
                        <span class="text-xl">✅</span>
                        <div>
                            <p class="font-bold text-sm text-emerald-200">${message}</p>
                            ${details ? `<p class="text-xs text-emerald-400 mt-0.5">${details}</p>` : ''}
                        </div>
                    </div>
                    <button onclick="document.getElementById('statusAlert').classList.add('hidden')" class="text-emerald-400 hover:text-white text-xs">✕</button>
                `;
            }
            alertBox.classList.remove("hidden");
            alertBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }

        // Global unhandled error interception
        window.addEventListener('unhandledrejection', function (event) {
            console.error('Unhandled Promise Rejection:', event.reason);
            showErrorModal(
                "Unhandled Client Exception",
                "An unexpected JavaScript error occurred",
                event.reason ? (event.reason.message || String(event.reason)) : "Unknown client error",
                event.reason && event.reason.stack ? event.reason.stack : "See browser Developer Tools console for full trace."
            );
        });

        window.addEventListener('error', function (event) {
            console.error('Global Error:', event.error || event.message);
            if (event.filename && !event.filename.includes(window.location.host) && !event.filename.includes('localhost')) {
                return;
            }
            showErrorModal(
                "UI Runtime Error",
                "An error occurred in the dashboard script",
                event.message || "Script execution error",
                `${event.filename || ''}:${event.lineno || 0}:${event.colno || 0}\n${(event.error && event.error.stack) || ''}`
            );
        });

        // Publish to Instagram
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
                const data = await res.json().catch(() => ({}));

                if (!res.ok || !data.success) {
                    throw new Error(data.error || data.message || `Server returned HTTP ${res.status}`);
                }

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
                const pBadge = document.getElementById("publishBadge");
                if (pBadge) {
                    pBadge.innerHTML = `
                        <span class="px-3 py-1 rounded-full text-xs font-bold bg-green-500/20 text-green-400 border border-green-500/30 flex items-center gap-1.5">
                            <span>✅</span> Live on Instagram (@arovia360)
                        </span>
                    `;
                }
            } catch (err) {
                showErrorModal(
                    "Instagram Publishing Failed",
                    "Meta Graph API rejected the publish request",
                    err.message || String(err),
                    err.stack || "Failed during Instagram video container creation or media publish.",
                    "1. Verify your Instagram Access Token has not expired (generate a fresh token in Facebook Developer Portal). 2. Ensure the Cloudinary video URL is publicly accessible."
                );
                btn.disabled = false;
                btn.innerHTML = "<span>🚀</span> Retry Publishing to Instagram";
            }
        }

        // Instant Studio: Topic Selection
        function selectTopic(topic, category) {
            document.getElementById('customTopicInput').value = topic;
            document.getElementById('customCategoryInput').value = category;
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        const sampleTopics = [
            "Benefits of drinking warm lemon water every morning",
            "What happens to your blood sugar when you eat white rice?",
            "3 early warning signs of Vitamin D deficiency in adults",
            "Why walking 15 minutes after dinner lowers spike in insulin",
            "The secret reason you feel exhausted even after 8 hours of sleep",
            "How soaking almonds overnight unlocks vital brain enzymes"
        ];
        function pickRandomTopic() {
            const random = sampleTopics[Math.floor(Math.random() * sampleTopics.length)];
            document.getElementById('customTopicInput').value = random;
        }

        const currentVideoUrl = "{{ state.cloudinary_url or '' }}";

        function updateProgressStage(percent, title, msg, activeStep) {
            const banner = document.getElementById("genProgressBanner");
            if (banner) banner.classList.remove("hidden");

            const bar = document.getElementById("progressBar");
            const pct = document.getElementById("progressPercent");
            const titleEl = document.getElementById("progressStepTitle");
            const msgEl = document.getElementById("progressMsg");

            if (bar) bar.style.width = percent + "%";
            if (pct) pct.innerText = percent + "%";
            if (titleEl && title) titleEl.innerText = title;
            if (msgEl && msg) msgEl.innerText = msg;

            for (let i = 1; i <= 5; i++) {
                const pill = document.getElementById("step-pill-" + i);
                if (pill) {
                    if (i <= activeStep) {
                        pill.className = "p-2 rounded-xl bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 flex items-center gap-1.5 transition";
                    } else {
                        pill.className = "p-2 rounded-xl bg-gray-950/60 text-gray-400 border border-gray-800 flex items-center gap-1.5 transition";
                    }
                }
            }
        }

        let progressInterval = null;

        function getErrorTroubleshootingAdvice(errorText) {
            const err = (errorText || "").toLowerCase();
            if (err.includes("gemini") || err.includes("503") || err.includes("resourceexhausted") || err.includes("quota")) {
                return "Gemini API capacity limits hit. Switching to 'gemini-3.5-flash-lite' in .env or waiting 60s before retrying resolves this immediately.";
            }
            if (err.includes("pixabay") || err.includes("footage")) {
                return "Pixabay API quota reached or query returned 0 vertical clips. Verify PIXABAY_API_KEY in .env.";
            }
            if (err.includes("fetch first") || err.includes("rejected") || err.includes("push") || err.includes("git")) {
                return "GitHub concurrency lock or out-of-sync branch during git push. Automatic rebase handles this on retry.";
            }
            if (err.includes("edge-tts") || err.includes("tts") || err.includes("audio")) {
                return "Edge-TTS audio synthesis timed out or network disconnected. Try retrying the generation.";
            }
            if (err.includes("ffmpeg") || err.includes("filter") || err.includes("libass")) {
                return "FFmpeg video assembly failed. Verify libass, subtitle filters, and Telugu fonts are installed.";
            }
            if (err.includes("cloudinary")) {
                return "Cloudinary credentials missing or upload network timeout. Verify CLOUDINARY_URL in .env.";
            }
            return "Check your API credentials in .env, inspect server terminal logs, or retry with another health topic.";
        }

        function handleGenerationFailure(data, reason) {
            if (progressInterval) clearInterval(progressInterval);
            localStorage.removeItem("arovia_generating");
            localStorage.removeItem("arovia_start_time");
            localStorage.removeItem("arovia_initial_url");

            const banner = document.getElementById("genProgressBanner");
            if (banner) {
                banner.className = "mb-8 p-5 rounded-2xl glass-panel border border-red-500/60 bg-gradient-to-r from-red-950/40 to-slate-900/60 shadow-xl transition-all";
            }
            const bar = document.getElementById("progressBar");
            if (bar) bar.className = "h-full bg-gradient-to-r from-red-600 to-rose-400";
            const titleEl = document.getElementById("progressStepTitle");
            if (titleEl) titleEl.innerText = `🚨 Generation Failed: ${data.step || reason || 'Pipeline Error'}`;
            const msgEl = document.getElementById("progressMsg");
            if (msgEl) msgEl.innerText = data.error || data.message || "An exception occurred during generation. See diagnostics below.";

            const advice = getErrorTroubleshootingAdvice((data.error || "") + " " + (data.details || ""));
            showErrorModal(
                `Reel Generation Failed (${data.target === 'github' ? 'Cloud Workflow' : 'Local Engine'})`,
                `Failed during: ${data.step || reason || 'Pipeline Execution'}`,
                data.error || data.message || "Generation pipeline terminated with an error.",
                data.details || data.error || "No technical error trace was captured. Check terminal or GitHub Actions logs.",
                advice,
                data.run_url
            );

            showStatusAlert("error", `Generation failed at step: ${data.step || reason || 'Pipeline Error'}`, data.error || "Inspect diagnostics modal for full error log.");

            const btn = document.getElementById("startGenBtn");
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = "<span>⚡</span> Start Instant Reel Generation";
            }
        }

        function startProgressTracker(initialUrl) {
            let startTime = parseInt(localStorage.getItem("arovia_start_time") || Date.now());
            if (!localStorage.getItem("arovia_start_time")) {
                localStorage.setItem("arovia_start_time", startTime);
            }
            localStorage.setItem("arovia_generating", "true");
            localStorage.setItem("arovia_initial_url", initialUrl || currentVideoUrl);

            switchTab('review');

            // Reset banner to emerald styling if it was previously red
            const banner = document.getElementById("genProgressBanner");
            if (banner) {
                banner.className = "mb-8 p-5 rounded-2xl glass-panel border border-emerald-500/30 bg-gradient-to-r from-emerald-950/20 to-slate-900/40 shadow-xl";
            }
            const bar = document.getElementById("progressBar");
            if (bar) bar.className = "h-full accent-gradient";

            if (progressInterval) clearInterval(progressInterval);

            progressInterval = setInterval(async () => {
                const elapsed = Math.floor((Date.now() - startTime) / 1000);

                // Stage simulation based on real pipeline progression
                if (elapsed < 12) {
                    updateProgressStage(Math.min(20, Math.floor(10 + elapsed)), "💡 Drafting 5-Beat Viral Script...", "Gemini 3.1 Flash Lite is composing hooks & Telugu storytelling arc...", 1);
                } else if (elapsed < 28) {
                    updateProgressStage(Math.min(42, Math.floor(22 + (elapsed - 12) * 1.3)), "🎙️ Synthesizing Native Telugu Audio...", "Edge-TTS is generating authentic native Shruti Telugu voiceover...", 2);
                } else if (elapsed < 50) {
                    updateProgressStage(Math.min(65, Math.floor(45 + (elapsed - 28) * 1.0)), "🎥 Fetching 9:16 Vertical HD Footage...", "Pixabay is fetching high-relevance video scenes for each health beat...", 3);
                } else if (elapsed < 75) {
                    updateProgressStage(Math.min(88, Math.floor(67 + (elapsed - 50) * 0.9)), "✂️ Assembling Video & Burning Subtitles...", "FFmpeg is rendering full-bleed 1080x1920 montage with kinetic popping captions...", 4);
                } else if (elapsed < 100) {
                    updateProgressStage(Math.min(95, Math.floor(89 + (elapsed - 75) * 0.3)), "☁️ Staging Review Stream in Cloud...", "Uploading to Cloudinary and dispatching review email...", 5);
                }

                // Check server status
                if (elapsed % 3 === 0 || elapsed > 35) {
                    try {
                        const res = await fetch("/api/status");
                        const data = await res.json();
                        const initUrl = localStorage.getItem("arovia_initial_url") || currentVideoUrl;

                        // Check for failure from local subprocess or GitHub workflow
                        if (data.status === "failed" || (data.error && !data.running) || (data.step && data.step.startsWith("Failed"))) {
                            handleGenerationFailure(data, data.step);
                            return;
                        }

                        // Check for completion
                        if (data.cloudinary_url && data.cloudinary_url !== initUrl) {
                            clearInterval(progressInterval);
                            updateProgressStage(100, "🎉 Reel Generation Complete!", "New video is ready! Refreshing player...", 5);
                            localStorage.removeItem("arovia_generating");
                            localStorage.removeItem("arovia_start_time");
                            localStorage.removeItem("arovia_initial_url");
                            showStatusAlert("success", "New Reel Generated Successfully!", `Cloudinary stream ready for topic: "${data.topic || 'Health'}"`);
                            setTimeout(() => location.reload(), 1500);
                            return;
                        }
                    } catch (e) {
                        console.error("Status check poll error:", e);
                    }
                }

                if (elapsed > 180) { // Safety timeout
                    clearInterval(progressInterval);
                    localStorage.removeItem("arovia_generating");
                    localStorage.removeItem("arovia_start_time");
                    localStorage.removeItem("arovia_initial_url");
                    handleGenerationFailure({
                        step: "Timeout (180s Exceeded)",
                        error: "Pipeline exceeded maximum wait time of 180 seconds without completing.",
                        details: `Elapsed: ${elapsed}s\nInitial Video: ${localStorage.getItem("arovia_initial_url") || currentVideoUrl}\nCheck server terminal stdout or GitHub Actions runs tab for live status.`
                    }, "Timeout");
                }
            }, 1000);
        }

        // On Page Load: Check if a generation is currently running
        window.addEventListener('DOMContentLoaded', () => {
            if (localStorage.getItem("arovia_generating") === "true") {
                const startTime = parseInt(localStorage.getItem("arovia_start_time") || "0");
                const elapsed = (Date.now() - startTime) / 1000;
                if (elapsed < 180) {
                    startProgressTracker(localStorage.getItem("arovia_initial_url"));
                } else {
                    localStorage.removeItem("arovia_generating");
                }
            }
        });

        // Start Generation
        async function startInstantGeneration() {
            const btn = document.getElementById("startGenBtn");
            const topic = document.getElementById("customTopicInput").value.trim();
            const category = document.getElementById("customCategoryInput").value;
            const runnerEl = document.querySelector('input[name="runnerType"]:checked');
            const runner = runnerEl ? runnerEl.value : 'local';

            btn.disabled = true;
            btn.innerHTML = "<span class='animate-spin'>⏳</span> Starting Engine...";

            try {
                const res = await fetch("/api/generate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ topic, category, runner })
                });
                const data = await res.json().catch(err => {
                    throw new Error("Invalid response from server: " + err.message);
                });

                if (!res.ok || !data.success) {
                    throw new Error(data.message || data.error || `Server returned HTTP ${res.status}`);
                }

                showStatusAlert("success", `Generation Engine Launched (${runner.toUpperCase()})`, topic ? `Topic: "${topic}"` : "Auto-generating trending health topic...");
                startProgressTracker(currentVideoUrl);
            } catch (e) {
                console.error("Start generation error:", e);
                showErrorModal(
                    "Failed to Launch Generation",
                    `Engine dispatch error (${runner})`,
                    e.message || String(e),
                    e.stack || "Failed when calling POST /api/generate",
                    runner === "github"
                        ? "Ensure GITHUB_TOKEN is set with 'repo' and 'workflow' scopes in .env, or GitHub CLI is authenticated."
                        : "Ensure no other local generation is currently running and the server has permissions to execute python scripts."
                );
                showStatusAlert("error", "Failed to start generation engine", e.message || String(e));
            } finally {
                btn.disabled = false;
                btn.innerHTML = "<span>⚡</span> Start Instant Reel Generation";
            }
        }

        // Schedule Functions
        function setPresetTime(time) {
            document.getElementById("customTimeInput").value = time;
        }

        async function saveSchedule() {
            const btn = document.getElementById("saveScheduleBtn");
            const time = document.getElementById("customTimeInput").value;

            if (!time) {
                showStatusAlert("error", "Schedule Validation Error", "Please select a valid time (e.g. 17:30 IST).");
                return;
            }

            btn.disabled = true;
            btn.innerText = "⏳ Saving and syncing with GitHub...";

            try {
                const res = await fetch("/api/schedule", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ time_ist: time, enabled: true })
                });
                const data = await res.json().catch(err => {
                    throw new Error("Invalid response from server: " + err.message);
                });
                if (!res.ok || !data.success) {
                    throw new Error(data.message || data.error || `Server returned HTTP ${res.status}`);
                }

                document.getElementById("currentScheduleLabel").innerText = data.schedule.label;
                document.getElementById("currentCron").innerText = data.schedule.cron;
                showStatusAlert("success", "Schedule Updated & Synced", `Daily reel trigger set to ${data.schedule.label} (Cron: ${data.schedule.cron})`);
            } catch (e) {
                console.error("Schedule error:", e);
                showErrorModal(
                    "Schedule Synchronization Failed",
                    "Could not update cron schedule",
                    e.message || String(e),
                    e.stack || "Failed when calling POST /api/schedule",
                    "Verify git permissions, ensure .github/workflows/daily_reel.yml exists, or inspect server error logs."
                );
                showStatusAlert("error", "Failed to update schedule", e.message || String(e));
            } finally {
                btn.disabled = false;
                btn.innerText = "💾 Save & Synchronize Schedule with GitHub Actions";
            }
        }

        // Feedback Functions
        async function addFeedback() {
            const input = document.getElementById("newFeedbackInput");
            const text = input.value.trim();
            if (!text) {
                showStatusAlert("error", "Empty Rule", "Please write a specific rule or topic guideline before saving.");
                return;
            }

            const btn = document.getElementById("addFeedbackBtn");
            btn.disabled = true;

            try {
                const res = await fetch("/api/feedback", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ action: "add", text })
                });
                const data = await res.json().catch(err => {
                    throw new Error("Invalid response from server: " + err.message);
                });
                if (!res.ok || !data.success) {
                    throw new Error(data.message || data.error || `Server returned HTTP ${res.status}`);
                }

                input.value = "";
                renderFeedbackList(data.items);
                showStatusAlert("success", "AI Instruction Saved", `Added rule: "${text}"`);
            } catch (e) {
                console.error("Add feedback error:", e);
                showErrorModal(
                    "Failed to Add Instruction",
                    "Could not update feedback list",
                    e.message || String(e),
                    e.stack || "Failed when calling POST /api/feedback",
                    "Check write permissions on config/feedback.json or server console logs."
                );
                showStatusAlert("error", "Failed to save AI instruction", e.message || String(e));
            } finally {
                btn.disabled = false;
            }
        }

        async function deleteFeedback(index) {
            if (!confirm("Remove this AI instruction?")) return;
            try {
                const res = await fetch("/api/feedback", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ action: "delete", index })
                });
                const data = await res.json().catch(err => {
                    throw new Error("Invalid response from server: " + err.message);
                });
                if (!res.ok || !data.success) {
                    throw new Error(data.message || data.error || `Server returned HTTP ${res.status}`);
                }
                renderFeedbackList(data.items);
                showStatusAlert("success", "Instruction Removed", "The AI guideline has been removed from future generations.");
            } catch (e) {
                console.error("Delete feedback error:", e);
                showErrorModal(
                    "Failed to Delete Instruction",
                    "Could not remove feedback item",
                    e.message || String(e),
                    e.stack || "Failed when calling POST /api/feedback (delete)",
                    "Check write permissions on config/feedback.json."
                );
                showStatusAlert("error", "Failed to delete instruction", e.message || String(e));
            }
        }

        function renderFeedbackList(items) {
            document.getElementById("feedbackCountBadge").innerText = items.length + " Rules Active";
            const container = document.getElementById("feedbackList");
            container.innerHTML = items.map((item, i) => `
                <div class="p-3.5 rounded-xl bg-gray-950/50 border border-gray-800/80 flex items-start justify-between gap-3 group hover:border-gray-700 transition">
                    <div class="flex items-start gap-3">
                        <span class="w-5 h-5 rounded-full bg-emerald-500/10 text-emerald-400 font-bold text-xs flex items-center justify-center shrink-0 mt-0.5">
                            ${i + 1}
                        </span>
                        <p class="text-xs text-gray-300 leading-relaxed">${item}</p>
                    </div>
                    <button onclick="deleteFeedback(${i})" class="text-gray-500 hover:text-red-400 text-xs px-2 py-1 rounded transition opacity-70 group-hover:opacity-100" title="Delete Rule">
                        🗑️
                    </button>
                </div>
            `).join("");
        }

        // API Usage Monitor
        async function refreshUsage() {
            const btn = document.getElementById("refreshUsageBtn");
            btn.innerHTML = "<span class='animate-spin'>🔄</span> Fetching Live...";

            try {
                const res = await fetch("/api/usage");
                const data = await res.json().catch(err => {
                    throw new Error("Invalid response from server: " + err.message);
                });
                if (!res.ok) {
                    throw new Error(data.message || `Server returned HTTP ${res.status}`);
                }

                // Gemini
                const gBadge = document.getElementById("geminiStatusBadge");
                if (data.gemini && data.gemini.status === "healthy") {
                    gBadge.className = "text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
                    gBadge.innerText = "Online";
                    document.getElementById("geminiMsg").innerText = data.gemini.message;
                } else {
                    gBadge.className = "text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-red-500/20 text-red-400 border border-red-500/30";
                    gBadge.innerText = "Error";
                    document.getElementById("geminiMsg").innerText = data.gemini ? data.gemini.message : "Service unreachable";
                }

                // Pixabay
                const pBadge = document.getElementById("pixabayStatusBadge");
                if (data.pixabay && data.pixabay.status === "healthy") {
                    pBadge.className = "text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
                    pBadge.innerText = "Online";
                    document.getElementById("pixabayRemaining").innerText = data.pixabay.remaining + " / " + data.pixabay.limit;
                    document.getElementById("pixabayMsg").innerText = data.pixabay.message;
                } else {
                    pBadge.className = "text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-red-500/20 text-red-400 border border-red-500/30";
                    pBadge.innerText = "Error";
                    document.getElementById("pixabayMsg").innerText = data.pixabay ? data.pixabay.message : "Service unreachable";
                }

                // Cloudinary
                const cBadge = document.getElementById("cloudinaryStatusBadge");
                if (data.cloudinary && data.cloudinary.status === "healthy") {
                    cBadge.className = "text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
                    cBadge.innerText = "Connected";
                    document.getElementById("cloudinaryStorage").innerText = data.cloudinary.storage_mb + " MB (" + data.cloudinary.credits_percent + "% Credits Used)";
                    document.getElementById("cloudinaryMsg").innerText = data.cloudinary.message;
                } else {
                    cBadge.className = "text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-red-500/20 text-red-400 border border-red-500/30";
                    cBadge.innerText = "Error";
                    document.getElementById("cloudinaryMsg").innerText = data.cloudinary ? data.cloudinary.message : "Connection failed";
                }

                // Instagram
                const igBadge = document.getElementById("instagramStatusBadge");
                if (data.instagram && data.instagram.status === "healthy") {
                    igBadge.className = "text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
                    igBadge.innerText = "Active";
                    document.getElementById("instagramMsg").innerText = "Token Valid | Follower count: " + data.instagram.followers;
                } else if (data.instagram && data.instagram.status === "token_expired") {
                    igBadge.className = "text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30";
                    igBadge.innerText = "Token Expired";
                    document.getElementById("instagramMsg").innerText = "⚠️ Session token expired. Click 'Update Access Token' to paste fresh token.";
                } else {
                    igBadge.className = "text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-red-500/20 text-red-400 border border-red-500/30";
                    igBadge.innerText = "Disconnected";
                    document.getElementById("instagramMsg").innerText = (data.instagram ? data.instagram.message : "Error connecting");
                }
            } catch (e) {
                console.error("Usage fetch err:", e);
                showStatusAlert("error", "API Status Check Error", e.message || String(e));
            } finally {
                btn.innerHTML = "<span>🔄</span> Refresh Stats";
            }
        }

        function toggleTokenModal() {
            const box = document.getElementById("tokenUpdateBox");
            box.classList.toggle("hidden");
        }

        async function saveNewToken() {
            const token = document.getElementById("newTokenInput").value.trim();
            if (!token) {
                showStatusAlert("error", "Empty Token Input", "Please paste your Meta Graph API User Access Token.");
                return;
            }

            try {
                const res = await fetch("/api/settings/token", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ token })
                });
                const data = await res.json().catch(err => {
                    throw new Error("Invalid response from server: " + err.message);
                });
                if (!res.ok || !data.success) {
                    throw new Error(data.message || data.error || `Server returned HTTP ${res.status}`);
                }

                showStatusAlert("success", "Instagram Token Verified & Updated!", "Your new access token was saved to .env and verified with Instagram Graph API.");
                toggleTokenModal();
                refreshUsage();
            } catch (e) {
                console.error("Token save error:", e);
                showErrorModal(
                    "Instagram Token Validation Failed",
                    "Meta Graph API rejected the token",
                    e.message || String(e),
                    e.stack || "Failed when calling POST /api/settings/token",
                    "1. Verify that the token was generated for user @arovia360. 2. Ensure permissions 'instagram_basic', 'instagram_content_publish', and 'pages_show_list' are granted in the Meta Graph API Explorer. 3. Make sure to generate a Long-Lived Token if possible."
                );
                showStatusAlert("error", "Failed to update Instagram token", e.message || String(e));
            }
        }
    </script>
</body>
</html>
"""

# -------------------------------------------------------------
# Routes
# -------------------------------------------------------------
@app.route("/")
def index():
    state = get_current_state()
    feedback_items = get_feedback_items()
    schedule = get_schedule()
    topics_preview = []
    if TOPICS_FILE.exists():
        try:
            with open(TOPICS_FILE, "r", encoding="utf-8") as f:
                topics_preview = json.load(f)[:8]
        except Exception:
            pass

    video_path = Path(state.get("video_path", "")) if state.get("video_path") else None
    video_exists = bool((video_path and video_path.exists()) or state.get("cloudinary_url"))

    return render_template_string(
        HTML_TEMPLATE,
        state=state,
        video_exists=video_exists,
        feedback_items=feedback_items,
        schedule=schedule,
        topics_preview=topics_preview
    )

@app.route("/favicon.ico")
def favicon():
    return ('', 204)

@app.route("/video")
def serve_video():
    state = get_current_state()
    video_path = Path(state.get("video_path", "")) if state.get("video_path") else None
    if video_path and video_path.exists():
        return send_file(video_path, mimetype="video/mp4")
    elif state.get("cloudinary_url"):
        return redirect(state["cloudinary_url"])
    return "Video not found", 404

@app.route("/api/publish", methods=["POST"])
def api_publish():
    state = get_current_state()
    public_url = state.get("cloudinary_url")

    if not public_url:
        video_path_str = state.get("video_path")
        if not video_path_str or not Path(video_path_str).exists():
            return jsonify({"success": False, "error": "No video found to publish. Please generate a video first."}), 400
        try:
            uploader = MediaUploader()
            public_url = uploader.upload_video(Path(video_path_str))
            state["cloudinary_url"] = public_url
        except Exception as e:
            return jsonify({"success": False, "error": f"Cloudinary upload failed: {e}"}), 500

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
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return jsonify({"success": True, "post_id": post_id})
    except Exception as e:
        logger.error(f"Publishing failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/generate", methods=["POST"])
def api_generate():
    global generation_status
    if generation_status["running"]:
        return jsonify({"success": False, "message": "Generation already running!"}), 400

    req_data = request.get_json(silent=True) or {}
    topic = req_data.get("topic")
    category = req_data.get("category")
    runner = req_data.get("runner", "local")

    if runner == "github":
        # Dispatch to GitHub Actions workflow
        gh_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if gh_token:
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"Bearer {gh_token}"
            }
            url = "https://api.github.com/repos/mahajanpc/automation/actions/workflows/daily_reel.yml/dispatches"
            payload = {
                "ref": "main",
                "inputs": {
                    "topic": topic or "",
                    "mode": "review"
                }
            }
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=10)
                if r.status_code in (200, 204):
                    return jsonify({"success": True, "runner": "github", "message": "Dispatched to GitHub Actions!"})
                else:
                    return jsonify({"success": False, "message": f"GitHub API error ({r.status_code}): {r.text}"}), 500
            except Exception as e:
                return jsonify({"success": False, "message": f"GitHub dispatch exception: {e}"}), 500

        cmd = ["gh", "workflow", "run", "daily_reel.yml"]
        if topic:
            cmd.extend(["-f", f"topic={topic}"])
        try:
            res = subprocess.run(cmd, cwd=str(Config.ROOT_DIR), capture_output=True, text=True)
            if res.returncode == 0:
                return jsonify({"success": True, "runner": "github", "message": "Dispatched to GitHub Actions!"})
            else:
                return jsonify({"success": False, "message": f"GitHub dispatch error: {res.stderr}"}), 500
        except Exception as e:
            return jsonify({"success": False, "message": f"Execution error: {e}"}), 500
    else:
        t = threading.Thread(target=run_local_generation, args=(topic, category))
        t.daemon = True
        t.start()
        return jsonify({"success": True, "runner": "local", "message": "Generation pipeline launched!"})

@app.route("/api/status")
def api_status():
    global generation_status
    state = get_current_state()
    res = dict(generation_status)

    # Check GitHub Actions runs if token is set or gh CLI is present
    gh_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if gh_token:
        try:
            headers = {"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github.v3+json"}
            url = "https://api.github.com/repos/mahajanpc/automation/actions/runs?event=workflow_dispatch&per_page=1"
            r = requests.get(url, headers=headers, timeout=3)
            if r.status_code == 200:
                runs = r.json().get("workflow_runs", [])
                if runs:
                    latest = runs[0]
                    r_status = latest.get("status")
                    r_conclusion = latest.get("conclusion")
                    r_id = latest.get("id")
                    r_url = latest.get("html_url")
                    res["run_id"] = r_id
                    res["run_url"] = r_url

                    if r_status in ("queued", "in_progress"):
                        res["running"] = True
                        res["status"] = "running"
                        res["target"] = "github"
                        res["step"] = "Cloud GitHub Runner Active"
                        res["message"] = f"Workflow run #{r_id} is executing in GitHub Actions..."
                    elif r_status == "completed":
                        if r_conclusion == "failure":
                            failed_step = "Execution Step"
                            try:
                                jobs_r = requests.get(
                                    f"https://api.github.com/repos/mahajanpc/automation/actions/runs/{r_id}/jobs",
                                    headers=headers,
                                    timeout=3
                                )
                                if jobs_r.status_code == 200:
                                    for j in jobs_r.json().get("jobs", []):
                                        for s in j.get("steps", []):
                                            if s.get("conclusion") == "failure":
                                                failed_step = s.get("name", failed_step)
                                                break
                            except Exception:
                                pass
                            res["running"] = False
                            res["status"] = "failed"
                            res["step"] = f"Failed at {failed_step}"
                            res["error"] = f"GitHub Actions workflow #{r_id} failed at step: '{failed_step}'"
                            res["details"] = f"Job Step: {failed_step}\nWorkflow Run URL: {r_url}\nCheck the GitHub Actions tab for complete step logs."
                        elif r_conclusion == "cancelled":
                            res["running"] = False
                            res["status"] = "failed"
                            res["step"] = "Workflow Cancelled"
                            res["error"] = f"GitHub Actions workflow run #{r_id} was cancelled."
                            res["details"] = f"Workflow Run URL: {r_url}"
                        elif r_conclusion == "success":
                            if res.get("status") == "running" and res.get("target") == "github":
                                res["running"] = False
                                res["status"] = "completed"
                                res["step"] = "Complete"
                                res["message"] = "Cloud generation finished successfully!"
        except Exception as e:
            logger.debug(f"GitHub run check error: {e}")
    else:
        # Fallback to local gh CLI if present
        try:
            gh_res = subprocess.run(
                ["gh", "run", "list", "--json", "databaseId,status,conclusion,url", "-L", "1"],
                capture_output=True, text=True, timeout=2
            )
            if gh_res.returncode == 0:
                gh_runs = json.loads(gh_res.stdout)
                if gh_runs:
                    latest = gh_runs[0]
                    r_status = latest.get("status")
                    r_conclusion = latest.get("conclusion")
                    r_id = latest.get("databaseId")
                    r_url = latest.get("url")
                    res["run_id"] = r_id
                    res["run_url"] = r_url

                    if r_status in ("queued", "in_progress"):
                        res["running"] = True
                        res["status"] = "running"
                        res["target"] = "github"
                        res["step"] = "Cloud GitHub Runner Active"
                    elif r_status == "completed" and r_conclusion == "failure" and res.get("running"):
                        res["running"] = False
                        res["status"] = "failed"
                        res["step"] = "Cloud Workflow Failed"
                        res["error"] = f"GitHub Actions run #{r_id} failed. See logs at {r_url}"
                        res["details"] = f"Run URL: {r_url}"
        except Exception:
            pass

    res["cloudinary_url"] = state.get("cloudinary_url")
    res["topic"] = state.get("topic")
    return jsonify(res)

@app.route("/api/schedule", methods=["GET", "POST"])
def api_schedule():
    if request.method == "GET":
        return jsonify(get_schedule())

    data = request.get_json(silent=True) or {}
    time_ist = data.get("time_ist", "17:30")
    enabled = data.get("enabled", True)

    try:
        parts = time_ist.split(":")
        h, m = int(parts[0]), int(parts[1])
        new_cron, utc_time = ist_to_utc_cron(h, m)

        # Convert to 12-hour label
        period = "AM" if h < 12 else "PM"
        h12 = h % 12
        if h12 == 0:
            h12 = 12
        label = f"Daily at {h12}:{m:02d} {period} IST ({utc_time} UTC)"

        schedule_data = {
            "cron": new_cron,
            "time_ist": time_ist,
            "time_utc": utc_time,
            "timezone": "Asia/Kolkata",
            "label": label,
            "enabled": enabled,
            "last_updated": datetime.datetime.now().isoformat()
        }

        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(schedule_data, f, indent=2)

        # Update workflow file directly
        update_workflow_cron(new_cron)

        # Sync with Git repository
        try:
            subprocess.run(["git", "add", str(SCHEDULE_FILE), str(WORKFLOW_FILE)], cwd=str(Config.ROOT_DIR), check=False)
            subprocess.run(["git", "commit", "-m", f"Update automation schedule to {label}"], cwd=str(Config.ROOT_DIR), check=False)
            subprocess.run(["git", "push", "origin", "main"], cwd=str(Config.ROOT_DIR), check=False)
        except Exception as e:
            logger.warning(f"Git push schedule sync warning: {e}")

        return jsonify({"success": True, "schedule": schedule_data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400

@app.route("/api/feedback", methods=["GET", "POST"])
def api_feedback():
    items = get_feedback_items()

    if request.method == "GET":
        return jsonify({"items": items})

    data = request.get_json(silent=True) or {}
    action = data.get("action")

    if action == "add":
        text = data.get("text", "").strip()
        if text:
            items.append(text)
            save_feedback_items(items)
        return jsonify({"success": True, "items": items})

    elif action == "delete":
        idx = data.get("index")
        if isinstance(idx, int) and 0 <= idx < len(items):
            items.pop(idx)
            save_feedback_items(items)
        return jsonify({"success": True, "items": items})

    elif action == "clear":
        save_feedback_items([])
        return jsonify({"success": True, "items": []})

    return jsonify({"success": False, "message": "Invalid action"}), 400

@app.route("/api/usage")
def api_usage():
    data = {}

    # 1. Google Gemini AI
    try:
        from google import genai
        client = genai.Client(api_key=Config.GEMINI_API_KEY)
        client.models.generate_content(model=Config.GEMINI_MODEL, contents="ping")
        data["gemini"] = {
            "status": "healthy",
            "model": Config.GEMINI_MODEL,
            "plan": "Free Tier (15 RPM / 1M TPM / 1500 RPD)",
            "message": "Connected and operating normally"
        }
    except Exception as e:
        data["gemini"] = {"status": "error", "message": str(e)}

    # 2. Pixabay HD Video API
    pix_key = Config.PIXABAY_API_KEY
    try:
        r = requests.get(f"https://pixabay.com/api/videos/?key={pix_key}&q=health&per_page=3", timeout=5)
        limit = r.headers.get("X-RateLimit-Limit", "100")
        remaining = r.headers.get("X-RateLimit-Remaining", "99")
        reset = r.headers.get("X-RateLimit-Reset", "60")
        data["pixabay"] = {
            "status": "healthy",
            "limit": limit,
            "remaining": remaining,
            "reset_seconds": reset,
            "message": f"{remaining}/{limit} requests available in current rate window"
        }
    except Exception as e:
        data["pixabay"] = {"status": "error", "message": str(e)}

    # 3. Cloudinary Video Storage
    try:
        c_usage = cloudinary.api.usage()
        credits_info = c_usage.get("credits", {})
        storage_info = c_usage.get("storage", {})
        bytes_used = storage_info.get("usage", 0)
        mb_used = round(bytes_used / (1024 * 1024), 2)
        data["cloudinary"] = {
            "status": "healthy",
            "plan": c_usage.get("plan", "Free"),
            "credits_percent": credits_info.get("used_percent", 0.0),
            "storage_mb": mb_used,
            "message": f"{mb_used} MB used ({credits_info.get('used_percent', 0.0)}% of 25 monthly free credits)"
        }
    except Exception as e:
        data["cloudinary"] = {"status": "error", "message": str(e)}

    # 4. Instagram Graph API
    ig_id = Config.INSTAGRAM_ACCOUNT_ID
    token = Config.IG_ACCESS_TOKEN
    try:
        r = requests.get(
            f"https://graph.facebook.com/v21.0/{ig_id}?fields=username,media_count,followers_count,name&access_token={token}",
            timeout=5
        )
        res = r.json()
        if "error" in res:
            err = res["error"]
            data["instagram"] = {
                "status": "token_expired" if err.get("code") == 190 else "error",
                "message": err.get("message"),
                "account_id": ig_id
            }
        else:
            data["instagram"] = {
                "status": "healthy",
                "username": res.get("username", "arovia360"),
                "followers": res.get("followers_count", 0),
                "media_count": res.get("media_count", 0),
                "message": "Token active & authorized"
            }
    except Exception as e:
        data["instagram"] = {"status": "error", "message": str(e)}

    return jsonify(data)

@app.route("/api/settings/token", methods=["POST"])
def api_update_token():
    data = request.get_json(silent=True) or {}
    token = data.get("token", "").strip()
    if not token:
        return jsonify({"success": False, "message": "Token is empty"}), 400

    # Validate against Instagram Graph API
    ig_id = Config.INSTAGRAM_ACCOUNT_ID
    try:
        r = requests.get(
            f"https://graph.facebook.com/v21.0/{ig_id}?fields=username&access_token={token}",
            timeout=5
        )
        res = r.json()
        if "error" in res:
            return jsonify({"success": False, "message": res["error"].get("message")}), 400

        # Update .env
        update_env_variable("IG_ACCESS_TOKEN", token)
        Config.IG_ACCESS_TOKEN = token
        return jsonify({"success": True, "username": res.get("username")})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
