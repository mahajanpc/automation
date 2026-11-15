import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

from src.config import Config

logger = logging.getLogger(__name__)

ACCENT_COLORS = ["#10b981", "#06b6d4", "#f59e0b"]  # Emerald, Sky Cyan, Amber Gold

@dataclass
class PosterContent:
    headline_line1: str
    headline_line2: str
    subtitle: str
    category: str
    points: list[dict] = field(default_factory=list)  # [{"num": "01", "title": "...", "body": "...", "accent": "#10b981"}]
    takeaway: str = ""
    protocol_title: str = "THE DAILY RECOVERY PROTOCOL"
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
    - Real HD hero photography blended with cinematic dark gradient
    - Two-tone punchy headlines (crisp white + glowing amber)
    - Custom vector-drawn icons (lightning bolt, bookmark ribbon) - no broken emoji glyphs
    - Color-coded infographic cards (emerald, cyan, amber)
    - Actionable 'Daily Protocol' highlight box
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or Config.GEMINI_API_KEY
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
You are an expert health infographic designer and viral Instagram content strategist (style of Glucose Goddess, Huberman Lab).
Create high-value, scientifically grounded, highly shareable ENGLISH infographic content for Instagram.

Category: "{category}"
Topic: "{topic}"

STRICT DESIGN & CONTENT REQUIREMENTS:
1. LANGUAGE: 100% STRICTLY IN ENGLISH. Clean, crisp, authoritative, jargon-free.
2. TWO-TONE HEADLINE:
   - 'headline_line1': Punchy uppercase curiosity/problem hook (3 to 6 words max, e.g. "WHY YOU'RE ALWAYS TIRED", "3 MORNING HABITS", "THE HIDDEN GUT INFLAMMATION TRAP").
   - 'headline_line2': Clear uppercase solution or protocol name (2 to 5 words max, e.g. "THE IRON DEFICIENCY PROTOCOL", "BLOOD SUGAR MASTERY GUIDE").
3. SUBTITLE: 1 explanatory line that promises immediate value (e.g. "How to optimize absorption & beat chronic fatigue naturally").
4. 3 CORE INFOGRAPHIC CARDS:
   - Exactly 3 actionable points numbered "01", "02", "03".
   - 'title': Short bold headline (2 to 5 words).
   - 'body': High-impact, clear 1 to 2 sentence explanation of the biological mechanism (max 22 words per card).
