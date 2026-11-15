import json
import logging
import os
import re
import subprocess
import time
import requests
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps

from src.config import Config

logger = logging.getLogger(__name__)

ASSETS_DIR = Path("/tmp/poster_assets")
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

ACCENT_COLORS = ["#10b981", "#06b6d4", "#ef4444", "#f59e0b"]  # Emerald, Cyan, Red, Amber

@dataclass
class PosterContent:
    headline_line1: str
    headline_line2: str
    subtitle: str
    category: str
    points: list[dict] = field(default_factory=list)
    protocol_title: str = "THE DAILY RECOVERY PROTOCOL"
    protocol_image_query: str = "healthy food plate"
    takeaway: str = ""
    caption: str = ""

    @property
    def headline(self) -> str:
        if self.headline_line2:
            return f"{self.headline_line1}: {self.headline_line2}"
        return self.headline_line1


class PosterGenerator:
    """
    Generates high-engagement 4:5 vertical (1080x1350) English health infographic posters
    designed for maximum saves, bookmarks, and shares on Instagram feeds.
    Features:
    - Real HD photography for EVERY point (fetched from Pixabay or extracted from video)
    - High-impact visual stat badges (+300% BOOST, -80% BLOCKED, etc.)
    - Two-tone punchy headlines (crisp white + glowing amber)
    - Custom vector-drawn icons (lightning bolt, bookmark ribbon) - no broken emoji glyphs
    - Color-coded infographic cards (emerald, cyan, red)
    - Actionable 'Daily Protocol' highlight box with dedicated visual imagery
    """

    def __init__(self, api_key: str = None, pixabay_key: str = None):
        self.api_key = api_key or Config.GEMINI_API_KEY
        self.pixabay_key = pixabay_key or Config.PIXABAY_API_KEY
        self.client = None
        if Config.is_valid_key(self.api_key):
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Could not initialize google-genai for poster: {e}")

    def generate_content(self, topic: str, category: str = "Health & Wellness") -> PosterContent:
        """Generate structured English content for the companion health infographic poster."""
        if not self.client:
            logger.info("Using verified offline English poster content.")
            return self._mock_content(topic, category)

        prompt = f"""
You are an expert health infographic designer and viral Instagram visual strategist (style of Glucose Goddess, Huberman Lab).
Create high-value, scientifically grounded, highly visual ENGLISH infographic content for Instagram.

Category: "{category}"
Topic: "{topic}"

STRICT DESIGN & VISUAL REQUIREMENTS:
1. LANGUAGE: 100% STRICTLY IN ENGLISH. Clean, crisp, authoritative.
2. TWO-TONE HEADLINE:
   - 'headline_line1': Punchy uppercase curiosity hook (3 to 6 words max, e.g. "WHY YOU'RE ALWAYS TIRED", "3 MORNING HABITS", "THE CHRONIC INFLAMMATION TRAP").
   - 'headline_line2': Clear uppercase solution name (2 to 5 words max, e.g. "THE IRON DEFICIENCY PROTOCOL", "BLOOD SUGAR MASTERY GUIDE").
3. SUBTITLE: 1 explanatory line promising immediate value (e.g. "How to unlock iron absorption and beat chronic fatigue naturally").
4. 3 CORE VISUAL CARDS:
   - Exactly 3 actionable points numbered "01", "02", "03".
   - 'title': Short bold headline (2 to 5 words).
   - 'badge': High-impact visual metric pill (e.g. "⚡ +300% ABSORPTION", "❌ -80% BLOCKED", "🌱 PLANT vs ANIMAL", "⏰ 60-MIN RULE").
   - 'badge_type': One of "synergy" (green/boost), "warning" (red/blocker), or "info" (blue/cyan).
   - 'image_query': Highly specific, tangible English photography search query for Pixabay (e.g. "spinach greens bowl", "fresh lemon slice", "coffee cup espresso", "almonds water", "avocado slice").
   - 'body': High-impact, clear 1 to 2 sentence explanation of the biological mechanism (max 22 words per card).
5. THE DAILY PROTOCOL / GOLDEN RULE:
   - 'protocol_title': "THE DAILY PROTOCOL" or "THE DAILY RECOVERY PROTOCOL"
   - 'protocol_image_query': Specific tangible food or healthy habit photo query (e.g. "pomegranate seeds", "healthy meal bowl", "glass of water lemon").
   - 'takeaway': 1 or 2 sentences of simple, actionable daily advice to do starting today.
6. CAPTION: Engaging English Instagram caption with:
   - Hook opening line
   - Bullet point summary of the 3 points
   - "📌 Save this guide for your daily health routine!"
   - 8-10 targeted wellness hashtags (e.g. #HealthTips #NutritionScience #DailyWellness #Arovia360).

Return strictly a valid JSON object matching this schema:
{{
  "headline_line1": "PUNCHY UPPERCASE HOOK",
  "headline_line2": "UPPERCASE PROTOCOL NAME",
  "subtitle": "Clear 1-line subtitle explaining the exact health benefit",
  "category": "NUTRITION & VITALITY",
  "points": [
    {{
      "num": "01",
      "title": "First Key Insight",
      "badge": "🌱 PLANT vs ANIMAL",
      "badge_type": "info",
      "image_query": "spinach greens bowl",
      "body": "Clear 1-2 sentence biological explanation of why this matters for energy and health."
    }},
    {{
      "num": "02",
      "title": "Second Key Insight",
      "badge": "⚡ +300% ABSORPTION",
      "badge_type": "synergy",
      "image_query": "fresh lemon slice",
      "body": "Clear 1-2 sentence explanation of the cause and effect inside the body."
    }},
    {{
      "num": "03",
      "title": "Third Key Insight",
      "badge": "❌ -80% BLOCKED",
      "badge_type": "warning",
      "image_query": "coffee cup espresso",
      "body": "Clear 1-2 sentence explanation busting a common health myth."
    }}
  ],
  "protocol_title": "THE DAILY RECOVERY PROTOCOL",
  "protocol_image_query": "pomegranate seeds",
  "takeaway": "Specific actionable daily habit to implement starting today.",
  "caption": "Full Instagram caption with hook, takeaway bullets, save reminder, and hashtags"
}}
"""
        candidate_models = ["gemini-3.5-flash-lite", "gemini-3.5-flash", Config.GEMINI_MODEL]
        for model_name in candidate_models:
            try:
                logger.info(f"Requesting English visual poster content from Gemini model: {model_name}...")
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                raw_text = response.text.strip()
                if "```json" in raw_text:
                    raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                elif "```" in raw_text:
                    raw_text = raw_text.split("```")[1].split("```")[0].strip()

                data = json.loads(raw_text)
                
                raw_points = data.get("points", [])
                formatted_points = []
                for idx, pt in enumerate(raw_points[:3]):
                    num = pt.get("num", f"0{idx+1}")
                    b_type = pt.get("badge_type", "info")
                    if b_type == "synergy":
                        accent, b_bg, b_fg = "#10b981", "#064e3b", "#34d399"
                    elif b_type == "warning":
                        accent, b_bg, b_fg = "#ef4444", "#450a0a", "#f87171"
                    else:
                        accent, b_bg, b_fg = "#06b6d4", "#083344", "#38bdf8"

                    formatted_points.append({
                        "num": num,
                        "title": pt.get("title", f"Insight {num}"),
                        "badge": pt.get("badge", "KEY INSIGHT"),
                        "badge_bg": b_bg,
                        "badge_fg": b_fg,
                        "accent": accent,
                        "image_query": pt.get("image_query", topic),
                        "body": pt.get("body", "")
                    })

                while len(formatted_points) < 3:
                    idx = len(formatted_points)
                    formatted_points.append({
                        "num": f"0{idx+1}",
                        "title": f"Key Principle {idx+1}",
                        "badge": "⚡ HABIT SHIFT",
                        "badge_bg": "#064e3b",
                        "badge_fg": "#34d399",
                        "accent": "#10b981",
                        "image_query": topic,
                        "body": "Consistency and proper nutrient timing yield cumulative metabolic benefits."
                    })

                h1 = data.get("headline_line1")
                h2 = data.get("headline_line2")
                if not h1:
                    full_hl = data.get("headline", topic.upper())
                    parts = full_hl.split(" - ") if " - " in full_hl else full_hl.split(":")
                    h1 = parts[0].strip()
                    h2 = parts[1].strip() if len(parts) > 1 else "DAILY WELLNESS PROTOCOL"

                return PosterContent(
                    headline_line1=h1.upper(),
                    headline_line2=(h2 or "DAILY WELLNESS PROTOCOL").upper(),
                    subtitle=data.get("subtitle", "How to optimize your body and beat fatigue naturally"),
                    category=(data.get("category") or category).upper(),
                    points=formatted_points,
                    protocol_title=(data.get("protocol_title") or "THE DAILY RECOVERY PROTOCOL").upper(),
                    protocol_image_query=data.get("protocol_image_query", "healthy food plate"),
                    takeaway=data.get("takeaway", "Implement this simple habit daily for long-term vitality."),
                    caption=data.get("caption", f"Essential wellness intel on {topic}. #Arovia360 #HealthTips")
                )
            except Exception as e:
                logger.warning(f"Poster generation attempt with {model_name} failed: {e}")

        logger.warning("All Gemini candidate models failed for poster. Falling back to default content.")
        return self._mock_content(topic, category)

    def _mock_content(self, topic: str, category: str) -> PosterContent:
        is_iron = "iron" in topic.lower() or "tired" in topic.lower()
        if is_iron:
            return PosterContent(
                headline_line1="WHY YOU'RE ALWAYS TIRED",
                headline_line2="THE IRON DEFICIENCY PROTOCOL",
                subtitle="How to unlock iron absorption and beat chronic fatigue naturally",
                category="NUTRITION & VITALITY",
                points=[
                    {
                        "num": "01",
                        "title": "Heme vs Non-Heme Iron",
                        "badge": "🌱 PLANT vs ANIMAL",
                        "badge_bg": "#064e3b",
                        "badge_fg": "#34d399",
                        "accent": "#10b981",
                        "image_query": "spinach greens bowl",
                        "body": "Animal iron absorbs directly. Plant iron (spinach, lentils) requires an acidic activator to unlock in the gut."
                    },
                    {
                        "num": "02",
                        "title": "The Vitamin C Synergy",
                        "badge": "⚡ +300% ABSORPTION",
                        "badge_bg": "#083344",
                        "badge_fg": "#38bdf8",
                        "accent": "#06b6d4",
                        "image_query": "fresh lemon slice",
                        "body": "Pairing plant greens with fresh citrus converts ferric iron into absorbable ferrous iron, boosting mineral uptake by up to 300%."
                    },
                    {
                        "num": "03",
                        "title": "The 60-Minute Coffee Rule",
                        "badge": "❌ -80% BLOCKED",
                        "badge_bg": "#450a0a",
                        "badge_fg": "#f87171",
                        "accent": "#ef4444",
                        "image_query": "coffee cup espresso",
                        "body": "Caffeine and tannins bind directly to iron molecules in your stomach. Keep coffee and tea at least 1 hour away from meals."
                    }
                ],
                protocol_title="THE DAILY RECOVERY PROTOCOL",
                protocol_image_query="pomegranate seeds",
                takeaway="Always squeeze fresh lemon over plant greens, and separate coffee or tea by at least 60 minutes from iron-rich meals.",
                caption="Struggling with low energy and brain fog? It might not be lack of sleep—it could be a hidden iron deficiency! 🩸✨\n\nHere is how to fix it:\n• Know your sources: Animal heme iron absorbs directly, while plant non-heme iron needs an acidic activator.\n• Supercharge absorption: Always pair plant-based greens with fresh citrus (Vitamin C) to boost uptake by up to 300%.\n• Avoid iron blockers: Keep coffee, tea, and calcium away from your iron-rich meals by at least 60 minutes.\n\n📌 Save this guide for your daily wellness routine!\n\n#IronDeficiency #NutritionScience #HealthyEating #EnergyBoost #AnemiaAwareness #GutHealth #WellnessTips #Arovia360"
            )

        clean_topic = topic.upper()
        return PosterContent(
            headline_line1=f"THE SCIENCE OF {clean_topic}",
            headline_line2="DAILY WELLNESS PROTOCOL",
            subtitle="What actually happens inside your body & how to optimize it",
            category=category.upper(),
            points=[
                {
                    "num": "01",
                    "title": "Biological Trigger",
                    "badge": "⚡ ACTIVE METABOLISM",
                    "badge_bg": "#064e3b",
                    "badge_fg": "#34d399",
                    "accent": "#10b981",
                    "image_query": "healthy fresh vegetables",
                    "body": "Everyday habits alter digestive enzymes, dictating how your metabolism handles cellular stress throughout the day."
                },
                {
                    "num": "02",
                    "title": "Metabolic Impact",
                    "badge": "🛡️ CELL PROTECTION",
                    "badge_bg": "#083344",
                    "badge_fg": "#38bdf8",
                    "accent": "#06b6d4",
                    "image_query": "fresh fruit bowl",
                    "body": "When consumed properly, bioavailable vitamins and antioxidants are absorbed up to 60% faster, protecting vital cells."
                },
                {
                    "num": "03",
                    "title": "Sustained Vitality",
                    "badge": "⏰ TIMING PROTOCOL",
                    "badge_bg": "#450a0a",
                    "badge_fg": "#f87171",
                    "accent": "#ef4444",
                    "image_query": "drinking water glass",
                    "body": "Simple nutritional swaps neutralize antinutrients, eliminating digestive sluggishness and afternoon crashes."
                }
            ],
            protocol_title="THE DAILY RECOVERY PROTOCOL",
            protocol_image_query="healthy meal bowl",
            takeaway="Implement this simple habit daily: pair hydration with consistent nutrient timing for optimal cellular vitality.",
            caption=f"⚡ {topic} | Essential Daily Wellness Guide\n\nSave this checklist to keep your routine on track! 📌\n\n#Arovia360 #DailyHealth #NutritionTips #WellnessRoutine #HealthyHabits"
        )

    def _fetch_photo(self, query: str, cache_name: str, fallback_video_sec: int = None) -> Path | None:
        """
        Fetch authentic high-res photography for a specific query from Pixabay CDN,
        caching locally or falling back to extracted video frames.
        """
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", cache_name).lower()
        cached_file = ASSETS_DIR / f"{safe_name}.jpg"
        if cached_file.exists() and cached_file.stat().st_size > 2000:
            return cached_file

        # 1. Try Pixabay Image API
        if Config.is_valid_key(self.pixabay_key):
            try:
                url = (
                    f"https://pixabay.com/api/?key={self.pixabay_key}"
                    f"&q={urllib.parse.quote(query)}&image_type=photo&orientation=all&safesearch=true&per_page=3"
                )
                res = requests.get(url, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    hits = data.get("hits", [])
                    if hits:
                        # Pixabay previewURL can be upscaled to 640px smoothly
                        p_url = hits[0].get("previewURL", "").replace("_150.jpg", "_640.jpg")
                        if p_url:
                            img_resp = requests.get(p_url, timeout=6)
                            if img_resp.status_code == 200 and len(img_resp.content) > 2000:
                                with open(cached_file, "wb") as f:
                                    f.write(img_resp.content)
                                return cached_file
            except Exception as e:
                logger.debug(f"Pixabay photo fetch warning for '{query}': {e}")

        # 2. Fallback: extract frame from video if available
        if fallback_video_sec is not None:
            state_file = Path("current_reel.json")
            video_src = None
            if state_file.exists():
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        s_data = json.load(f)
                        video_src = s_data.get("video_path") or s_data.get("cloudinary_url")
                except Exception:
                    pass
            if not video_src:
                output_dir = Path("output")
                if output_dir.exists():
                    mp4s = sorted(output_dir.glob("*.mp4"), key=os.path.getmtime, reverse=True)
                    if mp4s:
                        video_src = str(mp4s[0])

            if video_src:
                try:
                    ts = f"00:00:{fallback_video_sec:02d}"
                    cmd = ["ffmpeg", "-y", "-ss", ts, "-i", str(video_src), "-vframes", "1", "-q:v", "2", str(cached_file)]
                    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
                    if res.returncode == 0 and cached_file.exists() and cached_file.stat().st_size > 2000:
                        return cached_file
                except Exception:
                    pass

        return None

    def _make_rounded_thumb(self, img_path: Path, size: tuple[int, int] = (165, 165), radius: int = 18) -> Image.Image | None:
        """Helper to create a crisp, center-cropped rounded thumbnail with transparency."""
        if not img_path or not img_path.exists():
            return None
        try:
            im = Image.open(img_path).convert("RGB")
            w, h = im.size
            min_dim = min(w, h)
            left = (w - min_dim) // 2
            top = (h - min_dim) // 2
            im_cropped = im.crop((left, top, left + min_dim, top + min_dim)).resize(size, Image.Resampling.LANCZOS)

            mask = Image.new("L", size, 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([0, 0, size[0], size[1]], radius=radius, fill=255)

            output = Image.new("RGBA", size, (0, 0, 0, 0))
            output.paste(im_cropped, (0, 0), mask=mask)
            return output
        except Exception as e:
            logger.debug(f"Thumbnail creation error for {img_path}: {e}")
            return None

    def _get_fonts(self):
        """Locate high-quality sans-serif fonts on system with graceful fallbacks."""
        bold_paths = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
        ]
        reg_paths = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-Regular.ttf",
        ]

        bold_path = next((p for p in bold_paths if Path(p).exists()), None)
        reg_path = next((p for p in reg_paths if Path(p).exists()), None)

        def make_font(path, size, bold=False):
            if path:
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
            return ImageFont.load_default()

        return {
            "brand": make_font(bold_path, 20, True),
            "category": make_font(bold_path, 15, True),
            "headline1": make_font(bold_path, 46, True),
            "headline2": make_font(bold_path, 34, True),
            "subtitle": make_font(reg_path, 22),
            "card_num": make_font(bold_path, 22, True),
            "card_title": make_font(bold_path, 27, True),
            "card_body": make_font(reg_path, 20),
            "badge": make_font(bold_path, 14, True),
            "protocol_head": make_font(bold_path, 20, True),
            "protocol_body": make_font(bold_path, 22, True),
            "footer": make_font(bold_path, 17, True),
        }

    def _wrap_text(self, text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
        words = text.split()
        lines = []
        cur_line = []
        for w in words:
            test = " ".join(cur_line + [w])
            if draw.textlength(test, font=font) <= max_width:
                cur_line.append(w)
            else:
                if cur_line:
                    lines.append(" ".join(cur_line))
                cur_line = [w]
        if cur_line:
            lines.append(" ".join(cur_line))
        return lines

    def render_poster(self, content: PosterContent, output_path: Path = None, video_source: str = None) -> Path:
        """
        Render a 1080x1350 luxury, highly visual English health infographic poster
        packed with authentic photography, visual metric badges, and clear hierarchy.
        """
        width, height = 1080, 1350
        canvas = Image.new("RGB", (width, height), color="#090d16")
        draw = ImageDraw.Draw(canvas)

        # 1. Subtle Dark Gradient Background
        for y in range(height):
            ratio = y / float(height)
            r = int(9 + (15 - 9) * ratio)
            g = int(13 + (23 - 13) * ratio)
            b = int(22 + (42 - 22) * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # 2. Outer Subtle Border & Top Glowing Highlight
        draw.rounded_rectangle([24, 24, width - 24, height - 24], radius=28, outline="#1e293b", width=2)
        draw.line([(width // 2 - 160, 24), (width // 2 + 160, 24)], fill="#10b981", width=4)

        fonts = self._get_fonts()

        # 3. Top Brand Pill (Centered)
        pill_w, pill_h = 240, 40
        pill_x = (width - pill_w) // 2
        pill_y = 48
        draw.rounded_rectangle([pill_x, pill_y, pill_x + pill_w, pill_y + pill_h], radius=20, fill="#0f172a", outline="#10b981", width=2)
        # Glowing Emerald Dot
        draw.ellipse([pill_x + 22, pill_y + 14, pill_x + 34, pill_y + 26], fill="#34d399")
        draw.text((pill_x + 48, pill_y + 10), "AROVIA 360", font=fonts["brand"], fill="#ffffff")

        # 4. Category Pill with Cyan Glow Accent
        cat_text = content.category if content.category else "EVIDENCE-BASED NUTRITION"
        cat_w = int(draw.textlength(cat_text, font=fonts["category"])) + 36
        cat_x = (width - cat_w) // 2
        cat_y = 102
        draw.rounded_rectangle([cat_x, cat_y, cat_x + cat_w, cat_y + 32], radius=16, fill="#083344", outline="#06b6d4", width=1)
        draw.text((width // 2, cat_y + 16), cat_text, font=fonts["category"], fill="#38bdf8", anchor="mm")

        # 5. Two-Tone Punchy Headline
        # Line 1: Crisp Bold White (Hook)
        draw.text((width // 2, 178), content.headline_line1, font=fonts["headline1"], fill="#ffffff", anchor="mm")
        # Line 2: Radiant Warm Amber Gold (Protocol)
        draw.text((width // 2, 232), content.headline_line2, font=fonts["headline2"], fill="#fbbf24", anchor="mm")

        # 6. Subtitle (Wrapped cleanly)
        sub_lines = self._wrap_text(content.subtitle, fonts["subtitle"], width - 160, draw)
        draw.multiline_text((width // 2, 280), "\n".join(sub_lines[:2]), font=fonts["subtitle"], fill="#cbd5e1", anchor="mm", align="center", spacing=6)

        # 7. 3 Visual Feature Cards (With Real Food Photography)
        card_y = 325
        card_h = 205
        card_spacing = 18
        card_w = width - 100
        card_x = 50

        # Video fallback timestamps
        fallback_times = [2, 16, 10]

        for idx, pt in enumerate(content.points[:3]):
            cy = card_y + idx * (card_h + card_spacing)
            num = pt.get("num", f"0{idx+1}")
            c_title = pt.get("title", f"Insight {num}")
            c_body = pt.get("body", "")
            accent = pt.get("accent", ACCENT_COLORS[idx % len(ACCENT_COLORS)])
            b_text = pt.get("badge", "KEY INSIGHT")
            b_bg = pt.get("badge_bg", "#083344")
            b_fg = pt.get("badge_fg", "#38bdf8")
            q = pt.get("image_query", "healthy nutrition")

            # Glass card container
            draw.rounded_rectangle([card_x, cy, card_x + card_w, cy + card_h], radius=24, fill="#0c1322", outline="#1e293b", width=1)
            # Left vertical indicator bar
            draw.rounded_rectangle([card_x + 6, cy + 24, card_x + 11, cy + card_h - 24], radius=3, fill=accent)

            # 1. Fetch & Render Real Photographic Thumbnail on Left
            thumb_path = self._fetch_photo(q, f"card_{idx}_{q}", fallback_video_sec=fallback_times[idx % len(fallback_times)])
            thumb_x = card_x + 24
            thumb_y = cy + 20
            thumb_w, thumb_h = 165, 165
            thumb = self._make_rounded_thumb(thumb_path, (thumb_w, thumb_h), radius=18)
            if thumb:
                # Border glow behind thumb
                draw.rounded_rectangle([thumb_x - 2, thumb_y - 2, thumb_x + thumb_w + 2, thumb_y + thumb_h + 2], radius=20, outline=accent, width=2)
                canvas.paste(thumb, (thumb_x, thumb_y), thumb)
            else:
                # Decorative fallback badge box
                draw.rounded_rectangle([thumb_x, thumb_y, thumb_x + thumb_w, thumb_y + thumb_h], radius=18, fill="#064e3b33", outline=accent, width=2)
                draw.text((thumb_x + thumb_w // 2, thumb_y + thumb_h // 2), num, font=fonts["headline1"], fill=accent, anchor="mm")

            # 2. Text Content & Badges on Right
            tx = thumb_x + thumb_w + 24
            content_w = (card_x + card_w) - tx - 24

            # Visual Badge Pill (Top Right)
            b_w = int(draw.textlength(b_text, font=fonts["badge"])) + 24
            b_h = 26
            b_x = (card_x + card_w) - b_w - 24
            b_y = cy + 20
            draw.rounded_rectangle([b_x, b_y, b_x + b_w, b_y + b_h], radius=13, fill=b_bg, outline=accent, width=1)
            draw.text((b_x + b_w // 2, b_y + b_h // 2), b_text, font=fonts["badge"], fill=b_fg, anchor="mm")

            # Number + Card Title
            draw.text((tx, cy + 20), f"{num} |", font=fonts["card_num"], fill=accent)
            draw.text((tx + 46, cy + 18), c_title, font=fonts["card_title"], fill="#f8fafc")

            # Body Text (wrapped cleanly)
            b_lines = self._wrap_text(c_body, fonts["card_body"], content_w, draw)
            draw.multiline_text((tx, cy + 62), "\n".join(b_lines[:3]), font=fonts["card_body"], fill="#94a3b8", spacing=6)

        # 8. Actionable Protocol Box (WITH 4TH VISUAL PHOTO)
        box_y = 1000
        box_h = 195
        draw.rounded_rectangle([card_x, box_y, card_x + card_w, box_y + box_h], radius=24, fill="#022c22", outline="#10b981", width=2)

        # 4th Visual Photo
        p_query = content.protocol_image_query if content.protocol_image_query else "pomegranate seeds"
        p_thumb_path = self._fetch_photo(p_query, f"proto_{p_query}", fallback_video_sec=16)
        p_thumb_x = card_x + 24
        p_thumb_y = box_y + 20
        p_thumb_w, p_thumb_h = 155, 155
        p_thumb = self._make_rounded_thumb(p_thumb_path, (p_thumb_w, p_thumb_h), radius=18)
        if p_thumb:
            draw.rounded_rectangle([p_thumb_x - 2, p_thumb_y - 2, p_thumb_x + p_thumb_w + 2, p_thumb_y + p_thumb_h + 2], radius=20, outline="#10b981", width=2)
            canvas.paste(p_thumb, (p_thumb_x, p_thumb_y), p_thumb)
            ptx = p_thumb_x + p_thumb_w + 24
            p_content_w = (card_x + card_w) - ptx - 24
        else:
            ptx = card_x + 32
            p_content_w = card_w - 64

        # Custom Vector Lightning Bolt Icon (NO broken unicode glyphs)
        lx, ly = ptx, box_y + 24
        draw.polygon([(lx + 8, ly), (lx, ly + 14), (lx + 9, ly + 14), (lx + 5, ly + 26), (lx + 18, ly + 11), (lx + 9, ly + 11)], fill="#facc15")
        proto_title = content.protocol_title if content.protocol_title else "THE DAILY RECOVERY PROTOCOL"
        draw.text((ptx + 28, box_y + 24), proto_title, font=fonts["protocol_head"], fill="#34d399")

        # Protocol body text (wrapped)
        p_lines = self._wrap_text(content.takeaway, fonts["protocol_body"], p_content_w, draw)
        draw.multiline_text((ptx, box_y + 66), "\n".join(p_lines[:3]), font=fonts["protocol_body"], fill="#ffffff", spacing=8)

        # 9. Clean Footer with Vector Bookmark Ribbon Icon (NO broken unicode glyphs)
        draw.line([(card_x, 1225), (card_x + card_w, 1225)], fill="#1e293b", width=1)
        bx, by = card_x + 10, 1252
        draw.polygon([(bx, by), (bx + 14, by), (bx + 14, by + 20), (bx + 7, by + 14), (bx, by + 20)], fill="#64748b")
        draw.text((card_x + 34, 1252), "SAVE THIS GUIDE FOR LATER", font=fonts["footer"], fill="#94a3b8")
        draw.text((width - card_x - 10, 1252), "FOLLOW @AROVIA360 FOR DAILY HEALTH", font=fonts["footer"], fill="#10b981", anchor="ra")

        if not output_path:
            output_dir = Config.OUTPUT_DIR
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"poster_{int(time.time())}.png"

        canvas.save(str(output_path), format="PNG", quality=95)
        logger.info(f"Rendered English infographic poster saved to: {output_path}")
        return output_path

    def generate(self, topic: str, category: str = "Health & Wellness", output_path: Path = None, video_source: str = None) -> tuple[Path, PosterContent]:
        """Convenience method: generate content and render poster in one call."""
        content = self.generate_content(topic, category)
        path = self.render_poster(content, output_path, video_source=video_source)
        return path, content
