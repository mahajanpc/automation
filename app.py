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
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            logger.warning(f"Error reading state file: {e}")

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

    # If running on Vercel (where local video_path doesn't exist) or cloudinary_url is not set,
    # pull latest video stream from Cloudinary
    local_path = Path(state.get("video_path", "")) if state.get("video_path") else None
    if not local_path or not local_path.exists() or not state.get("cloudinary_url"):
        if Config.is_valid_key(Config.CLOUDINARY_URL):
            try:
                res = cloudinary.api.resources(
                    resource_type="video",
                    type="upload",
                    prefix="instagram_automation",
                    max_results=1,
                    direction="desc"
                )
                resources = res.get("resources", [])
                if resources:
                    latest = resources[0]
                    state["cloudinary_url"] = latest.get("secure_url")
                    if not state.get("video_filename"):
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
    "progress": 0,
    "step": "Idle",
    "message": "Ready to generate",
    "target": "local",
    "topic": None
}

def run_local_generation(topic=None, category=None):
    global generation_status
    with generation_lock:
        generation_status.update({
            "running": True,
            "progress": 10,
            "step": "Initializing Pipeline",
            "message": "Starting generation pipeline...",
            "target": "local",
            "topic": topic
        })

        cmd = [str(Config.ROOT_DIR / ".venv" / "bin" / "python3"), "main.py", "--mode", "review"]
        if topic:
            cmd.extend(["--topic", topic])
        if category:
            cmd.extend(["--category", category])

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
                    "progress": 100,
                    "step": "Complete",
                    "message": "Reel successfully generated and ready for review!"
                })
            else:
                generation_status.update({
                    "running": False,
                    "progress": 0,
                    "step": "Failed",
                    "message": f"Generation exited with error code {proc.returncode}"
                })
        except Exception as e:
            generation_status.update({
                "running": False,
                "progress": 0,
                "step": "Error",
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

        <!-- Global Live Generation Progress Banner (Visible when generation running) -->
        <div id="genProgressBanner" class="hidden mb-6 glass-panel p-5 rounded-2xl border-emerald-500/30">
            <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2.5">
                    <div class="w-3 h-3 rounded-full bg-emerald-400 animate-ping"></div>
                    <h3 class="font-bold text-sm text-white" id="progressStepTitle">Generating Reel...</h3>
                </div>
                <span class="text-xs font-mono font-bold text-emerald-400" id="progressPercent">0%</span>
            </div>
            <p class="text-xs text-gray-400 mb-3" id="progressMsg">Pipeline is running...</p>
            <div class="w-full bg-gray-800 rounded-full h-2.5 overflow-hidden">
                <div id="progressBar" class="accent-gradient h-2.5 rounded-full transition-all duration-300" style="width: 0%"></div>
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
                                <source src="/video?v={{ state.created_at }}" type="video/mp4">
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
                            <span>✅</span> Live on Instagram (@arovia360)
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
                btn.innerHTML = "<span>🚀</span> 1-Click Publish Live to Instagram (@arovia360)";
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

        // Start Generation
        async function startInstantGeneration() {
            const btn = document.getElementById("startGenBtn");
            const topic = document.getElementById("customTopicInput").value.trim();
            const category = document.getElementById("customCategoryInput").value;
            const runner = document.querySelector('input[name="runnerType"]:checked').value;

            btn.disabled = true;
            btn.innerHTML = "<span class='animate-spin'>⏳</span> Starting Engine...";

            try {
                const res = await fetch("/api/generate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ topic, category, runner })
                });
                const data = await res.json();

                if (data.success) {
                    switchTab('review');
                    showProgressBanner();
                    btn.disabled = false;
                    btn.innerHTML = "<span>⚡</span> Start Instant Reel Generation";

                    if (runner === "github") {
                        document.getElementById("progressStepTitle").innerText = "☁️ GitHub Cloud Runner Active";
                        document.getElementById("progressMsg").innerText = "Rendering 1080x1920 video with FFmpeg, burning Telugu subtitles & uploading to Cloudinary... (Takes ~60-90s)";
                        document.getElementById("progressBar").style.width = "45%";
                        document.getElementById("progressPercent").innerText = "Rendering";
                        pollCloudinaryForNewVideo();
                    } else {
                        pollGenerationStatus();
                    }
                } else {
                    alert(data.message || "Failed to start generation.");
                    btn.disabled = false;
                    btn.innerHTML = "<span>⚡</span> Start Instant Reel Generation";
                }
            } catch (e) {
                alert("Network error: " + e);
                btn.disabled = false;
                btn.innerHTML = "<span>⚡</span> Start Instant Reel Generation";
            }
        }

        function showProgressBanner() {
            document.getElementById("genProgressBanner").classList.remove("hidden");
        }

        function pollCloudinaryForNewVideo() {
            let initialUrl = "{{ state.cloudinary_url or '' }}";
            let attempts = 0;
            const interval = setInterval(async () => {
                attempts++;
                try {
                    const res = await fetch("/api/status");
                    const data = await res.json();
                    if (data.cloudinary_url && data.cloudinary_url !== initialUrl) {
                        clearInterval(interval);
                        document.getElementById("progressBar").style.width = "100%";
                        document.getElementById("progressPercent").innerText = "100%";
                        document.getElementById("progressStepTitle").innerText = "🎉 Video Ready!";
                        document.getElementById("progressMsg").innerText = "Reel rendered and uploaded to Cloudinary! Refreshing player...";
                        setTimeout(() => location.reload(), 1500);
                        return;
                    }
                } catch (e) {
                    console.error("Poll err:", e);
                }
                if (attempts >= 25) {
                    clearInterval(interval);
                    location.reload();
                }
            }, 5000);
        }

        function pollGenerationStatus() {
            const interval = setInterval(async () => {
                try {
                    const res = await fetch("/api/status");
                    const data = await res.json();

                    if (data.running) {
                        showProgressBanner();
                        document.getElementById("progressPercent").innerText = data.progress + "%";
                        document.getElementById("progressBar").style.width = data.progress + "%";
                        document.getElementById("progressStepTitle").innerText = data.step || "Generating...";
                        document.getElementById("progressMsg").innerText = data.message || "Working...";
                    } else {
                        clearInterval(interval);
                        document.getElementById("progressBar").style.width = "100%";
                        document.getElementById("progressPercent").innerText = "100%";
                        setTimeout(() => {
                            location.reload();
                        }, 1200);
                    }
                } catch (e) {
                    console.error("Status poll err:", e);
                }
            }, 2500);
        }

        // Schedule Functions
        function setPresetTime(time) {
            document.getElementById("customTimeInput").value = time;
        }

        async function saveSchedule() {
            const btn = document.getElementById("saveScheduleBtn");
            const time = document.getElementById("customTimeInput").value;

            if (!time) {
                alert("Please select a valid time.");
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
                const data = await res.json();
                if (data.success) {
                    document.getElementById("currentScheduleLabel").innerText = data.schedule.label;
                    document.getElementById("currentCron").innerText = data.schedule.cron;
                    alert("✅ Schedule updated and synchronized with GitHub Actions workflow!");
                } else {
                    alert("Error: " + data.message);
                }
            } catch (e) {
                alert("Network error: " + e);
            } finally {
                btn.disabled = false;
                btn.innerText = "💾 Save & Synchronize Schedule with GitHub Actions";
            }
        }

        // Feedback Functions
        async function addFeedback() {
            const input = document.getElementById("newFeedbackInput");
            const text = input.value.trim();
            if (!text) return;

            const btn = document.getElementById("addFeedbackBtn");
            btn.disabled = true;

            try {
                const res = await fetch("/api/feedback", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ action: "add", text })
                });
                const data = await res.json();
                if (data.success) {
                    input.value = "";
                    renderFeedbackList(data.items);
                } else {
                    alert("Error adding feedback: " + data.message);
                }
            } catch (e) {
                alert("Network error: " + e);
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
                const data = await res.json();
                if (data.success) {
                    renderFeedbackList(data.items);
                }
            } catch (e) {
                alert("Error deleting: " + e);
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
                const data = await res.json();

                // Gemini
                const gBadge = document.getElementById("geminiStatusBadge");
                if (data.gemini && data.gemini.status === "healthy") {
                    gBadge.className = "text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
                    gBadge.innerText = "Online";
                    document.getElementById("geminiMsg").innerText = data.gemini.message;
                } else {
                    gBadge.className = "text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-red-500/20 text-red-400 border border-red-500/30";
                    gBadge.innerText = "Error";
                    document.getElementById("geminiMsg").innerText = data.gemini.message;
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
                alert("Please paste a token.");
                return;
            }

            try {
                const res = await fetch("/api/settings/token", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ token })
                });
                const data = await res.json();
                if (data.success) {
                    alert("✅ Token successfully verified and updated!");
                    toggleTokenModal();
                    refreshUsage();
                } else {
                    alert("❌ Token validation failed: " + data.message);
                }
            } catch (e) {
                alert("Network error: " + e);
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
        client.models.generate_content(model="gemini-3.1-flash-lite", contents="ping")
        data["gemini"] = {
            "status": "healthy",
            "model": "gemini-3.1-flash-lite",
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
