import datetime
import logging
import random
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

    def select_background_music(self, mood: str = "calm") -> Path | None:
        """Select a royalty-free background music track matching the topic mood."""
        music_dir = Config.MUSIC_DIR
        if not music_dir.exists():
            return None

        mood_map = {
            "calm": music_dir / "calm_piano.mp3",
            "inspirational": music_dir / "ambient_hope.mp3",
            "acoustic": music_dir / "gentle_acoustic.mp3",
            "upbeat": music_dir / "daybreak.mp3"
        }

        chosen = mood_map.get(mood.lower())
        if chosen and chosen.exists():
            return chosen

        # Fallback to any mp3 in music dir
        all_tracks = list(music_dir.glob("*.mp3"))
        if all_tracks:
            return all_tracks[0]

        # Procedural soothing ambient fallback if no MP3 files exist
        fallback_drone = Config.TEMP_DIR / "ambient_drone.mp3"
        if not fallback_drone.exists():
            try:
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "lavfi",
                    "-i", "aevalsrc=0.06*sin(2*PI*174.61*t)+0.05*sin(2*PI*220*t)+0.04*sin(2*PI*261.63*t):s=44100:d=45",
                    "-af", "lowpass=f=800,volume=0.35",
                    "-c:a", "libmp3lame",
                    str(fallback_drone)
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                return fallback_drone
            except Exception:
                pass

        return None

    def _build_scene_motion_filter(self, idx: int, dur: float) -> str:
        """
        Build distinct, cinematic camera motion per scene to eliminate the slideshow effect:
        - Scene 0 (Hook): Slow, subtle push-in zoom to draw viewer in.
        - Scene 1 (Conflict): Gentle subtle pan right across the subject.
        - Scene 2 (Domino): Slow, subtle pull-out zoom revealing context.
        - Scene 3 (Eye-opener): Gentle subtle pan left.
        - Scene 4 (Hero/CTA): Cinematic subtle zoom towards the focal center.
        """
        mode = idx % 5
        d_fmt = f"{dur:.2f}"

        if mode == 0:
            # Subtle slow push-in zoom (1.00 -> 1.08)
            return (
                f"scale=1080:1920:force_original_aspect_ratio=increase,"
                f"crop=1080:1920,setsar=1,fps=30,"
                f"zoompan=z='min(zoom+0.0006,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,"
                f"trim=duration={d_fmt},setpts=PTS-STARTPTS"
            )
        elif mode == 1:
            # Subtle horizontal pan right
            return (
                f"scale=1240:1920:force_original_aspect_ratio=increase,"
                f"crop=1240:1920,setsar=1,fps=30,"
                f"crop=1080:1920:x='(in_w-1080)*0.15 + (in_w-1080)*0.7*(t/{d_fmt})':y='(in_h-1920)/2',"
                f"trim=duration={d_fmt},setpts=PTS-STARTPTS"
            )
        elif mode == 2:
            # Subtle slow pull-out zoom (1.08 -> 1.00)
            return (
                f"scale=1080:1920:force_original_aspect_ratio=increase,"
                f"crop=1080:1920,setsar=1,fps=30,"
                f"zoompan=z='if(lte(zoom,1.0),1.08,max(1.001,zoom-0.0006))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,"
                f"trim=duration={d_fmt},setpts=PTS-STARTPTS"
            )
        elif mode == 3:
            # Subtle horizontal pan left
            return (
                f"scale=1240:1920:force_original_aspect_ratio=increase,"
                f"crop=1240:1920,setsar=1,fps=30,"
                f"crop=1080:1920:x='(in_w-1080)*0.85 - (in_w-1080)*0.7*(t/{d_fmt})':y='(in_h-1920)/2',"
                f"trim=duration={d_fmt},setpts=PTS-STARTPTS"
            )
        else:
            # Cinematic focus push-in towards center-top
            return (
                f"scale=1080:1920:force_original_aspect_ratio=increase,"
                f"crop=1080:1920,setsar=1,fps=30,"
                f"zoompan=z='min(zoom+0.0007,1.07)':x='iw/2-(iw/zoom/2)':y='ih*0.45-(ih/zoom/2)':d=1:s=1080x1920:fps=30,"
                f"trim=duration={d_fmt},setpts=PTS-STARTPTS"
            )

    def assemble_multi_scene(
        self,
        video_clips: list[Path],
        scene_durations: list[float],
        audio_path: Path,
        ass_path: Path,
        output_filename: str = None,
        music_mood: str = "calm"
    ) -> Path:
        """
        Assemble a professionally edited Instagram Reel:
        - Full-bleed 9:16 vertical video with varied cinematic camera movement per scene.
        - Consistent color grading & subtle vignette.
        - Burning in synchronized Telugu ASS subtitles with high-contrast safe-zone styling.
        - Background music with dynamic audio ducking under narration.
        - Smooth fade-in, fade-out, and perfect audio/video lock.
        """
        if not output_filename:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"health_reel_{timestamp}.mp4"

        output_path = Config.OUTPUT_DIR / output_filename
        total_audio_duration = self.get_media_duration(audio_path)
        logger.info(f"Assembling {len(video_clips)} scenes for total voice duration: {total_audio_duration:.2f}s")

        # Re-verify and ensure exact duration lock
        total_scene_dur = sum(scene_durations)
        if abs(total_scene_dur - total_audio_duration) > 0.05 and scene_durations:
            # Adjust the last scene slightly to achieve exact millisecond match
            diff = total_audio_duration - total_scene_dur
            scene_durations[-1] = max(2.5, scene_durations[-1] + diff)
            logger.info(f"Adjusted final scene duration for exact synchronization: {scene_durations[-1]:.2f}s")

        safe_ass_path = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")

        # Select background music
        bgm_path = self.select_background_music(music_mood)
        has_bgm = bgm_path is not None and bgm_path.exists()
        if has_bgm:
            logger.info(f"Selected royalty-free BGM: {bgm_path.name} (mood: {music_mood})")

        cmd = ["ffmpeg", "-y"]

        # 1. Add video clip inputs
        for clip in video_clips:
            cmd.extend(["-stream_loop", "-1", "-i", str(clip)])

        # 2. Add voiceover audio input
        voice_input_idx = len(video_clips)
        cmd.extend(["-i", str(audio_path)])

        # 3. Add BGM input if present
        bgm_input_idx = voice_input_idx + 1 if has_bgm else None
        if has_bgm:
            cmd.extend(["-stream_loop", "-1", "-i", str(bgm_path)])

        # 4. Construct video filter graph
        filter_parts = []
        concat_inputs = []

        for idx, (clip, dur) in enumerate(zip(video_clips, scene_durations)):
            motion_filter = self._build_scene_motion_filter(idx, dur)
            filter_parts.append(f"[{idx}:v]{motion_filter}[v{idx}];")
            concat_inputs.append(f"[v{idx}]")

        # Concat all motion scenes
        filter_parts.append(f"{''.join(concat_inputs)}concat=n={len(video_clips)}:v=1:a=0[v_concat];")

        # Unified color grading:
        # - Subtle contrast (1.05) & natural saturation (1.12)
        # - Filmic vignette (0.22) to draw focus to center
        # - Smooth fade to black on the final 0.5s
        v_fade_start = max(0.0, total_audio_duration - 0.5)
        filter_parts.append(
            f"[v_concat]eq=contrast=1.05:brightness=0.01:saturation=1.12,"
            f"vignette=angle=PI/5:aspect=1080/1920,"
            f"fade=t=out:st={v_fade_start:.2f}:d=0.5,"
            f"ass='{safe_ass_path}'[outv];"
        )

        # 5. Construct audio filter graph (Audio Ducking)
        if has_bgm:
            # Duck music under voiceover using sidechain compressor
            bgm_vol = Config.BGM_VOLUME
            bgm_fadeout_start = max(0.0, total_audio_duration - 1.5)
            master_fadeout_start = max(0.0, total_audio_duration - 0.4)

            filter_parts.append(
                f"[{bgm_input_idx}:a]volume={bgm_vol:.2f},"
                f"afade=t=in:ss=0:d=1.0,"
                f"afade=t=out:st={bgm_fadeout_start:.2f}:d=1.5[bgm_faded];"
                f"[{voice_input_idx}:a]volume=1.05,asplit=2[voice_for_duck][voice_for_mix];"
                f"[bgm_faded][voice_for_duck]sidechaincompress=threshold=0.10:ratio=4.5:attack=30:release=280[bgm_ducked];"
                f"[voice_for_mix][bgm_ducked]amix=inputs=2:duration=first:dropout_transition=2,"
                f"afade=t=out:st={master_fadeout_start:.2f}:d=0.4[outa]"
            )
        else:
            master_fadeout_start = max(0.0, total_audio_duration - 0.4)
            filter_parts.append(
                f"[{voice_input_idx}:a]volume=1.05,"
                f"afade=t=out:st={master_fadeout_start:.2f}:d=0.4[outa]"
            )

        filter_complex = "".join(filter_parts)

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "[outa]",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "22",
            "-maxrate", "4000k",
            "-bufsize", "8000k",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", f"{total_audio_duration:.2f}",
            str(output_path)
        ])

        logger.info(f"Rendering professionally edited Reel to {output_path}...")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            logger.error(f"FFmpeg render error: {res.stderr}")
            # Resilient fallback: render without ASS filter if font/ass parse error occurs
            logger.warning("Attempting safe fallback render...")
            fallback_parts = []
            for idx, (clip, dur) in enumerate(zip(video_clips, scene_durations)):
                fallback_parts.append(
                    f"[{idx}:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                    f"crop=1080:1920,setsar=1,fps=30,trim=duration={dur:.2f},setpts=PTS-STARTPTS[v{idx}];"
                )
            fallback_parts.append(f"{''.join(concat_inputs)}concat=n={len(video_clips)}:v=1:a=0[outv];")
            fallback_parts.append(f"[{voice_input_idx}:a]volume=1.0[outa]")

            fallback_cmd = ["ffmpeg", "-y"]
            for clip in video_clips:
                fallback_cmd.extend(["-stream_loop", "-1", "-i", str(clip)])
            fallback_cmd.extend(["-i", str(audio_path)])
            fallback_cmd.extend([
                "-filter_complex", "".join(fallback_parts),
                "-map", "[outv]",
                "-map", "[outa]",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-c:a", "aac",
                "-b:a", "128k",
                "-t", f"{total_audio_duration:.2f}",
                str(output_path)
            ])
            subprocess.run(fallback_cmd, check=True)

        logger.info(f"Professional cinematic Reel successfully rendered at {output_path}")
        return output_path
