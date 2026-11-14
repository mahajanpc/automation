import time
import logging
import requests
from src.config import Config

logger = logging.getLogger(__name__)

class InstagramPublisher:
    GRAPH_API_VERSION = "v21.0"
    BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

    def __init__(self, account_id: str = None, access_token: str = None):
        self.account_id = account_id or Config.INSTAGRAM_ACCOUNT_ID
        self.access_token = access_token or Config.IG_ACCESS_TOKEN

    def publish_video(self, video_url: str, caption: str, media_type: str = "REELS") -> dict:
        """
        Publish a video as an Instagram Reel or Story via official Graph API.
        media_type can be 'REELS' or 'STORIES'.
        """
        if not self.account_id or not self.access_token:
            raise ValueError("INSTAGRAM_ACCOUNT_ID and IG_ACCESS_TOKEN must be configured.")

        media_type = media_type.upper()
        if media_type not in ("REELS", "STORIES"):
            raise ValueError("media_type must be either 'REELS' or 'STORIES'")

        logger.info(f"Step 1: Creating Instagram media container ({media_type})...")
        container_id = self._create_container(video_url, caption, media_type)

        logger.info(f"Step 2: Waiting for Instagram to process container {container_id}...")
        self._wait_for_processing(container_id)

        logger.info(f"Step 3: Publishing container {container_id} to Instagram...")
        publish_res = self._publish_container(container_id)
        
        post_id = publish_res.get("id")
        logger.info(f"Successfully published! Post ID: {post_id}")
        return publish_res

    def _create_container(self, video_url: str, caption: str, media_type: str) -> str:
        url = f"{self.BASE_URL}/{self.account_id}/media"
        payload = {
            "media_type": media_type,
            "video_url": video_url,
            "access_token": self.access_token
        }
        if media_type == "REELS":
            payload["caption"] = caption
            payload["share_to_feed"] = "true"

        res = requests.post(url, data=payload, timeout=30)
        res_data = res.json()
        if res.status_code != 200 or "id" not in res_data:
            raise RuntimeError(f"Failed to create media container: {res_data}")

        return res_data["id"]

    def _wait_for_processing(self, container_id: str, max_retries: int = 30, interval: int = 5):
        url = f"{self.BASE_URL}/{container_id}"
        params = {
            "fields": "status_code,status",
            "access_token": self.access_token
        }

        for attempt in range(1, max_retries + 1):
            res = requests.get(url, params=params, timeout=15)
            data = res.json()
            status_code = data.get("status_code")
            logger.info(f"Container status (check {attempt}/{max_retries}): {status_code}")

            if status_code == "FINISHED":
                return
            elif status_code == "ERROR":
                raise RuntimeError(f"Instagram media processing failed: {data}")
            elif status_code == "EXPIRED":
                raise RuntimeError("Instagram media container expired before publishing.")

            time.sleep(interval)

        raise TimeoutError("Timed out waiting for Instagram to process video container.")

    def _publish_container(self, container_id: str) -> dict:
        url = f"{self.BASE_URL}/{self.account_id}/media_publish"
        payload = {
            "creation_id": container_id,
            "access_token": self.access_token
        }
        res = requests.post(url, data=payload, timeout=30)
        data = res.json()
        if res.status_code != 200 or "id" not in data:
            raise RuntimeError(f"Failed to publish media: {data}")
        return data