5. THE DAILY PROTOCOL / GOLDEN RULE:
   - 'protocol_title': "THE DAILY PROTOCOL" or "THE DAILY RECOVERY PROTOCOL"
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
      "body": "Clear 1-2 sentence biological explanation of why this matters for energy and health."
    }},
    {{
      "num": "02",
      "title": "Second Key Insight",
      "body": "Clear 1-2 sentence explanation of the cause and effect inside the body."
    }},
    {{
      "num": "03",
      "title": "Third Key Insight",
      "body": "Clear 1-2 sentence explanation busting a common health myth."
    }}
  ],
  "protocol_title": "THE DAILY RECOVERY PROTOCOL",
  "takeaway": "Specific actionable daily habit to implement starting today.",
  "caption": "Full Instagram caption with hook, takeaway bullets, save reminder, and hashtags"
}}
"""
        candidate_models = ["gemini-3.5-flash-lite", "gemini-3.5-flash", Config.GEMINI_MODEL]
        for model_name in candidate_models:
            try:
                logger.info(f"Requesting English poster content from Gemini model: {model_name}...")
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
                    accent = ACCENT_COLORS[idx % len(ACCENT_COLORS)]
                    formatted_points.append({
                        "num": num,
                        "title": pt.get("title", f"Insight {num}"),
                        "body": pt.get("body", ""),
                        "accent": accent
                    })

                while len(formatted_points) < 3:
                    idx = len(formatted_points)
                    formatted_points.append({
                        "num": f"0{idx+1}",
                        "title": f"Key Principle {idx+1}",
                        "body": "Consistency and proper nutrient timing yield cumulative metabolic benefits.",
                        "accent": ACCENT_COLORS[idx % len(ACCENT_COLORS)]
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
                    subtitle=data.get("subtitle", f"How to optimize your body and beat fatigue naturally"),
                    category=(data.get("category") or category).upper(),
                    points=formatted_points,
                    protocol_title=(data.get("protocol_title") or "THE DAILY RECOVERY PROTOCOL").upper(),
                    takeaway=data.get("takeaway", "Implement this simple habit daily for long-term vitality."),
                    caption=data.get("caption", f"Essential wellness intel on {topic}. #Arovia360 #HealthTips")
                )
            except Exception as e:
                logger.warning(f"Poster generation attempt with {model_name} failed: {e}")

        logger.warning("All Gemini candidate models failed for poster. Falling back to default content.")
        return self._mock_content(topic, category)

    def _mock_content(self, topic: str, category: str) -> PosterContent:
        is_iron = "iron" in topic.lower()
        if is_iron:
            return PosterContent(
                headline_line1="WHY YOU'RE ALWAYS TIRED",
                headline_line2="THE IRON DEFICIENCY PROTOCOL",
                subtitle="How to optimize absorption & beat chronic fatigue naturally",
                category="NUTRITION & VITALITY",
                points=[
                    {
                        "num": "01",
                        "title": "Heme vs Non-Heme Iron",
                        "body": "Animal iron absorbs directly without resistance. Plant iron requires an acidic chemical activator to unlock in the digestive tract.",
                        "accent": "#10b981"
                    },
                    {
                        "num": "02",
                        "title": "The 300% Vitamin C Synergy",
                        "body": "Pairing plant greens with fresh citrus converts stubborn ferric iron into absorbable ferrous iron, boosting mineral uptake by up to 300%.",
                        "accent": "#06b6d4"
                    },
                    {
                        "num": "03",
                        "title": "The 60-Minute Coffee Rule",
                        "body": "Caffeine, tannins, and calcium bind to iron in your stomach, blocking up to 80% of absorption. Keep coffee 1 hour away from meals.",
                        "accent": "#f59e0b"
                    }
                ],
                protocol_title="THE DAILY RECOVERY PROTOCOL",
                takeaway="Always squeeze fresh lemon over plant iron sources, and never drink coffee or tea within 60 minutes of eating your iron-rich meals.",
                caption="Struggling with low energy and brain fog? It might not be lack of sleep—it could be a hidden iron deficiency! 🩸✨\n\nHere is how to fix it:\n• Know your sources: Understand the difference between easily absorbed heme iron and stubborn non-heme iron.\n• Supercharge absorption: Always pair plant-based iron with Vitamin C like lemon or bell peppers.\n• Avoid iron blockers: Keep coffee, tea, and calcium away from your iron-rich meals to maximize uptake.\n\n📌 Save this post for your daily health routine!\n\n#IronDeficiency #NutritionScience #HealthyEating #EnergyBoost #AnemiaAwareness #GutHealth #WellnessTips #Arovia360"
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
                    "body": "Everyday habits alter digestive enzymes, dictating how your metabolism handles cellular stress throughout the day.",
                    "accent": "#10b981"
                },
                {
                    "num": "02",
                    "title": "Metabolic Impact",
                    "body": "When consumed properly, bioavailable vitamins and antioxidants are absorbed up to 60% faster, protecting vital cells.",
                    "accent": "#06b6d4"
                },
                {
                    "num": "03",
                    "title": "Sustained Vitality",
                    "body": "Simple nutritional swaps neutralize antinutrients, eliminating digestive sluggishness and afternoon crashes.",
                    "accent": "#f59e0b"
                }
            ],
            protocol_title="THE DAILY RECOVERY PROTOCOL",
            takeaway="Implement this simple habit daily: pair hydration with consistent nutrient timing for optimal cellular vitality.",
            caption=f"⚡ {topic} | Essential Daily Wellness Guide\n\nSave this checklist to keep your routine on track! 📌\n\n#Arovia360 #DailyHealth #NutritionTips #WellnessRoutine #HealthyHabits"
        )

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
            "card_num": make_font(bold_path, 26, True),
            "card_title": make_font(bold_path, 28, True),
            "card_body": make_font(reg_path, 21),
            "protocol_head": make_font(bold_path, 20, True),
            "protocol_body": make_font(bold_path, 23, True),
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

    def _extract_hero_frame(self, video_source: str = None) -> Image.Image | None:
        """
        Extracts a sharp 1080p frame from video footage (local file or Cloudinary URL)
        using FFmpeg to provide an authentic, high-impact hero visual.
        """
        source = video_source
        if not source:
            # Check current_reel.json
            state_file = Path("current_reel.json")
            if state_file.exists():
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        local_vid = data.get("video_path")
                        cloud_vid = data.get("cloudinary_url")
                        if local_vid and Path(local_vid).exists():
                            source = local_vid
                        elif cloud_vid:
                            source = cloud_vid
                except Exception:
                    pass

        if not source:
            # Check output/ directory for latest video
            output_dir = Path("output")
            if output_dir.exists():
                mp4s = sorted(output_dir.glob("*.mp4"), key=os.path.getmtime, reverse=True)
                if mp4s:
                    source = str(mp4s[0])

        if not source:
            return None

        temp_frame = Path("/tmp/extracted_poster_frame.jpg")
        cmd = [
            "ffmpeg", "-y",
            "-ss", "00:00:02",
            "-i", str(source),
            "-vframes", "1",
            "-q:v", "2",
            str(temp_frame)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=6)
            if res.returncode == 0 and temp_frame.exists() and temp_frame.stat().st_size > 1000:
                img = Image.open(temp_frame).convert("RGB")
                # Resize to 1080 width preserving aspect ratio or fill
                w, h = img.size
                target_w = 1080
                target_h = int(h * (target_w / w))
                img_resized = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                
                # Crop 520px tall section from upper middle
                crop_y1 = max(0, min(140, target_h - 520))
                hero_crop = img_resized.crop((0, crop_y1, 1080, crop_y1 + 520))
                # Enhance & darken for strong typography contrast
                hero_dark = ImageEnhance.Brightness(hero_crop).enhance(0.42)
                return hero_dark
        except Exception as e:
            logger.debug(f"Frame extraction failed from {source}: {e}")

        return None

    def render_poster(self, content: PosterContent, output_path: Path = None, video_source: str = None) -> Path:
        """
        Render a 1080x1350 luxury, highly shareable English health infographic poster.
        """
        width, height = 1080, 1350
        canvas = Image.new("RGB", (width, height), color="#080c14")

        # 1. Hero Photo Integration (Top 38%)
        hero = self._extract_hero_frame(video_source)
        if hero:
            canvas.paste(hero, (0, 0))
            # Smooth dark gradient fade down into canvas
            draw_fade = ImageDraw.Draw(canvas)
            fade_start = 240
            fade_end = 520
            for y in range(fade_start, fade_end):
                progress = (y - fade_start) / float(fade_end - fade_start)
                r = int(8 * progress)
                g = int(12 * progress)
                b = int(20 * progress)
                draw_fade.line([(0, y), (width, y)], fill=(8, 12, 20, int(255 * progress)))
        else:
            # Fallback: Rich Atmospheric Dark Mesh Gradient
            draw_mesh = ImageDraw.Draw(canvas)
            for y in range(height):
                ratio = y / height
                r = int(8 + (14 - 8) * ratio)
                g = int(12 + (24 - 12) * ratio)
                b = int(20 + (44 - 20) * ratio)
                draw_mesh.line([(0, y), (width, y)], fill=(r, g, b))

        draw = ImageDraw.Draw(canvas)

        # Ensure solid dark foundation below hero blend
        draw.rectangle([(0, 520), (width, height)], fill="#080c14")

        # 2. Outer Subtle Border & Top Glowing Highlight
        draw.rounded_rectangle([24, 24, width - 24, height - 24], radius=28, outline="#1e293b", width=2)
        draw.line([(width // 2 - 160, 24), (width // 2 + 160, 24)], fill="#10b981", width=4)

        fonts = self._get_fonts()

        # 3. Top Brand Pill (Centered)
        pill_w, pill_h = 240, 40
        pill_x = (width - pill_w) // 2
        pill_y = 52
        draw.rounded_rectangle([pill_x, pill_y, pill_x + pill_w, pill_y + pill_h], radius=20, fill="#0f172a", outline="#10b981", width=2)
        # Glowing Emerald Dot
        draw.ellipse([pill_x + 22, pill_y + 14, pill_x + 34, pill_y + 26], fill="#34d399")
        draw.text((pill_x + 48, pill_y + 10), "AROVIA 360", font=fonts["brand"], fill="#ffffff")

        # 4. Category Pill with Cyan Glow Accent
        cat_text = content.category if content.category else "NUTRITION & VITALITY"
        cat_w = int(draw.textlength(cat_text, font=fonts["category"])) + 36
        cat_x = (width - cat_w) // 2
        cat_y = 108
        draw.rounded_rectangle([cat_x, cat_y, cat_x + cat_w, cat_y + 32], radius=16, fill="#083344", outline="#06b6d4", width=1)
        draw.text((width // 2, cat_y + 16), cat_text, font=fonts["category"], fill="#38bdf8", anchor="mm")

        # 5. Two-Tone Punchy Headline
        # Line 1: Crisp Bold White (Hook)
        draw.text((width // 2, 190), content.headline_line1, font=fonts["headline1"], fill="#ffffff", anchor="mm")
        # Line 2: Radiant Warm Amber Gold (Protocol)
        draw.text((width // 2, 248), content.headline_line2, font=fonts["headline2"], fill="#fbbf24", anchor="mm")

        # 6. Subtitle (Wrapped cleanly)
        sub_lines = self._wrap_text(content.subtitle, fonts["subtitle"], width - 160, draw)
        draw.multiline_text((width // 2, 302), "\n".join(sub_lines[:2]), font=fonts["subtitle"], fill="#cbd5e1", anchor="mm", align="center", spacing=6)

        # 7. 3 Feature Cards (Color-Coded Accent System)
        card_y = 350
        card_h = 195
        card_spacing = 18
        card_w = width - 100
        card_x = 50

        for idx, pt in enumerate(content.points[:3]):
            cy = card_y + idx * (card_h + card_spacing)
            num = pt.get("num", f"0{idx+1}")
            c_title = pt.get("title", f"Insight {num}")
            c_body = pt.get("body", "")
            accent = pt.get("accent", ACCENT_COLORS[idx % len(ACCENT_COLORS)])

            # Card glass container
            draw.rounded_rectangle([card_x, cy, card_x + card_w, cy + card_h], radius=22, fill="#0d1526", outline="#1e293b", width=1)
            # Left vertical indicator bar
            draw.rounded_rectangle([card_x + 5, cy + 24, card_x + 10, cy + card_h - 24], radius=3, fill=accent)

            # Number badge
            badge_x1, badge_y1 = card_x + 28, cy + 26
            badge_x2, badge_y2 = card_x + 80, cy + 78
            draw.rounded_rectangle([badge_x1, badge_y1, badge_x2, badge_y2], radius=16, fill="#022c22", outline=accent, width=2)
            draw.text(((badge_x1 + badge_x2) // 2, (badge_y1 + badge_y2) // 2), num, font=fonts["card_num"], fill="#34d399", anchor="mm")

            # Title
            draw.text((card_x + 100, cy + 34), c_title, font=fonts["card_title"], fill="#f8fafc")

            # Body text (wrapped)
            b_lines = self._wrap_text(c_body, fonts["card_body"], card_w - 124, draw)
            draw.multiline_text((card_x + 100, cy + 78), "\n".join(b_lines[:3]), font=fonts["card_body"], fill="#94a3b8", spacing=6)

        # 8. Actionable Protocol Box (Golden Rule Callout)
        box_y = 1005
        box_h = 185
        draw.rounded_rectangle([card_x, box_y, card_x + card_w, box_y + box_h], radius=22, fill="#022c22", outline="#10b981", width=2)

        # Custom Vector Lightning Bolt Icon (NO broken unicode glyphs)
        lx, ly = card_x + 32, box_y + 24
        draw.polygon([(lx + 8, ly), (lx, ly + 14), (lx + 9, ly + 14), (lx + 5, ly + 26), (lx + 18, ly + 11), (lx + 9, ly + 11)], fill="#facc15")
        proto_title = content.protocol_title if content.protocol_title else "THE DAILY RECOVERY PROTOCOL"
        draw.text((card_x + 62, box_y + 24), proto_title, font=fonts["protocol_head"], fill="#34d399")

        # Protocol body text (wrapped)
        p_lines = self._wrap_text(content.takeaway, fonts["protocol_body"], card_w - 64, draw)
        draw.multiline_text((card_x + 32, box_y + 64), "\n".join(p_lines[:3]), font=fonts["protocol_body"], fill="#ffffff", spacing=8)

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
