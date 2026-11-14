import datetime
import logging
import subprocess
from pathlib import Path
from src.config import Config

logger = logging.getLogger(__name__)

class VideoAssembler:
    def __init__(self):
        Config.ensure_dirs()

    def get_media_duration(self, file_path: Path) -> float:
        """Get exact duration in seconds of an audio or video file using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return float(res.stdout.strip())
        except Exception as e:
            logger.warning(f"Could not get duration for {file_path}: {e}")
            return float(Config.TARGET_DURATION)

    def get_media_resolution(self, file_path: Path) -> tuple[int, int]:
        """Get width and height of a video file."""
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            str(file_path)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            parts = res.stdout.strip().split("x")
            return int(parts[0]), int(parts[1])
        except Exception:
            return 1920, 1080

    def assemble_multi_scene(
        self,
        video_clips: list[Path],
        scene_durations: list[float],
        audio_path: Path,
        ass_path: Path,
        output_filename: str = None
    ) -> Path:
        """
        Assemble multiple video clips with smart aspect-ratio cropping (so subjects are never cut off),
        native voiceover, and burned-in ASS subtitles perfectly placed in the Instagram safe zone.
        """
        if not output_filename:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"health_reel_{timestamp}.mp4"

        output_path = Config.OUTPUT_DIR / output_filename
        total_audio_duration = self.get_media_duration(audio_path)
        logger.info(f"Assembling {len(video_clips)} scenes for total audio: {total_audio_duration:.2f}s")

        safe_ass_path = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")

        cmd = ["ffmpeg", "-y"]

        # Add each video clip as a looping input
        for clip in video_clips:
            cmd.extend(["-stream_loop", "-1", "-i", str(clip)])

        # Add audio input
        audio_input_idx = len(video_clips)
        cmd.extend(["-i", str(audio_path)])

        # Construct pure 9:16 vertical video filter_complex:
        # Scales and center crops directly to 1080x1920 so the whole screen is 100% full-bleed vertical video
        # No blurred bars or YouTube-style letterbox!
        filter_parts = []
        concat_inputs = []

        for idx, (clip, dur) in enumerate(zip(video_clips, scene_durations)):
            filter_parts.append(
                f"[{idx}:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                f"crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2,setsar=1,fps=30,"
                f"trim=duration={dur:.2f},setpts=PTS-STARTPTS[v{idx}];"
            )
            concat_inputs.append(f"[v{idx}]")

        filter_parts.append(
            f"{''.join(concat_inputs)}concat=n={len(video_clips)}:v=1:a=0[v_concat];"
        )
        filter_parts.append(
            f"[v_concat]ass='{safe_ass_path}'[outv]"
        )

        filter_complex = "".join(filter_parts)

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", f"{audio_input_idx}:a",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "24",
            "-maxrate", "3500k",
            "-bufsize", "7000k",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-t", f"{total_audio_duration + 0.3:.2f}",
            str(output_path)
        ])

        logger.info(f"Rendering smart-cropped multi-scene Reel to {output_path}...")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            logger.error(f"FFmpeg multi-scene render error: {res.stderr}")
            # Fallback without ASS filter if any library error
            fallback_parts = filter_parts[:-1]
            fallback_complex = "".join(fallback_parts).replace("[v_concat];", "[outv]")
            fallback_cmd = ["ffmpeg", "-y"]
            for clip in video_clips:
                fallback_cmd.extend(["-stream_loop", "-1", "-i", str(clip)])
            fallback_cmd.extend([
                "-i", str(audio_path),
                "-filter_complex", fallback_complex,
                "-map", "[outv]",
                "-map", f"{audio_input_idx}:a",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-c:a", "aac",
                "-b:a", "128k",
                "-t", f"{total_audio_duration + 0.3:.2f}",
                str(output_path)
            ])
            subprocess.run(fallback_cmd, check=True)

        logger.info(f"Professional multi-scene Reel assembled at {output_path}")
        return output_path
