import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Config:
    # Directories
    ROOT_DIR = BASE_DIR
    OUTPUT_DIR = BASE_DIR / "output"
    TEMP_DIR = BASE_DIR / "temp"
    ASSETS_DIR = BASE_DIR / "assets"
    MUSIC_DIR = BASE_DIR / "assets" / "music"

    # API Keys & Credentials
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
    PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
    INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID", "")
    IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", "")
    CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "")

    # Voice & Media Defaults (Telugu & 30s)
    # Available Telugu voices: te-IN-ShrutiNeural (Female - Recommended), te-IN-MohanNeural (Male)
    VOICE_NAME = os.getenv("VOICE_NAME", "te-IN-ShrutiNeural")
    TARGET_DURATION = int(os.getenv("TARGET_DURATION_SECONDS", "30"))
    SUBTITLE_FONT = os.getenv("SUBTITLE_FONT", "Noto Sans Telugu")
    BGM_VOLUME = float(os.getenv("BGM_VOLUME", "0.20"))

    # Email Notification Settings
    SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "")

    # Execution Mode: "review" (email video for manual post) or "publish" (live to Instagram)
    EXECUTION_MODE = os.getenv("EXECUTION_MODE", "review")

    @classmethod
    def ensure_dirs(cls):
        """Create necessary working directories."""
        cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        cls.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        cls.ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        cls.MUSIC_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def is_valid_key(cls, key: str) -> bool:
        """Check if an API key is set and not a placeholder."""
        return bool(key) and not key.startswith("your_")

    @classmethod
    def validate_for_publish(cls) -> list[str]:
        """Check if all required credentials for live publishing are present."""
        missing = []
        if not cls.is_valid_key(cls.GEMINI_API_KEY):
            missing.append("GEMINI_API_KEY")
        if not cls.is_valid_key(cls.INSTAGRAM_ACCOUNT_ID):
            missing.append("INSTAGRAM_ACCOUNT_ID")
        if not cls.is_valid_key(cls.IG_ACCESS_TOKEN):
            missing.append("IG_ACCESS_TOKEN")
        if not cls.is_valid_key(cls.CLOUDINARY_URL):
            missing.append("CLOUDINARY_URL")
        return missing
