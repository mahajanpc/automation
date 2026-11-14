import logging
import subprocess
from pathlib import Path
import requests
from src.config import Config

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "white", "black", "red", "blue", "green", "yellow", "meter", "human",
    "close", "fresh", "high", "low", "more", "less", "fast", "slow",
    "eating", "drinking", "looking", "doing", "taking", "body", "woman",
    "man", "girl", "boy", "person", "up", "down", "colorful", "happy"
}

BANNED_TAGS = {
    "lipstick", "makeup", "make up", "bride", "wedding", "fashion",
    "cosmetics", "lingerie", "glamour", "jewelry", "eyeshadow", "nail polish",
    "bird", "animal", "wildlife", "cassette", "party", "disco", "nightclub"
}

HEALTH_FALLBACK_TERMS = {
    "glucose": ["blood test", "diabetes", "medical hospital"],
    "sugar": ["sweets", "dessert", "candy food"],
    "liver": ["human organ", "medical anatomy", "health body"],
    "skin": ["face skin care", "wrinkles", "dermatology"]
}

class MediaFetcher:
    def __init__(self, pixabay_key: str = None, pexels_key: str = None):
        self.pixabay_key = pixabay_key or Config.PIXABAY_API_KEY
        self.pexels_key = pexels_key or Config.PEXELS_API_KEY

    def _get_primary_keywords(self, query: str) -> list[str]:
        words = [w.strip(".,!?:;\"'()[]{}*~-") for w in query.lower().split() if len(w.strip(".,!?:;\"'()[]{}*~-")) > 2]
        primaries = [w for w in words if w not in STOP_WORDS]
        return primaries if primaries else words

    def get_multiple_background_clips(self, queries: list[str], durations: list[float]) -> list[Path]:
        """
        Fetch distinct HD video clips for each scene from Pixabay.
        Prioritizes true vertical videos (9:16) and verifies strict topic relevance.
        """
        Config.ensure_dirs()
        clip_paths = []
        used_video_ids = set()

        for idx, (query, dur) in enumerate(zip(queries, durations)):
            clip_path = Config.TEMP_DIR / f"scene_clip_{idx}.mp4"
            logger.info(f"Fetching scene {idx + 1}/{len(queries)} visuals: '{query}' (duration: {dur:.1f}s)")

            downloaded = False
            if Config.is_valid_key(self.pixabay_key):
                downloaded = self._fetch_pixabay_video(query, clip_path, used_video_ids)

            if not downloaded:
                # Procedural dynamic visual clip fallback for this scene
                self._generate_ambient_clip(clip_path, duration=int(dur) + 2, scene_idx=idx)

            clip_paths.append(clip_path)

        return clip_paths

    def _fetch_pixabay_video(self, query: str, output_path: Path, used_ids: set) -> bool:
        """Search and download a strictly relevant HD video clip from Pixabay, prioritizing vertical 9:16."""
        try:
            primaries = self._get_primary_keywords(query)
            search_query = " ".join(primaries[:2]) if primaries else "health"

            hits = self._query_pixabay(search_query)

            # If no hits, check fallback terms
            if not hits:
                for term in primaries:
                    if term in HEALTH_FALLBACK_TERMS:
                        for fb in HEALTH_FALLBACK_TERMS[term]:
                            hits = self._query_pixabay(fb)
                            if hits:
                                break
                    if hits:
                        break

            matched_candidates = []
            for hit in hits:
                hit_id = hit.get("id")
                if hit_id in used_ids:
                    continue

                raw_tags = hit.get("tags", "").lower()
                tag_set = set([t.strip() for t in raw_tags.split(",")])

                # Reject clips with banned non-health tags
                if tag_set.intersection(BANNED_TAGS):
                    continue

                # Strict relevance check: at least one primary topic keyword MUST match tags
                is_relevant = any(pk in raw_tags for pk in primaries)
                if not is_relevant:
                    # Secondary health relevance check for medical terms
                    if any(term in primaries for term in ["glucose", "insulin"]):
                        is_relevant = any(m in raw_tags for m in ["blood", "medical", "diabetes", "doctor", "health"])
                    elif any(term in primaries for term in ["liver", "organ"]):
                        is_relevant = any(m in raw_tags for m in ["liver", "organ", "medical", "anatomy", "health"])

                if not is_relevant:
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

                matched_candidates.append({
                    "id": hit_id,
                    "url": best_video["url"],
                    "w": w,
                    "h": h,
                    "is_vertical": is_vertical,
                    "tags": hit.get("tags")
                })

            if not matched_candidates:
                logger.warning(f"No strictly relevant clips found for '{query}'.")
                return False

            # Sort so true vertical videos (9:16) come FIRST!
            matched_candidates.sort(key=lambda c: (1 if c["is_vertical"] else 0), reverse=True)
            chosen = matched_candidates[0]

            logger.info(
                f"Selected {'VERTICAL 9:16' if chosen['is_vertical'] else 'Horizontal'} Pixabay clip ID {chosen['id']} "
                f"({chosen['w']}x{chosen['h']}): {chosen['tags'][:50]}..."
            )

            with requests.get(chosen["url"], stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)

            used_ids.add(chosen["id"])
            return True

        except Exception as e:
            logger.warning(f"Pixabay video download error for '{query}': {e}")
        return False

    def _query_pixabay(self, query: str) -> list:
        url = (
            f"https://pixabay.com/api/videos/?key={self.pixabay_key}"
            f"&q={requests.utils.quote(query)}&per_page=30"
        )
        res = requests.get(url, timeout=15)
        res.raise_for_status()
        return res.json().get("hits", [])

    def _generate_ambient_clip(self, output_path: Path, duration: int, scene_idx: int):
        """Generate a colorful animated vertical background clip with FFmpeg."""
        colors = [
            ("0x0f172a", "0x1e1b4b", "0x312e81"),
            ("0x064e3b", "0x065f46", "0x047857"),
            ("0x701a75", "0x86198f", "0xa21caf"),
            ("0x1e293b", "0x334155", "0x475569"),
            ("0x1e3a8a", "0x1d4ed8", "0x2563eb")
        ]
        c0, c1, c2 = colors[scene_idx % len(colors)]
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"gradients=s=1080x1920:d={duration}:c0={c0}:c1={c1}:c2={c2}:x0=0:y0=0:x1=1080:y1=1920",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-t", str(duration),
            str(output_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            cmd2 = [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"color=c={c0}:s=1080x1920:d={duration}",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-t", str(duration),
                str(output_path)
            ]
            subprocess.run(cmd2, check=True)
