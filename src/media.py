import logging
import subprocess
from pathlib import Path
import requests
from src.config import Config

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "white", "black", "red", "blue", "green", "yellow", "meter", "human",
    "close", "closeup", "fresh", "high", "low", "more", "less", "fast", "slow",
    "eating", "drinking", "looking", "doing", "taking", "body", "woman",
    "man", "girl", "boy", "person", "up", "down", "colorful", "happy",
    "the", "and", "for", "with", "from", "into", "this", "that", "raw", "dry",
    "hand", "holding", "bowl", "plate", "table", "shot", "macro", "concept",
    "texture", "food", "healthy", "health", "nutrition", "nutrient", "absorption",
    "good", "best", "super", "system", "life", "lifestyle", "daily", "simple",
    "glass", "cup", "animation", "3d", "render", "loop"
}

BANNED_TAGS = {
    # Landscapes & Scenery
    "landscape", "scenery", "scenic", "horizon", "mountains", "mountain", "beach",
    "ocean", "sea", "sunset", "sunrise", "clouds", "sky", "highway", "railroad",
    "road", "traffic", "car", "cars", "windmill", "winery", "vineyard", "dam", "reservoir",
    # Nightlife & Alcohol
    "cocktail", "alcohol", "wine", "beer", "liquor", "champagne", "bartender",
    "bar", "pub", "disco", "nightclub", "party", "club",
    # Glamour, Bathroom & Romance
    "wedding", "bride", "groom", "fashion", "lingerie", "makeup", "cosmetics",
    "lipstick", "eyeshadow", "nail polish", "jewelry", "glamour", "model",
    "bathtub", "bath", "silhouette", "green screen", "greenscreen",
    # Botany / Flowers / Trees (not edible food)
    "flowers", "floral", "blossom", "tree branch", "tree", "plant", "garden",
    # Wildlife / Unrelated Animals
    "squirrel", "rodent", "bird", "wildlife", "animal", "animals", "lion",
    "tiger", "insect", "cassette", "cyberpunk",
    # Space & Unrelated fast food
    "space", "galaxy", "nebula", "cosmos", "universe", "stars", "starry", "astronomy",
    "pasta", "farfalle", "spaghetti", "noodle", "noodles", "pizza", "burger",
    # Surgery / unrelated operations & tools
    "surgery", "operation", "renal", "hammer", "cracking", "factory", "tool", "tools", "craft", "labor", "worker",
    # Abstract / Fractals / CGI
    "fractal", "mandelbulb", "abstract", "render", "rendered", "cgi"
}

# Semantic topic mappings for strict medical & food accuracy
TOPIC_SUBJECT_RULES = {
    "almond": ["almond", "almonds", "nuts", "nut", "dry fruits", "seed"],
    "soak": ["water", "glass", "nuts", "seeds", "soaking"],
    "sugar": ["sugar", "sweets", "sweet", "dessert", "candy", "sweetener"],
    "glucose": ["diabetes", "blood", "glucometer", "medical", "doctor", "health"],
    "insulin": ["diabetes", "blood", "medical", "doctor", "hormone", "health"],
    "liver": ["liver", "organ", "anatomy", "medical", "internal"],
    "brain": ["brain", "neurons", "neuron", "mind", "head", "synapses", "thinking"],
    "digest": ["digestive", "digestion", "stomach", "intestine", "gut"],
    "water": ["water", "drinking", "hydrate", "hydration", "pour"],
    "salad": ["salad", "vegetables", "vegetable", "greens", "organic"],
    "exercise": ["exercise", "fitness", "workout", "stretching", "training", "yoga"]
}

