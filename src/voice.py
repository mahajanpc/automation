import asyncio
import logging
from pathlib import Path
import edge_tts
from src.config import Config

logger = logging.getLogger(__name__)

def format_ass_time(seconds: float) -> str:
    """Format seconds into ASS timestamp format H:MM:SS.cs"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"

def style_phrase_with_highlights(phrase: str) -> str:
    """Highlight ALL-CAPS keywords in vibrant yellow and apply kinetic pop bounce."""
    styled_words = []
    for word in phrase.split():
        clean = word.strip(".,!?:;\"'()[]{}*~-")
        # If word is capitalized/emphasized keyword
        if (clean.isupper() and len(clean) > 1) or word.startswith("*") or word.endswith("*"):
            display_word = word.replace("*", "")
            styled_words.append(f"{{\\c&H0000FFFF&}}{display_word}{{\\c&H00FFFFFF&}}")
        else:
            styled_words.append(word)

    styled_text = " ".join(styled_words)
    # Kinetic pop zoom bounce (scale to 115% then settle to 100%)
    pop_effect = "{\\t(0,100,\\fscx115\\fscy115)\\t(100,200,\\fscx100\\fscy100)}"
    return f"{pop_effect}{styled_text}"

class VoiceSynthesizer:
    def __init__(self, voice_name: str = None):
        self.voice_name = voice_name or Config.VOICE_NAME

    async def _generate_multi_scene_async(self, scenes: list, audio_path: Path, ass_path: Path) -> list[float]:
        """
        Synthesize pure native Telugu speech (Shruti female voice)
        and generate dynamic, kinetic moving ASS subtitles that pop with the audio pace.
        """
        full_telugu_text = " ".join([s.telugu_speech.rstrip(".") + "." for s in scenes])

        communicate = edge_tts.Communicate(full_telugu_text, self.voice_name)
        submaker = edge_tts.SubMaker()

        with open(audio_path, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "SentenceBoundary":
                    submaker.feed(chunk)

        cues = submaker.cues
        scene_durations = []

        # Map cues to scenes
        aligned_dialogues = []
        for idx, cue in enumerate(cues):
            start_sec = cue.start.total_seconds()
            end_sec = cue.end.total_seconds()
            dur = max(end_sec - start_sec, 2.5)
            scene_durations.append(dur)

            scene_idx = min(idx, len(scenes) - 1)
            target_scene = scenes[scene_idx]

            # Get popping phrases for this scene
            phrases = getattr(target_scene, "subtitles", [])
            if not phrases:
                raw_text = getattr(target_scene, "tenglish_subtitle", "")
                words = raw_text.split()
                chunk_sz = max(2, len(words) // 3) if len(words) > 3 else len(words)
                phrases = [" ".join(words[i:i+chunk_sz]) for i in range(0, len(words), chunk_sz)] if words else ["Health Tip"]

            # Distribute scene duration evenly across the short popping phrases
            m_count = len(phrases)
            p_dur = dur / m_count

            for p_idx, phrase in enumerate(phrases):
                p_start = start_sec + (p_idx * p_dur)
                p_end = p_start + p_dur
                start_fmt = format_ass_time(p_start)
                end_fmt = format_ass_time(p_end)
                pop_styled_phrase = style_phrase_with_highlights(phrase)

                aligned_dialogues.append(
                    f"Dialogue: 0,{start_fmt},{end_fmt},PopStyle,,0,0,0,,{pop_styled_phrase}"
                )

        while len(scene_durations) < len(scenes):
            scene_durations.append(5.0)

        # Build ASS file with exact Instagram Reels safe-zone styling:
        # - PlayResX: 1080, PlayResY: 1920 (Exact 9:16 Canvas)
        # - Alignment: 2 (Bottom Center)
        # - MarginV: 440 (Safe from bottom captions/username UI, well below top header)
        # - MarginR: 160 (Safe from right-hand like/comment/share buttons)
        # - Fontsize: 52 with bold outline and soft shadow
        ass_content = f"""[Script Info]
Title: Instagram Reel Subtitles
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: PopStyle,{Config.SUBTITLE_FONT},52,&H00FFFFFF,&H0000FFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4.5,2.5,2,80,160,440,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(aligned_dialogues) + "\n"

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        return scene_durations[:len(scenes)]

    def generate(self, scenes: list, output_name: str = "voice") -> tuple[Path, Path, list[float]]:
        """
        Synthesize native Telugu speech and return (audio_path, ass_path, scene_durations).
        """
        Config.ensure_dirs()
        audio_path = Config.TEMP_DIR / f"{output_name}.mp3"
        ass_path = Config.TEMP_DIR / f"{output_name}.ass"

        logger.info(f"Synthesizing native Telugu female voiceover using '{self.voice_name}'...")
        scene_durations = asyncio.run(self._generate_multi_scene_async(scenes, audio_path, ass_path))
        logger.info(f"Voiceover saved to {audio_path}")
        logger.info(f"Moving popping ASS subtitles saved to {ass_path}")
        return audio_path, ass_path, scene_durations
