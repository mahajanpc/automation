import asyncio
import logging
import re
import subprocess
from pathlib import Path
import edge_tts
from src.config import Config

logger = logging.getLogger(__name__)

# Emoji pattern to remove unrenderable glyphs that cause square boxes in fontconfig
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA70-\U0001FAFF"
    "\u2600-\u26FF"          # misc symbols
    "\u2700-\u27BF"          # dingbats
    "]+",
    flags=re.UNICODE
)

def clean_for_ass(text: str) -> str:
    """Remove emojis and special characters that cannot render in Telugu fonts."""
    cleaned = EMOJI_PATTERN.sub("", text)
    # Remove leftover symbols like [] {} |
    cleaned = cleaned.replace("[", "").replace("]", "").replace("{", "").replace("}", "")
    return cleaned.strip()

def format_ass_time(seconds: float) -> str:
    """Format seconds into ASS timestamp format H:MM:SS.cs"""
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"

def style_telugu_phrase(phrase: str) -> str:
    """
    Format Telugu subtitle phrase with vibrant golden-yellow highlights on starred words or keywords.
    Adds a subtle, professional kinetic pop animation on entrance.
    """
    cleaned = clean_for_ass(phrase)

    # Check for *keyword* pattern
    if "*" in cleaned:
        # Replace *word* with yellow highlight tags
        # In ASS, &H0000FFFF& is pure yellow (BBGGRR -> Blue 00, Green FF, Red FF)
        parts = re.split(r"(\*[^*]+\*)", cleaned)
        styled_parts = []
        for p in parts:
            if p.startswith("*") and p.endswith("*") and len(p) > 2:
                word_clean = p[1:-1].strip()
                styled_parts.append(f"{{\\c&H0000FFFF&}}{word_clean}{{\\c&H00FFFFFF&}}")
            else:
                styled_parts.append(p)
        styled_text = "".join(styled_parts)
    else:
        # If words in ALL CAPS (for Tenglish fallback) or first 2 words
        words = cleaned.split()
        styled_words = []
        for i, word in enumerate(words):
            if (word.isupper() and len(word) > 1) or i == 0:
                styled_words.append(f"{{\\c&H0000FFFF&}}{word}{{\\c&H00FFFFFF&}}")
            else:
                styled_words.append(word)
        styled_text = " ".join(styled_words)

    # Clean, subtle pop scale: slight zoom to 106% over 80ms, settle to 100% over 80ms
    pop_effect = "{\\t(0,80,\\fscx106\\fscy106)\\t(80,160,\\fscx100\\fscy100)}"
    return f"{pop_effect}{styled_text}"

