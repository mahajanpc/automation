# 🌿 Daily Telugu Health Reel Automation (Review & Manual Post)

An automated **Telugu Health Reel generator** designed for 30-second educational videos with 100% evidence-based medical information, human review via email, and continuous self-improvement.

---

## 💡 Answers to Key Questions

### 1. Why Gemini API Key?
Gemini acts as the **medical research brain**:
- Takes your daily health topic from the 120-topic list.
- Researches and generates a **medically accurate 30-second Telugu script** (based strictly on WHO, ICMR, and clinical consensus).
- Injects previous **user feedback** to continuously improve wording, tone, and pacing.
- Formulates English search keywords for matching footage and writes ready-to-copy Telugu Instagram captions & hashtags.

### 2. Why Pexels API Key?
Pexels provides **100% free vertical (9:16) stock video clips** (e.g. soaking almonds, drinking clean water, morning walking, sleep) without watermarks and with full commercial rights.

### 3. Can Gemini generate video directly?
- **Honest technical reality:** Gemini 1.5/2.5 Flash is a **multimodal language model** (text, audio, image analysis). Google's dedicated AI video generator is called **Veo**, which is not yet an open/free public developer API.
- Third-party AI video generators (Runway Gen-3, Kling, Sora, Pika) cost **\$0.20 to \$1.00 per video**, meaning they are NOT free.
- **The best 100% free approach:** Gemini writes the script + Pexels supplies high-definition real-life health footage (with a procedural ambient background fallback) + Edge-TTS provides the natural Telugu voice + FFmpeg renders the complete Reel with Telugu subtitles.

### 4. Voice Name & Target Duration
- **Duration:** Exactly **30 seconds** (target duration).
- **Language:** **Telugu (తెలుగు)**.
- **Available Free Telugu Neural Voices:**
  - `te-IN-MohanNeural` (Male, clear and authoritative doctor/educator tone - **Default**)
  - `te-IN-ShrutiNeural` (Female, warm and friendly tone)

---

## 🎯 Review & Draft Workflow (Human-in-the-Loop)

Instagram's official Graph API does **not** allow external apps to save directly into your personal mobile app "Drafts" folder. 

To solve this, the bot operates in **Review Mode**:
1. Every day at the scheduled time, the bot creates the 30-second Telugu video.
2. It sends an **Email to your inbox** containing:
   - The video file attached (or high-speed Cloudinary download link).
   - The exact Telugu voiceover script.
   - The ready-to-copy Instagram caption and relevant Telugu hashtags (`#Arogyam #TeluguHealth`).
3. You review the video, ensure you are satisfied, and post it to Instagram at your chosen peak time.

---

## 🔄 Self-Improvement & Feedback Loop

The bot learns and improves day by day based on your feedback:
```bash
python feedback.py --add "Use simpler Telugu words for vitamins and keep a slightly slower speech pace"
```
Every time the bot runs, it loads all past feedback notes from [feedback_history.json](file:///home/mahajan-ashok/automation/feedback_history.json) and instructs Gemini to strictly incorporate your preferences into future generations.

To view current feedback history:
```bash
python feedback.py --list
```

---

## 📚 120 Curated Health Topics

The bot rotates through 120 evidence-based health topics sequentially (one per day) stored in [topics.json](file:///home/mahajan-ashok/automation/topics.json):
1. **Nutrition & Food** (Topics 1–10: soaked almonds, water requirements, proteins, sugar, iron, B12...)
2. **Fitness & Exercise** (Topics 11–20: 30-min walking, walking vs running, strength training...)
3. **Sleep & Recovery** (Topics 21–30: 7–9 hours sleep, screen time, sleep cycles...)
4. **Mental Health** (Topics 31–40: everyday stress, burnout, emotional wellbeing...)
5. **Heart & Circulation** (Topics 41–50: blood pressure, cholesterol, resting heart rate...)
6. **Diabetes & Metabolism** (Topics 51–60: type 2 diabetes signs, blood glucose, HbA1c...)
7. **Skin, Hair & Hygiene** (Topics 61–70: sunscreen, SPF, acne, hair fall...)
8. **Gut & Digestion** (Topics 71–80: gut health, dietary fibre, acid reflux, probiotics...)
9. **Vitamins & Deficiencies** (Topics 81–90: Vitamin D, C, Calcium, Zinc, anaemia...)
10. **Preventive Health** (Topics 91–100: regular checkups, BMI, dehydration, fever warnings...)
11. **Everyday Health** (Topics 101–110: posture, screen eye strain, movement breaks...)
12. **Special Health Topics** (Topics 111–120: PCOS, thyroid disorders, bone health...)

---

## ⚙️ Configuration (.env)

Edit [.env](file:///home/mahajan-ashok/automation/.env) with your details:

```env
# 1. Google Gemini API (Free: https://aistudio.google.com/)
GEMINI_API_KEY=your_gemini_api_key

# 2. Pexels API (Free: https://www.pexels.com/api/)
PEXELS_API_KEY=your_pexels_api_key

# 3. Cloudinary (Free: https://cloudinary.com/)
CLOUDINARY_URL=cloudinary://<api_key>:<api_secret>@<cloud_name>

# 4. Email Notification (Sends review emails with video to you)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your_sender_gmail@gmail.com
SMTP_PASSWORD=your_gmail_16_digit_app_password
RECIPIENT_EMAIL=your_personal_email@gmail.com

# 5. Bot Settings
VOICE_NAME=te-IN-MohanNeural
TARGET_DURATION_SECONDS=30
EXECUTION_MODE=review
```

> **Note on Gmail App Password:** If using Gmail, enable 2-Step Verification in your Google Account, then go to **Security → App Passwords** to create a 16-digit password for `SMTP_PASSWORD`.

---

## 🚀 Running Locally

```bash
# 1. Activate environment
source .venv/bin/activate

# 2. Dry run (generates video locally in output/ without sending email)
python main.py --mode dry-run

# 3. Full Review Run (renders 30s Telugu video and emails it to you)
python main.py --mode review

# 4. Run for a specific topic
python main.py --topic "Benefits of walking 30 minutes daily" --category "Fitness and exercise"
```
