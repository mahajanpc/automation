import os
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
import cloudinary
import cloudinary.uploader
import cloudinary.api
from src.config import Config

logger = logging.getLogger(__name__)

class MediaUploader:
    def __init__(self, cloudinary_url: str = None):
        import urllib.parse
        self.cloudinary_url = cloudinary_url or Config.CLOUDINARY_URL
        if self.cloudinary_url:
            parsed = urllib.parse.urlparse(self.cloudinary_url)
            self.api_key = parsed.username
            self.api_secret = parsed.password
            self.cloud_name = parsed.hostname
            cloudinary.config(
                cloud_name=self.cloud_name,
                api_key=self.api_key,
                api_secret=self.api_secret,
                secure=True
            )

    def cleanup_old_videos(self, max_age_hours: int = 24) -> int:
        """
        Automatically deletes videos from Cloudinary that are older than max_age_hours (default 24h).
        Keeps Cloudinary free tier storage clean and saves quota automatically.
        """
        if not self.cloudinary_url:
            return 0

        deleted_count = 0
        try:
            logger.info(f"Checking Cloudinary for videos older than {max_age_hours} hours to clean up...")
            res = cloudinary.api.resources(
                resource_type="video",
                type="upload",
                prefix="instagram_automation",
                max_results=50
            )
            resources = res.get("resources", [])
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

            for item in resources:
                public_id = item.get("public_id")
                created_str = item.get("created_at")  # Format: "2026-11-14T10:20:30Z"
                if not public_id or not created_str:
                    continue

                try:
                    # Parse ISO timestamp
                    created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    if created_at < cutoff_time:
                        logger.info(f"Auto-deleting expired video from Cloudinary: {public_id} (created {created_str})...")
                        cloudinary.uploader.destroy(public_id, resource_type="video")
                        deleted_count += 1
                except Exception as ex:
                    logger.warning(f"Could not parse or delete {public_id}: {ex}")

            logger.info(f"Cloudinary cleanup completed: {deleted_count} expired video(s) removed.")
        except Exception as e:
            logger.warning(f"Cloudinary auto-cleanup check error: {e}")

        return deleted_count

    def upload_video(self, file_path: Path, auto_clean: bool = True) -> str:
        """
        Uploads local video to Cloudinary and returns a public HTTPS URL.
        Automatically cleans up old videos to save storage.
        """
        if not self.cloudinary_url:
            raise ValueError("CLOUDINARY_URL is not set. Cannot upload video to public host.")

        if auto_clean:
            self.cleanup_old_videos(max_age_hours=24)

        logger.info(f"Uploading {file_path.name} to Cloudinary...")
        res = cloudinary.uploader.upload_large(
            str(file_path),
            resource_type="video",
            folder="instagram_automation"
        )
        secure_url = res.get("secure_url")
        if not secure_url:
            raise RuntimeError(f"Cloudinary upload failed: {res}")

        logger.info(f"Uploaded successfully to Cloudinary. Public URL: {secure_url}")
        return secure_url