class VoiceSynthesizer:
    def __init__(self, voice_name: str = None):
        self.voice_name = voice_name or Config.VOICE_NAME

    def _get_file_duration(self, audio_file: Path) -> float:
        """Get exact duration in seconds of an audio file using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_file)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return float(res.stdout.strip())
        except Exception as e:
            logger.warning(f"Error measuring audio duration of {audio_file}: {e}")
            return 5.0

    async def _synthesize_single_scene_async(self, text: str, output_path: Path) -> list:
        """Synthesize a single scene's speech and extract sentence boundaries."""
        clean_text = clean_for_ass(text)
        if not clean_text.endswith((".", "!", "?")):
            clean_text += "."

        communicate = edge_tts.Communicate(clean_text, self.voice_name)
        cues = []
        with open(output_path, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "SentenceBoundary":
                    cues.append({
                        "offset": chunk["offset"] / 10_000_000,
                        "duration": chunk["duration"] / 10_000_000,
                        "text": chunk.get("text", "")
                    })
        return cues

    async def _generate_pipeline_async(
        self,
        scenes: list,
        final_audio_path: Path,
        ass_path: Path,
        hook_title: str = "",
        cta_text: str = ""
    ) -> list[float]:
        """
        Synthesize native Telugu speech for each scene with exact duration tracking,
        and generate synchronized ASS subtitles with platform-safe margins.
        """
        Config.ensure_dirs()
        scene_audio_files = []

        # 1. Synthesize all scenes in parallel
        synth_tasks = []
        for idx, scene in enumerate(scenes):
            scene_mp3 = Config.TEMP_DIR / f"scene_voice_{idx}.mp3"
            scene_audio_files.append(scene_mp3)
            synth_tasks.append(self._synthesize_single_scene_async(scene.telugu_speech, scene_mp3))

        await asyncio.gather(*synth_tasks)

        # 2. Measure exact duration of each scene's audio
        scene_durations = []
        for scene_mp3 in scene_audio_files:
            dur = self._get_file_duration(scene_mp3)
            scene_durations.append(max(dur, 2.5))

        # 3. Concatenate all scene audios into one master voiceover track with FFmpeg
        concat_list_file = Config.TEMP_DIR / "concat_voice_list.txt"
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for scene_mp3 in scene_audio_files:
                f.write(f"file '{scene_mp3.resolve()}'\n")

        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_file),
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            str(final_audio_path)
        ]
        res = subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            logger.error(f"Error concatenating scene audios: {res.stderr}")
            import shutil
            shutil.copy(scene_audio_files[0], final_audio_path)

        total_audio_duration = self._get_file_duration(final_audio_path)
        logger.info(f"Master voiceover synthesized: {total_audio_duration:.2f}s total across {len(scenes)} scenes.")

        # 4. Generate synchronized ASS subtitles
        aligned_dialogues = []
        accumulated_time = 0.0

        for idx, (scene, dur) in enumerate(zip(scenes, scene_durations)):
            scene_start = accumulated_time
            scene_end = scene_start + dur

            # Subtitle phrases for this scene
            phrases = getattr(scene, "subtitles", [])
            if not phrases:
                raw_speech = getattr(scene, "telugu_speech", "")
                words = clean_for_ass(raw_speech).split()
                chunk_sz = max(3, len(words) // 2) if len(words) > 3 else len(words)
                phrases = [" ".join(words[i:i+chunk_sz]) for i in range(0, len(words), chunk_sz)] if words else ["ఆరోగ్య చిట్కా"]

            # In the final scene, ensure concluding CTA is smoothly integrated
            if idx == len(scenes) - 1 and cta_text:
                clean_cta = clean_for_ass(cta_text)
                if clean_cta and clean_cta not in phrases:
                    phrases.append(f"*{clean_cta}*")

            num_phrases = len(phrases)
            phrase_dur = dur / num_phrases

            for p_idx, phrase in enumerate(phrases):
                p_start = scene_start + (p_idx * phrase_dur)
                p_end = p_start + phrase_dur
                start_fmt = format_ass_time(p_start)
                end_fmt = format_ass_time(p_end)
                styled_text = style_telugu_phrase(phrase)

                aligned_dialogues.append(
                    f"Dialogue: 0,{start_fmt},{end_fmt},TeluguCaption,,0,0,0,,{styled_text}"
                )

            # Opening Hook Badge for first scene (Top Center, 150px from top)
            if idx == 0 and hook_title:
                hook_end_time = min(scene_end, 3.8)
                h_start_fmt = format_ass_time(scene_start)
                h_end_fmt = format_ass_time(hook_end_time)
                clean_hook = clean_for_ass(hook_title).replace("*", "")
                aligned_dialogues.append(
                    f"Dialogue: 2,{h_start_fmt},{h_end_fmt},HookHeader,,0,0,0,,{{\\t(0,100,\\fscx104\\fscy104)\\t(100,200,\\fscx100\\fscy100)}}{clean_hook}"
                )

            accumulated_time = scene_end

        # Build ASS stylesheet with exact mobile safe margins:
        # - Canvas: 1080x1920
        # - Font: Noto Sans Telugu Bold
        # - Caption Fontsize: 60 (Primary white &H00FFFFFF& with black outline 4.8 and subtle shadow 2.0)
        # - Bottom Margin: 420 (safe from bottom Reel caption UI)
        # - Right Margin: 160 (safe from right-hand like/share buttons)
        # - Hook Header: Fontsize 48, Top Center (MarginV=150 from top)
        font_name = Config.SUBTITLE_FONT or "Noto Sans Telugu"
        ass_content = f"""[Script Info]
Title: Instagram Telugu Reel Subtitles
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TeluguCaption,{font_name},60,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4.8,2.0,2,90,160,420,1
Style: HookHeader,{font_name},48,&H0000FFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4.5,2.0,8,60,60,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(aligned_dialogues) + "\n"

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        return scene_durations

    def generate(
        self,
        scenes: list,
        output_name: str = "voice",
        hook_title: str = "",
        cta_text: str = ""
    ) -> tuple[Path, Path, list[float]]:
        """
        Synthesize native Telugu speech and return (audio_path, ass_path, scene_durations).
        """
        Config.ensure_dirs()
        audio_path = Config.TEMP_DIR / f"{output_name}.mp3"
        ass_path = Config.TEMP_DIR / f"{output_name}.ass"

        logger.info(f"Synthesizing native Telugu female voiceover using '{self.voice_name}'...")
        scene_durations = asyncio.run(
            self._generate_pipeline_async(scenes, audio_path, ass_path, hook_title, cta_text)
        )
        logger.info(f"Voiceover saved to {audio_path}")
        logger.info(f"Synchronized Telugu ASS subtitles saved to {ass_path}")
        return audio_path, ass_path, scene_durations
