#!/usr/bin/env python3
import argparse
import json
import logging
import sys
from pathlib import Path

from src.config import Config
from src.generator import ContentGenerator
from src.voice import VoiceSynthesizer
from src.media import MediaFetcher
from src.video import VideoAssembler
from src.uploader import MediaUploader
from src.instagram import InstagramPublisher
from src.mailer import EmailNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("HealthReelBot")

STATE_FILE = Config.ROOT_DIR / "current_topic_index.txt"

def get_next_topic(topics_file: Path) -> dict:
    """Select the next topic sequentially from the 120 topics list."""
    if not topics_file.exists():
        return {"id": 1, "category": "Nutrition and food", "topic": "Benefits of eating soaked almonds"}

    with open(topics_file, "r", encoding="utf-8") as f:
        topics = json.load(f)

    if not topics:
        return {"id": 1, "category": "General Health", "topic": "Benefits of daily hydration"}

    current_idx = 0
    if STATE_FILE.exists():
        try:
            current_idx = int(STATE_FILE.read_text().strip())
        except Exception:
            current_idx = 0

    topic_obj = topics[current_idx % len(topics)]

    # Advance index for the next daily run
    next_idx = (current_idx + 1) % len(topics)
    STATE_FILE.write_text(str(next_idx))

    return topic_obj

def main():
    parser = argparse.ArgumentParser(description="Automated Daily Health Reel Creator (Native Telugu Audio + Tenglish Subtitles + Multi-scene Visuals)")
    parser.add_argument("--topic", type=str, help="Override and run a specific health topic")
    parser.add_argument("--category", type=str, default="Health & Wellness", help="Topic category")
    parser.add_argument("--mode", choices=["review", "publish", "dry-run"], default=Config.EXECUTION_MODE,
                        help="Execution mode: 'review' (email video for manual post), 'publish' (live to IG), or 'dry-run'")
    parser.add_argument("--mock", action="store_true", help="Use offline test data without API calls")
    parser.add_argument("--type", choices=["reel", "story"], default="reel", help="Instagram media type")
    args = parser.parse_args()

    logger.info("==================================================")
    logger.info("   Starting Multi-Scene Health Reel Pipeline      ")
    logger.info(f"   Mode: {args.mode.upper()} | Voice: {Config.VOICE_NAME} | Target: {Config.TARGET_DURATION}s")
    logger.info("==================================================")

    Config.ensure_dirs()

    # Step 1: Sequential Topic Selection (from 120 Health Topics)
    if args.topic:
        topic_info = {"id": 0, "category": args.category, "topic": args.topic}
    else:
        topic_info = get_next_topic(Config.ROOT_DIR / "topics.json")

    topic_title = topic_info["topic"]
    topic_category = topic_info["category"]
    logger.info(f"Today's Topic (#{topic_info.get('id', 0)}): '{topic_title}' [{topic_category}]")

    # Step 2: Content Generation with Gemini (Multi-scene Dual Architecture)
    generator = ContentGenerator(api_key=None if args.mock else Config.GEMINI_API_KEY)
    script = generator.generate(topic_title, topic_category)
    logger.info("Script Generated:")
    logger.info(f"  Hook: {script.hook}")
    logger.info(f"  Scenes count: {len(script.scenes)}")
    for i, s in enumerate(script.scenes, 1):
        logger.info(f"    Scene {i} [Speech: {s.telugu_speech[:30]}... | Sub: {s.tenglish_subtitle[:30]}... | Visual: '{s.visual_query}']")

    # Step 3: Voiceover & Subtitles with Edge-TTS (Pure Telugu Speech -> Native Pronunciation)
    voice_synth = VoiceSynthesizer(Config.VOICE_NAME)
    audio_path, srt_path, scene_durations = voice_synth.generate(script.scenes)

    # Step 4: Multi-clip Visual Fetching (Pixabay HD clips per scene)
    media_fetcher = MediaFetcher(
        pixabay_key=None if args.mock else Config.PIXABAY_API_KEY,
        pexels_key=None if args.mock else Config.PEXELS_API_KEY
    )
    queries = [s.visual_query for s in script.scenes]
    video_clips = media_fetcher.get_multiple_background_clips(queries, scene_durations)

    # Step 5: Video Assembly (Multi-clip Montage + Tenglish Subtitles + 9:16 Vertical Crop)
    assembler = VideoAssembler()
    final_video = assembler.assemble_multi_scene(video_clips, scene_durations, audio_path, srt_path)
    logger.info(f"Final Multi-scene 30s Reel assembled: {final_video}")

    # Step 6: Mode Dispatch
    if args.mode == "dry-run":
        logger.info("==================================================")
        logger.info("DRY-RUN COMPLETE: Multi-scene video rendered locally.")
        logger.info(f"Video file: {final_video}")
        logger.info("Caption:\n" + script.caption)
        logger.info("==================================================")
        return

    # Upload to Cloudinary for safe cloud preview link
    public_url = None
    if Config.is_valid_key(Config.CLOUDINARY_URL):
        try:
            uploader = MediaUploader()
            public_url = uploader.upload_video(final_video)
        except Exception as e:
            logger.warning(f"Could not upload to Cloudinary: {e}")

    # Save current reel state for Web Dashboard
    reel_state = {
        "topic": topic_title,
        "category": topic_category,
        "hook": script.hook,
        "video_path": str(final_video),
        "video_filename": final_video.name,
        "cloudinary_url": public_url,
        "caption": script.caption,
        "scenes": [
            {
                "telugu_speech": s.telugu_speech,
                "subtitles": getattr(s, "subtitles", [s.tenglish_subtitle]),
                "visual_query": s.visual_query
            }
            for s in script.scenes
        ],
        "status": "ready_for_review",
        "published_post_id": None,
        "created_at": datetime.datetime.now().isoformat()
    }
    state_file = Config.ROOT_DIR / "current_reel.json"
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(reel_state, f, indent=2, ensure_ascii=False)

    if args.mode == "review":
        # EMAIL NOTIFICATION MODE (Draft & Human Review)
        logger.info("Dispatching review email with multi-scene video and caption...")
        mailer = EmailNotifier()
        mailer.send_review_email(
            topic=topic_title,
            category=topic_category,
            telugu_script=script.full_tenglish_text,
            caption=script.caption,
            video_url=public_url,
            local_video_path=final_video
        )
        logger.info("==================================================")
        logger.info("REVIEW DISPATCHED: Multi-scene Reel is ready for you to check and post!")
        logger.info(f"Local file: {final_video}")
        if public_url:
            logger.info(f"Cloud stream link: {public_url}")
        logger.info("Check your email for the video and ready-to-copy caption.")
        logger.info("==================================================")
        return

    elif args.mode == "publish":
        # DIRECT PUBLISH TO INSTAGRAM MODE
        if not public_url:
            logger.error("Publish mode requires CLOUDINARY_URL to generate a public link for Instagram API.")
            sys.exit(1)

        missing = Config.validate_for_publish()
        if missing:
            logger.error(f"Cannot publish live: Missing credentials: {', '.join(missing)}")
            sys.exit(1)

        publisher = InstagramPublisher()
        result = publisher.publish_video(
            video_url=public_url,
            caption=script.caption,
            media_type="STORIES" if args.type == "story" else "REELS"
        )
        post_id = result.get("id")
        reel_state["status"] = "published"
        reel_state["published_post_id"] = post_id
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(reel_state, f, indent=2, ensure_ascii=False)
        logger.info("==================================================")
        logger.info(f"SUCCESS: Published directly to Instagram! Post ID: {result.get('id')}")
        logger.info("==================================================")

if __name__ == "__main__":
    main()
