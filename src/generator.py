import json
import logging
from dataclasses import dataclass, field
from src.config import Config

logger = logging.getLogger(__name__)

@dataclass
class Scene:
    telugu_speech: str                  # Pure native Telugu script with rich cultural expressions
    subtitles: list[str] = field(default_factory=list)  # 2 to 4 rapid, moving popping phrases (2-4 words each)
    visual_query: str = "health"        # 1-2 specific medical/food keywords for Pixabay video clip

    @property
    def tenglish_subtitle(self) -> str:
        return " ".join(self.subtitles)

@dataclass
class ReelScript:
    topic: str
    category: str
    hook: str
    scenes: list[Scene]
    caption: str
    medical_disclaimer: str

    @property
    def full_telugu_voiceover(self) -> str:
        return " ".join([s.telugu_speech for s in self.scenes])

    @property
    def full_tenglish_text(self) -> str:
        return " ".join([s.tenglish_subtitle for s in self.scenes])

class ContentGenerator:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or Config.GEMINI_API_KEY
        self.client = None
        if Config.is_valid_key(self.api_key):
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Could not initialize google-genai client: {e}")

    def _load_feedback(self) -> str:
        """Load reviewer feedback to guide continuous self-improvement."""
        feedback_file = Config.ROOT_DIR / "feedback_history.json"
        if feedback_file.exists():
            try:
                with open(feedback_file, "r", encoding="utf-8") as f:
                    feedback_list = json.load(f)
                    if feedback_list:
                        return "\n".join([f"- {item}" for item in feedback_list])
            except Exception as e:
                logger.warning(f"Error loading feedback: {e}")
        return "Use natural native Telugu expressions, female voice cadence, and kinetic popping subtitles."

    def generate(self, topic: str, category: str = "Health") -> ReelScript:
        """Generate a 30-second multi-scene health reel script with native Telugu expressions & kinetic moving subtitles."""
        if not self.client:
            logger.info("No active Gemini API key configured. Using verified mock script.")
            return self._mock_script(topic, category)

        feedback_notes = self._load_feedback()

        prompt = f"""
You are an expert health educator and viral content creator for Telugu Instagram audiences.
Create a high-retention, 30-second MULTI-SCENE Instagram Reel about:
Category: "{category}"
Topic: "{topic}"

CRITICAL INSTRUCTIONS:
1. GRIPPING 5-BEAT CINEMATIC STORYTELLING ARC (DO NOT LIST DRY FACTS!):
   - Never recite dry medical textbook facts or boring bullet points. Tell a 5-beat mini-movie story that hooks curiosity:
     * Beat 1 (The Relatable Hook): Start with an everyday craving, habit, or familiar feeling everyone experiences (e.g. lunch ayyaka sweet craving, chai lo 3 spoons sugar, bedtime snacking).
     * Beat 2 (The Secret Body Conflict): Describe the internal biological drama (e.g. taste is delicious, but the moment it hits your stomach, an internal insulin emergency breaks out!).
     * Beat 3 (The Domino Effect): Show the suspenseful cause-and-effect chain (e.g. extra sugar gets dumped into the liver as fat, and skin collagen gets attacked, triggering wrinkles!).
     * Beat 4 (The Eye-Opening Shock / Hidden Secret): Reveal a surprising everyday fact (e.g. packed juices and sodas secretly hide 8 to 10 spoons of sugar!).
     * Beat 5 (The Empowering Hero Solution): End with a simple, positive habit swap that leaves the viewer feeling capable and relieved (e.g. swap with dates/raisins, protect your body, share with loved ones!).

2. AUTHENTIC NATIVE TELUGU VOICE SCRIPT ('telugu_speech'):
   - Write 100% STRICTLY in warm, expressive, authentic TELUGU SCRIPT (తెలుగు లిపి). NEVER use English letters in telugu_speech so that Edge-TTS produces pure native Telugu phonetics.
   - Use natural native conversational expressions (e.g. "భోజనం అవ్వగానే...", "రుచి అమృతంలా అనిపించొచ్చు కానీ...", "అసలు షాకింగ్ నిజం ఏంటంటే...", "ఆరోగ్యం మీ చేతుల్లోనే...").
   - Voice is an Indian female doctor/nutritionist (te-IN-ShrutiNeural). Keep the speech fluent, engaging, and authoritative.

3. MOVING, POPPING TENGLISH SUBTITLES ('subtitles'):
   - Do NOT output one static long sentence. Subtitles MUST dynamically MOVE WITH THE AUDIO!
   - Provide an array of 2 to 4 SHORT, PUNCHY phrases per scene (each phrase 2 to 4 words max!).
   - Put key punchy words in ALL-CAPS (e.g. 'CRAVING', 'INSULIN', 'FATTY LIVER', 'HIDDEN SUGAR', 'DATES SWAP', 'HEALTHY') so the renderer highlights them in vibrant yellow and pops them on screen!

4. ULTRA-ACCURATE VISUAL SEARCH KEYWORDS ('visual_query'):
   - 'visual_query' MUST be 1 to 2 concrete English nouns only matching the specific beat (e.g. 'sugar dessert', 'blood glucose', 'human liver', 'soda drink', 'dates fruit').
   - NEVER use generic words like "woman close up", "person eating", "happy healthy", "looking in mirror". Use ONLY concrete medical/food nouns!

5. 100% EVIDENCE-BASED MEDICAL ACCURACY:
   - Based on ICMR / WHO scientific guidelines.

6. INSTAGRAM CAPTION:
   - Written in friendly, engaging Tenglish with the story takeaway, simple action tip, medical note, and 8 relevant hashtags.

USER FEEDBACK HISTORY TO ADHERE TO:
{feedback_notes}

Return strictly a valid JSON object matching this schema:
{{
  "hook": "Punchy hook in Tenglish",
  "scenes": [
    {{
      "telugu_speech": "పూర్తి తెలుగు లిపిలో మొదటి సన్నివేశ వాక్యం (సహజమైన తెలుగు పలుకుబడులతో)...",
      "subtitles": ["Phrase 1 (2-3 words)", "Phrase 2 with KEYWORD", "Phrase 3 with WARNING"],
      "visual_query": "1-2 concrete english keywords"
    }},
    {{
      "telugu_speech": "పూర్తి తెలుగు లిపిలో రెండవ సన్నివేశ వాక్యం...",
      "subtitles": ["Phrase 1", "Phrase 2 with KEYWORD", "Phrase 3"],
      "visual_query": "1-2 concrete english keywords"
    }},
    {{
      "telugu_speech": "పూర్తి తెలుగు లిపిలో మూడవ సన్నివేశ వాక్యం...",
      "subtitles": ["Phrase 1", "Phrase 2 with KEYWORD", "Phrase 3"],
      "visual_query": "1-2 concrete english keywords"
    }},
    {{
      "telugu_speech": "పూర్తి తెలుగు లిపిలో నాల్గవ సన్నివేశ వాక్యం...",
      "subtitles": ["Phrase 1", "Phrase 2 with KEYWORD", "Phrase 3"],
      "visual_query": "1-2 concrete english keywords"
    }},
    {{
      "telugu_speech": "పూర్తి తెలుగు లిపిలో ఐదవ సన్నివేశ వాక్యం...",
      "subtitles": ["Phrase 1", "Phrase 2 with KEYWORD", "Phrase 3"],
      "visual_query": "1-2 concrete english keywords"
    }}
  ],
  "caption": "Tenglish Instagram caption with key points and hashtags",
  "medical_disclaimer": "General awareness kosam mathrame. Doctor advice mandatory."
}}
"""

        try:
            response = self.client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=prompt,
                config={
                    "response_mime_type": "application/json"
                }
            )
            data = json.loads(response.text)
            raw_scenes = data.get("scenes", [])
            scenes = []
            for s in raw_scenes:
                # Handle subtitles as list or string
                sub_list = s.get("subtitles")
                if not sub_list:
                    raw_sub = s.get("tenglish_subtitle", "")
                    # Split into 2-4 word phrases
                    words = raw_sub.split()
                    chunk_sz = max(2, len(words) // 3) if len(words) > 3 else len(words)
                    sub_list = [" ".join(words[i:i+chunk_sz]) for i in range(0, len(words), chunk_sz)] if words else ["Health Tip"]

                scenes.append(Scene(
                    telugu_speech=s.get("telugu_speech", "").strip(),
                    subtitles=[sub.strip() for sub in sub_list if sub.strip()],
                    visual_query=s.get("visual_query", "healthy nutrition").strip()
                ))

            if not scenes:
                return self._mock_script(topic, category)

            return ReelScript(
                topic=topic,
                category=category,
                hook=data.get("hook", topic),
                scenes=scenes,
                caption=data.get("caption", f"Health tips: {topic} #TeluguHealth #HealthTips #Tenglish"),
                medical_disclaimer=data.get("medical_disclaimer", "General awareness kosam mathrame.")
            )
        except Exception as e:
            logger.error(f"Gemini generation error: {e}. Falling back to verified mock script.")
            return self._mock_script(topic, category)

    def _mock_script(self, topic: str, category: str) -> ReelScript:
        """Verified fallback multi-scene script with moving popping subtitles."""
        scenes = [
            Scene(
                telugu_speech=f"మన పెద్దలు చెప్పినట్లు, {topic} గురించి తెలుసుకోవడం మనందరికీ ఎంతో అవసరం.",
                subtitles=[f"{topic}", "FACTS thelusukondi!", "Mee body kosam! 🩺"],
                visual_query="healthy food"
            ),
            Scene(
                telugu_speech="ప్రకృతి మనకు ఇచ్చిన ఆహారాన్ని సరైన మోతాదులో తీసుకుంటే శరీరానికి అమృతం లాంటిది.",
                subtitles=["BALANCED DIET", "Amrutham lantiది!", "Daily follow avvandi"],
                visual_query="vegetables salad"
            ),
            Scene(
                telugu_speech="రోజూ క్రమం తప్పకుండా మంచి అలవాట్లు పాటిస్తే రోగనిరోధక శక్తి ఎంతో పెరుగుతుంది.",
                subtitles=["Daily HABITS", "IMMUNITY double!", "Active energy"],
                visual_query="fitness exercise"
            ),
            Scene(
                telugu_speech="తగినంత నీరు మరియు కంటినిండా నిద్ర మన ఆరోగ్యాన్ని పదిలంగా కాపాడతాయి.",
                subtitles=["Water & SLEEP", "FRESH ENERGY", "Natural recovery"],
                visual_query="drinking water"
            ),
            Scene(
                telugu_speech="ఆరోగ్యమే మహాభాగ్యం! మరిన్ని వివరాలకు మీ వైద్యుడిని సంప్రదించండి.",
                subtitles=["AROGYAME mahabhagyam!", "STAY HEALTHY!", "Consult DOCTOR ✨"],
                visual_query="doctor consultation"
            )
        ]
        return ReelScript(
            topic=topic,
            category=category,
            hook=f"{topic} gurinchi doctors cheppe real facts!",
            scenes=scenes,
            caption=(
                f"🌿 {topic} gurinchi thelusukovalsina important tips:\n\n"
                "Arogyame mahabhagyam! Daily healthy habits tho mee life ni active ga unchandi.\n\n"
                "Key takeaways:\n"
                "1. Follow balanced nutrition.\n"
                "2. Drink enough water daily.\n"
                "3. Consult doctor for personalized health advice.\n\n"
                "#TeluguHealth #HealthTips #Arogyam #Tenglish #HealthyLiving #DoctorTips"
            ),
            medical_disclaimer="General awareness kosam mathrame. Doctor consultation mandatory."
        )
