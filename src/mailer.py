import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from src.config import Config

logger = logging.getLogger(__name__)

class EmailNotifier:
    def __init__(self):
        self.smtp_server = Config.SMTP_SERVER
        self.smtp_port = Config.SMTP_PORT
        self.smtp_email = Config.SMTP_EMAIL
        self.smtp_password = Config.SMTP_PASSWORD
        self.recipient_email = Config.RECIPIENT_EMAIL or self.smtp_email

    def is_configured(self) -> bool:
        return bool(self.smtp_email and self.smtp_password and not self.smtp_email.startswith("your_"))

    def send_review_email(
        self,
        topic: str,
        category: str,
        telugu_script: str,
        caption: str,
        video_url: str = None,
        local_video_path: Path = None
    ) -> bool:
        """
        Send an email notification with the generated video, Telugu script, and Instagram caption
        for user review and manual posting.
        """
        if not self.is_configured():
            logger.warning("SMTP email credentials are not configured in .env. Review email will be skipped.")
            logger.info("================ REVIEW READY (SIMULATED EMAIL) ================")
            logger.info(f"Topic: {topic} ({category})")
            logger.info(f"Telugu Script:\n{telugu_script}")
            logger.info(f"Caption:\n{caption}")
            if video_url:
                logger.info(f"Cloud Video URL: {video_url}")
            if local_video_path:
                logger.info(f"Local Video: {local_video_path}")
            logger.info("================================================================")
            return False

        try:
            logger.info(f"Sending review email to {self.recipient_email}...")
            msg = MIMEMultipart()
            msg["From"] = f"Health Reel Bot <{self.smtp_email}>"
            msg["To"] = self.recipient_email
            msg["Subject"] = f"🎬 [Review Ready] Instagram Reel: {topic}"

            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
                <h2 style="color: #0d9488;">🌿 Daily Health Reel Review Ready</h2>
                <p>Hello! Your automated 30-second Telugu health reel is ready for your review.</p>
                
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                    <tr style="background: #f8fafc;"><td style="padding: 8px; font-weight: bold;">Category:</td><td style="padding: 8px;">{category}</td></tr>
                    <tr><td style="padding: 8px; font-weight: bold;">Topic:</td><td style="padding: 8px;">{topic}</td></tr>
                    {f'<tr style="background: #f8fafc;"><td style="padding: 8px; font-weight: bold;">Video URL:</td><td style="padding: 8px;"><a href="{video_url}" style="color: #2563eb; font-weight: bold;">Watch / Download Video</a></td></tr>' if video_url else ''}
                </table>

                <div style="background: #f1f5f9; padding: 15px; border-radius: 6px; margin-bottom: 20px;">
                    <h4 style="margin-top: 0; color: #1e293b;">🎙️ Tenglish Voiceover Script:</h4>
                    <p style="font-size: 16px; color: #0f172a; white-space: pre-line;">{telugu_script}</p>
                </div>

                <div style="background: #fdf2f8; padding: 15px; border-radius: 6px; margin-bottom: 20px;">
                    <h4 style="margin-top: 0; color: #9d174d;">📋 Instagram Caption & Hashtags (Copy & Paste):</h4>
                    <p style="font-size: 14px; color: #334155; white-space: pre-line;">{caption}</p>
                </div>

                <p style="font-size: 13px; color: #64748b;">
                    <b>Next Steps:</b> Review the video, make any edits, and post it to Instagram at your preferred peak time. 
                    To train the bot with your feedback, run: <br>
                    <code>python feedback.py --add "Your feedback here"</code>
                </p>
            </body>
            </html>
            """
            msg.attach(MIMEText(html_body, "html"))

            # Attach video if under 10MB for fast delivery
            if local_video_path and local_video_path.exists():
                file_size_mb = local_video_path.stat().st_size / (1024 * 1024)
                if file_size_mb <= 10.0:
                    logger.info(f"Attaching video file ({file_size_mb:.1f} MB)...")
                    with open(local_video_path, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f"attachment; filename={local_video_path.name}")
                    msg.attach(part)
                else:
                    logger.info(f"Video size ({file_size_mb:.1f} MB) is large for email attachment. Saved locally and in cloud.")

            # Connect and send with generous timeout for video uploads
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=120) as server:
                server.starttls()
                server.login(self.smtp_email, self.smtp_password)
                server.send_message(msg)

            logger.info("Review email sent successfully!")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

