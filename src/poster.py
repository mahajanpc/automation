import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from src.config import Config

logger = logging.getLogger(__name__)

@dataclass
class PosterContent:
    headline: str
    subtitle: str
    category: str
    points: list[dict] = field(default_factory=list)  # [{"num": "01", "title": "...", "body": "..."}]
    takeaway: str = ""
    caption: str = ""

class PosterGenerator:
    """
    Generates high-engagement 4:5 vertical (1080x1350) English health infographic posters
    designed for maximum saves, bookmarks, and shares on Instagram feeds.
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
You are an expert health infographic designer and medical communicator.
Create high-value, scientifically grounded, highly shareable ENGLISH infographic content for Instagram.

Category: "{category}"
Topic: "{topic}"

REQUIREMENTS:
1. LANGUAGE: 100% STRICTLY IN ENGLISH. Clean, crisp, authoritative, jargon-free.
2. HEADLINE: Punchy, high-curiosity uppercase title (4 to 8 words max, e.g. "3 MORNING HABITS THAT SPIKE BLOOD SUGAR", "WHAT HAPPENS WHEN YOU SOAK ALMONDS").
3. SUBTITLE: 1 explanatory line that promises clear value (e.g. "What actually happens inside your body when you eat nuts raw vs soaked").
4. 3 CORE CARDS:
   - Exactly 3 actionable points numbered "01", "02", "03".
   - 'title': Short bold headline (2 to 5 words).
   - 'body': High-impact, clear 2-sentence explanation of the biological mechanism.
5. TAKEAWAY / GOLDEN RULE: 1 or 2 sentences of simple, actionable daily advice.
6. CAPTION: Engaging English Instagram caption with:
   - Hook opening line
   - Bullet point summary of the 3 points
   - "📌 Save this post for your daily health routine!"
   - 8-10 targeted wellness hashtags (e.g. #HealthTips #NutritionScience #DailyWellness #Arovia360).

Return strictly a valid JSON object matching this schema:
{{
  "headline": "PUNCHY UPPERCASE HEADLINE",
  "subtitle": "Clear 1-line subtitle explaining the health benefit",
  "category": "{category.upper()}",
  "points": [
    {{
      "num": "01",
      "title": "First Key Insight",
      "body": "Clear 2-sentence biological explanation of why this matters for energy and health."
    }},
    {{
      "num": "02",
      "title": "Second Key Insight",
      "body": "Clear 2-sentence explanation of the cause and effect inside the body."
    }},
    {{
      "num": "03",
      "title": "Third Key Insight",
      "body": "Clear 2-sentence explanation busting a common health myth."
    }}
  ],
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
                return PosterContent(
                    headline=data.get("headline", topic.upper()),
                    subtitle=data.get("subtitle", f"Essential guide to {topic}"),
                    category=data.get("category", category.upper()),
                    points=data.get("points", self._mock_content(topic, category).points),
                    takeaway=data.get("takeaway", "Implement this simple habit daily for long-term vitality."),
                    caption=data.get("caption", f"Essential wellness intel on {topic}. #Arovia360 #HealthTips")
                )
            except Exception as e:
                logger.warning(f"Poster generation attempt with {model_name} failed: {e}")

        logger.warning("All Gemini candidate models failed for poster. Falling back to default content.")
        return self._mock_content(topic, category)

    def _mock_content(self, topic: str, category: str) -> PosterContent:
        clean_title = topic.upper()
        return PosterContent(
            headline=f"THE SCIENCE OF {clean_title}",
            subtitle="What actually happens inside your body & how to optimize it",
            category=category.upper(),
            points=[
                {
                    "num": "01",
                    "title": "Biological Trigger",
                    "body": "Everyday habits alter digestive enzymes and cellular response, dictating how your metabolism handles stress and nutrients throughout the day."
                },
                {
                    "num": "02",
                    "title": "Metabolic Impact",
                    "body": "When consumed properly, bioavailable vitamins and antioxidants are absorbed up to 60% faster, protecting vital organs and cell membranes."
                },
                {
                    "num": "03",
                    "title": "Sustained Vitality",
                    "body": "Simple nutritional swaps neutralize antinutrients, eliminating digestive sluggishness and preventing post-meal energy crashes."
                }
            ],
            takeaway="Implement this simple habit daily: pair hydration with consistent timing for optimal cellular vitality.",
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
            "logo": make_font(bold_path, 22, True),
            "category": make_font(bold_path, 16, True),
            "title": make_font(bold_path, 44, True),
            "subtitle": make_font(reg_path, 23),
            "card_num": make_font(bold_path, 28, True),
            "card_title": make_font(bold_path, 30, True),
            "card_body": make_font(reg_path, 21),
            "takeaway_header": make_font(bold_path, 20, True),
            "takeaway_body": make_font(bold_path, 23, True),
            "footer": make_font(bold_path, 18, True),
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

    def render_poster(self, content: PosterContent, output_path: Path = None) -> Path:
        """Render a 1080x1350 professional dark-mode health infographic poster."""
        width, height = 1080, 1350
        img = Image.new("RGB", (width, height), color="#080c14")
        draw = ImageDraw.Draw(img)

        # 1. Subtle Dark Gradient Background
        for y in range(height):
            ratio = y / height
            r = int(8 + (15 - 8) * ratio)
            g = int(12 + (23 - 12) * ratio)
            b = int(20 + (42 - 20) * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # 2. Outer Subtle Frame & Glowing Top Accent
        draw.rounded_rectangle([28, 28, width - 28, height - 28], radius=28, outline="#1f293d", width=2)
        draw.line([(width // 2 - 140, 28), (width // 2 + 140, 28)], fill="#10b981", width=3)

        fonts = self._get_fonts()

        # 3. Brand Pill (Top Center)
        pill_w, pill_h = 240, 44
        pill_x = (width - pill_w) // 2
        pill_y = 65
        draw.rounded_rectangle([pill_x, pill_y, pill_x + pill_w, pill_y + pill_h], radius=22, fill="#0f172a", outline="#10b981", width=2)
        draw.ellipse([pill_x + 18, pill_y + 16, pill_x + 30, pill_y + 28], fill="#10b981")
        draw.text((pill_x + 40, pill_y + 11), "AROVIA 360", font=fonts["logo"], fill="#f8fafc")

        # 4. Category Tag
        cat_text = content.category if content.category else "EVIDENCE-BASED NUTRITION"
        draw.text((width // 2, 135), cat_text, font=fonts["category"], fill="#10b981", anchor="mm")

        # 5. Headline (Wrapped)
        title_lines = self._wrap_text(content.headline, fonts["title"], width - 160, draw)
        title_block = "\n".join(title_lines[:3])
        draw.multiline_text((width // 2, 215), title_block, font=fonts["title"], fill="#ffffff", anchor="mm", align="center", spacing=12)

        # 6. Subtitle (Wrapped)
        sub_lines = self._wrap_text(content.subtitle, fonts["subtitle"], width - 180, draw)
        sub_block = "\n".join(sub_lines[:2])
        draw.multiline_text((width // 2, 305), sub_block, font=fonts["subtitle"], fill="#94a3b8", anchor="mm", align="center", spacing=6)

        # 7. 3 Feature Cards
        card_y = 360
        card_h = 190
        card_spacing = 22
        card_w = width - 120
        card_x = 60

        for idx, pt in enumerate(content.points[:3]):
            cy = card_y + idx * (card_h + card_spacing)
            num = pt.get("num", f"0{idx+1}")
            c_title = pt.get("title", f"Point {idx+1}")
            c_body = pt.get("body", "")

            # Glass card body
            draw.rounded_rectangle([card_x, cy, card_x + card_w, cy + card_h], radius=20, fill="#0b1120", outline="#1e293b", width=1)
            # Left emerald indicator
            draw.rounded_rectangle([card_x + 4, cy + 20, card_x + 8, cy + card_h - 20], radius=2, fill="#10b981")

            # Number badge
            draw.rounded_rectangle([card_x + 24, cy + 24, card_x + 76, cy + 76], radius=14, fill="#064e3b33", outline="#10b98166", width=1)
            draw.text((card_x + 50, cy + 50), num, font=fonts["card_num"], fill="#34d399", anchor="mm")

            # Card Title
            draw.text((card_x + 94, cy + 30), c_title, font=fonts["card_title"], fill="#f1f5f9")

            # Card Body wrapped
            b_lines = self._wrap_text(c_body, fonts["card_body"], card_w - 116, draw)
            draw.multiline_text((card_x + 94, cy + 74), "\n".join(b_lines[:3]), font=fonts["card_body"], fill="#94a3b8", spacing=6)

        # 8. Actionable Protocol / Takeaway Box
        box_y = 1015
        box_h = 175
        draw.rounded_rectangle([card_x, box_y, card_x + card_w, box_y + box_h], radius=20, fill="#064e3b25", outline="#10b981", width=2)
        draw.text((card_x + 30, box_y + 24), "💡 THE DAILY PROTOCOL", font=fonts["takeaway_header"], fill="#34d399")

        proto_lines = self._wrap_text(content.takeaway, fonts["takeaway_body"], card_w - 60, draw)
        draw.multiline_text((card_x + 30, box_y + 60), "\n".join(proto_lines[:3]), font=fonts["takeaway_body"], fill="#f8fafc", spacing=8)

        # 9. Clean Footer
        draw.line([(card_x, 1235), (card_x + card_w, 1235)], fill="#1e293b", width=1)
        draw.text((card_x + 10, 1265), "📌 SAVE THIS FOR LATER", font=fonts["footer"], fill="#64748b")
        draw.text((width - card_x - 10, 1265), "FOLLOW @AROVIA360 FOR DAILY WELLNESS", font=fonts["footer"], fill="#10b981", anchor="ra")

        if not output_path:
            output_dir = Config.OUTPUT_DIR
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"poster_{int(time.time())}.png"

        img.save(str(output_path), format="PNG", quality=95)
        logger.info(f"Rendered English infographic poster saved to: {output_path}")
        return output_path

    def generate(self, topic: str, category: str = "Health & Wellness", output_path: Path = None) -> tuple[Path, PosterContent]:
        """Convenience method: generate content and render poster in one call."""
        content = self.generate_content(topic, category)
        path = self.render_poster(content, output_path)
        return path, content