class MediaFetcher:
    def __init__(self, pixabay_key: str = None, pexels_key: str = None):
        self.pixabay_key = pixabay_key or Config.PIXABAY_API_KEY
        self.pexels_key = pexels_key or Config.PEXELS_API_KEY

    def _extract_keywords(self, text: str) -> list[str]:
        words = [w.strip(".,!?:;\"'()[]{}*~-").lower() for w in text.split()]
        filtered = [w for w in words if len(w) > 2 and w not in STOP_WORDS]
        return filtered if filtered else [w for w in words if len(w) > 3]

    def get_multiple_background_clips(self, scenes_or_queries: list, durations: list[float]) -> list[Path]:
        """
        Fetch distinct, strictly relevant HD video clips for each scene from Pixabay.
        Prioritizes true vertical videos (9:16), avoids repetitions, and penalizes unrelated footage.
        """
        Config.ensure_dirs()
        clip_paths = []
        used_video_ids = set()
        recent_tags = []

        for idx, (item, dur) in enumerate(zip(scenes_or_queries, durations)):
            clip_path = Config.TEMP_DIR / f"scene_clip_{idx}.mp4"

            # Support both Scene object and legacy query string
            if hasattr(item, "search_queries"):
                queries = item.search_queries or [item.visual_query]
                concept = getattr(item, "visual_concept", "")
                negatives = getattr(item, "negative_keywords", [])
                telugu_title = getattr(item, "telugu_speech", "")[:30]
            elif hasattr(item, "visual_query"):
                queries = [item.visual_query]
                concept = getattr(item, "visual_concept", "")
                negatives = []
                telugu_title = getattr(item, "telugu_speech", "")[:30]
            else:
                queries = [str(item)]
                concept = str(item)
                negatives = []
                telugu_title = ""

            logger.info(f"Fetching scene {idx + 1}/{len(durations)} visuals (dur: {dur:.1f}s): queries={queries[:2]}")

            downloaded = False
            if Config.is_valid_key(self.pixabay_key):
                downloaded = self._fetch_pixabay_video(
                    queries=queries,
                    concept=concept,
                    negatives=negatives,
                    output_path=clip_path,
                    used_ids=used_video_ids,
                    min_duration=dur,
                    recent_tags=recent_tags
                )

            if not downloaded:
                logger.info(f"Using high-production cinematic motion graphic for scene {idx + 1}...")
                self._generate_cinematic_graphic_clip(
                    output_path=clip_path,
                    duration=dur,
                    scene_idx=idx,
                    title=concept or queries[0],
                    subtitle=telugu_title
                )

            clip_paths.append(clip_path)

        return clip_paths

    def _fetch_pixabay_video(
        self,
        queries: list[str],
        concept: str,
        negatives: list[str],
        output_path: Path,
        used_ids: set,
        min_duration: float,
        recent_tags: list[str]
    ) -> bool:
        """Search Pixabay across ranked queries, score candidates, and download the best relevant clip."""
        try:
            # 1. Identify core required semantic nouns from queries and concept
            full_text = (concept + " " + " ".join(queries)).lower()
            required_tags_pool = set()
            for key, accepted_tags in TOPIC_SUBJECT_RULES.items():
                if key in full_text:
                    required_tags_pool.update(accepted_tags)

            core_keywords = set(self._extract_keywords(full_text))
            negative_set = set(BANNED_TAGS).union(set([n.lower() for n in negatives]))

            all_hits = []
            seen_hit_ids = set()

            for q in queries[:4]:
                clean_q = " ".join(self._extract_keywords(q)[:2])
                if not clean_q:
                    continue
                hits = self._query_pixabay(clean_q)
                for h in hits:
                    hid = h.get("id")
                    if hid and hid not in seen_hit_ids and hid not in used_ids:
                        seen_hit_ids.add(hid)
                        all_hits.append(h)
                if len(all_hits) >= 15:
                    break

            candidates = []
            for hit in all_hits:
                hit_id = hit.get("id")
                raw_tags = hit.get("tags", "").lower()
                tag_list = [t.strip() for t in raw_tags.split(",")]
                tag_set = set(tag_list)

                # 1. Hard rejection: Banned or negative tags
                if tag_set.intersection(negative_set):
                    continue

                # 2. Strict Subject Relevance: Must match required semantic topic tags if defined
                if required_tags_pool:
                    if not tag_set.intersection(required_tags_pool) and not any(rt in raw_tags for rt in required_tags_pool):
                        continue
                else:
                    # Generic semantic overlap
                    if not any(ck in raw_tags for ck in core_keywords):
                        continue

                videos = hit.get("videos", {})
                large = videos.get("large", {})
                medium = videos.get("medium", {})
                small = videos.get("small", {})
                best_video = large if large.get("url") else (medium if medium.get("url") else small)
                if not best_video or not best_video.get("url"):
                    continue

                w = best_video.get("width") or 1920
                h = best_video.get("height") or 1080
                is_vertical = h >= w
                hit_dur = float(hit.get("duration", 0))

                # Multi-factor scoring
                score = 0
                if is_vertical:
                    score += 40  # Big boost for true vertical 9:16
                if w >= 1080:
                    score += 15  # HD quality
                
                # Bonus for exact subject match
                matching_core = [ck for ck in core_keywords if ck in raw_tags]
                score += len(matching_core) * 15

                if hit_dur >= min_duration:
                    score += 10
                elif hit_dur < 3.0:
                    score -= 20

                # Avoid back-to-back duplicate tag style
                for prev_tag in recent_tags[-2:]:
                    if prev_tag in tag_set:
                        score -= 25

                candidates.append({
                    "id": hit_id,
                    "url": best_video["url"],
                    "w": w,
                    "h": h,
                    "is_vertical": is_vertical,
                    "score": score,
                    "tags": raw_tags,
                    "primary_tag": tag_list[0] if tag_list else ""
                })

            if not candidates:
                logger.warning(f"No candidates passed semantic relevance threshold for queries {queries[:2]}.")
                return False

            candidates.sort(key=lambda c: c["score"], reverse=True)
            chosen = candidates[0]

            logger.info(
                f"Selected Pixabay clip ID {chosen['id']} (score: {chosen['score']}, "
                f"{'9:16 Vertical' if chosen['is_vertical'] else 'Horizontal'} {chosen['w']}x{chosen['h']}): "
                f"tags='{chosen['tags'][:60]}...'"
            )

            with requests.get(chosen["url"], stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)

            used_ids.add(chosen["id"])
            if chosen["primary_tag"]:
                recent_tags.append(chosen["primary_tag"])
            return True

        except Exception as e:
            logger.warning(f"Pixabay fetch error for {queries[:2]}: {e}")
            return False

    def _query_pixabay(self, query: str) -> list:
        url = (
            f"https://pixabay.com/api/videos/?key={self.pixabay_key}"
            f"&q={requests.utils.quote(query)}&per_page=30"
        )
        res = requests.get(url, timeout=15)
        res.raise_for_status()
        return res.json().get("hits", [])

    def _generate_cinematic_graphic_clip(
        self,
        output_path: Path,
        duration: float,
        scene_idx: int,
        title: str = "Health Tip",
        subtitle: str = ""
    ):
        """
        Generate a professional, documentary-grade motion graphic clip
        with smooth ambient camera zoom and elegant dark vignette when footage is unavailable.
        """
        color_themes = [
            ("0x0b1329", "0x162a45", "0x1d4ed8"),  # Deep Navy / Cellular
            ("0x064e3b", "0x065f46", "0x059669"),  # Emerald Vitality / Herbal
            ("0x1f1d36", "0x3f3351", "0x86198f"),  # Midnight Purple / Medical
            ("0x18181b", "0x27272a", "0x3f3f46"),  # Modern Charcoal / Studio
            ("0x1c1917", "0x292524", "0x44403c")   # Warm Slate / Organic
        ]
        c0, c1, c2 = color_themes[scene_idx % len(color_themes)]
        dur_s = max(duration, 3.0)

        # High-end animated gradient with subtle floating zoom and vignette
        filter_complex = (
            f"gradients=s=1080x1920:d={dur_s:.2f}:c0={c0}:c1={c1}:c2={c2}:x0=540:y0=960:x1=1080:y1=1920,"
            f"zoompan=z='min(zoom+0.0006,1.06)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,"
            f"vignette=angle=PI/4:aspect=1080/1920,"
            f"format=yuv420p"
        )

        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", filter_complex,
            "-t", f"{dur_s:.2f}",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            str(output_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            cmd2 = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c={c0}:s=1080x1920:d={dur_s:.2f}",
                "-t", f"{dur_s:.2f}",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                str(output_path)
            ]
            subprocess.run(cmd2, check=True)
