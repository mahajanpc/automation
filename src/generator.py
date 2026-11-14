import json
import logging
from dataclasses import dataclass, field
from src.config import Config

logger = logging.getLogger(__name__)

@dataclass
class Scene:
    telugu_speech: str                                  # Pure native Telugu script for speech synthesis
    subtitles: list[str] = field(default_factory=list)  # Short Telugu phrases (3-5 words) with *keywords*
    visual_query: str = "healthy nutrition"             # Primary English search query
    search_queries: list[str] = field(default_factory=list) # 2-3 ranked English queries
    visual_concept: str = ""                            # Concept description (subject, action)
    shot_type: str = "cinematic"                        # closeup, macro, pan, wide, action
    negative_keywords: list[str] = field(default_factory=list)

    @property
    def tenglish_subtitle(self) -> str:
        # Fallback helper for legacy references
        return " ".join(self.subtitles)

@dataclass
class ReelScript:
    topic: str
    category: str
    hook: str
    hook_title: str
    cta_text: str
    scenes: list[Scene]
    caption: str
    medical_disclaimer: str
    music_mood: str = "calm"

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
        """Generate a high-retention 30-second multi-scene health reel script with native Telugu narration & visual shot planning."""
        if not self.client:
            logger.info("No active Gemini API key configured. Using verified mock script.")
            return self._mock_script(topic, category)

        feedback_notes = self._load_feedback()

        prompt = f"""
You are an expert health communicator and viral video director for Telugu Instagram audiences.
Create a high-retention, professionally paced 30-second MULTI-SCENE Instagram Reel about:
Category: "{category}"
Topic: "{topic}"

CRITICAL EDITING & STORYTELLING GUIDELINES:
1. 5-BEAT VIRAL STORYTELLING ARC (30 seconds total, ~5-6 seconds per beat):
   * Beat 1 (The Relatable Hook): Start with an everyday habit, relatable feeling, or provocative question (e.g. "Do you eat almonds this way?").
   * Beat 2 (The Hidden Body Conflict): Reveal what secretly happens inside the body (e.g. enzyme inhibitors, digestive strain, insulin spike).
   * Beat 3 (The Domino Effect / Biological Drama): Describe the physiological cause-and-effect chain (e.g. nutrient blocking, energy crash, liver fat).
   * Beat 4 (The Eye-Opening Fact / Comparison): Reveal an astonishing scientific fact or comparison that busts a myth.
   * Beat 5 (The Empowering Solution & CTA): Present a simple, actionable daily habit swap that empowers the viewer, plus a warm call-to-action.

2. AUTHENTIC TELUGU SPEECH ('telugu_speech'):
   * 100% STRICTLY in warm, expressive, grammatically flawless TELUGU SCRIPT (తెలుగు లిపి).
   * NEVER use English letters in 'telugu_speech' so Edge-TTS pronounces it with 100% natural native Telugu cadence.
   * Conversational doctor/wellness host tone (friendly, authoritative, clear).

3. TELUGU SUBTITLES WITH SELECTIVE HIGHLIGHTING ('subtitles'):
   * Each scene must contain 2 to 3 SHORT, PUNCHY Telugu phrases (each 3 to 5 words max).
   * Use an asterisk around 1 or 2 high-impact keywords per phrase to highlight them in bold golden yellow (e.g., "*బాదం పప్పులు* తింటున్నారా?", "తోలుతో తింటే *కడుపుకు శ్రమ*!", "*రాత్రంతా నానబెట్టండి*").
   * Subtitles must be in TELUGU SCRIPT for authentic regional audience engagement.

4. ULTRA-RELEVANT STOCK FOOTAGE SEARCH ('search_queries'):
   * Provide 2 to 3 SIMPLE, HIGH-YIELD English search queries for Pixabay for each scene (2-3 words max).
   * Pixabay works best with clean concrete nouns, NOT long descriptive sentences.
   * PROVEN SEARCH PATTERNS:
     - For nuts/almonds/seeds: "healthy nuts", "walnuts bowl", "cashew nuts", "organic food"
     - For stomach/digestion: "stomach anatomy", "digestive tract", "human organs"
     - For cells/biology/nutrients: "blood cells", "human cell", "vitamins nutrition"
     - For drinking/water: "drinking water glass", "pouring water fresh"
     - For doctor/health/action: "doctor consultation", "healthy lifestyle walking", "fresh vegetables salad"
   * NEVER use compound phrases like "hand holding peeled almonds", "human digestive system 3d animation", "nutrient absorption block". Keep them clean and concrete!
   * 'negative_keywords': Concepts that would look ridiculous or misleading (e.g. 'winery', 'squirrel', 'cocktail', 'party', 'landscape', 'flowers', 'bathtub').

5. HOOK TITLE & CTA:
   * 'hook_title': Ultra-short punchy Telugu title for the opening visual card (e.g. "🚨 బాదం తినే సరైన పద్ధతి!").
   * 'cta_text': Warm concluding Telugu CTA (e.g. "🌿 ఆరోగ్యంగా ఉండండి | సేవ్ & షేర్ చేయండి ✨").
   * 'music_mood': Choose one: "calm", "inspirational", "acoustic".

USER FEEDBACK HISTORY:
{feedback_notes}

Return strictly a valid JSON object matching this schema:
{{
  "hook": "Punchy hook summary in English/Tenglish",
  "hook_title": "తెలుగులో చిన్న ఆకర్షణీయమైన హెడ్డింగ్",
  "cta_text": "తెలుగులో ముగింపు పిలుపు",
  "music_mood": "calm",
  "scenes": [
    {{
      "telugu_speech": "పూర్తి తెలుగు లిపిలో మొదటి సన్నివేశ వాక్యం...",
      "subtitles": ["వాక్యం మొదటి భాగం *ముఖ్యపదం*", "రెండవ భాగం *హైలైట్ పదం*"],
      "search_queries": ["specific english query 1", "alternative query 2", "fallback query 3"],
      "visual_concept": "Description of subject and action",
      "shot_type": "closeup",
      "negative_keywords": ["landscape", "winery", "squirrel"]
    }},
    {{
      "telugu_speech": "పూర్తి తెలుగు లిపిలో రెండవ సన్నివేశ వాక్యం...",
      "subtitles": ["వాక్యం మొదటి భాగం", "రెండవ భాగం *ముఖ్యపదం*"],
      "search_queries": ["specific english query 1", "alternative query 2"],
      "visual_concept": "Description of subject and action",
      "shot_type": "macro",
      "negative_keywords": ["cocktail", "party"]
    }},
    {{
      "telugu_speech": "పూర్తి తెలుగు లిపిలో మూడవ సన్నివేశ వాక్యం...",
      "subtitles": ["వాక్యం మొదటి భాగం", "రెండవ భాగం *ముఖ్యపదం*"],
      "search_queries": ["specific english query 1", "alternative query 2"],
      "visual_concept": "Description of subject and action",
      "shot_type": "pan",
      "negative_keywords": ["unrelated"]
    }},
    {{
      "telugu_speech": "పూర్తి తెలుగు లిపిలో నాల్గవ సన్నివేశ వాక్యం...",
      "subtitles": ["వాక్యం మొదటి భాగం", "రెండవ భాగం *ముఖ్యపదం*"],
      "search_queries": ["specific english query 1", "alternative query 2"],
      "visual_concept": "Description of subject and action",
      "shot_type": "closeup",
      "negative_keywords": ["unrelated"]
    }},
    {{
      "telugu_speech": "పూర్తి తెలుగు లిపిలో ఐదవ సన్నివేశ వాక్యం...",
      "subtitles": ["వాక్యం మొదటి భాగం", "రెండవ భాగం *ముఖ్యపదం*"],
      "search_queries": ["specific english query 1", "alternative query 2"],
      "visual_concept": "Description of subject and action",
      "shot_type": "cinematic",
      "negative_keywords": ["unrelated"]
    }}
  ],
  "caption": "Instagram caption in engaging Tenglish with story takeaway, practical tip, and 8 relevant hashtags",
  "medical_disclaimer": "General awareness kosam mathrame. Doctor consultation mandatory."
}}
"""

        candidate_models = ["gemini-3.5-flash-lite", "gemini-3.5-flash", Config.GEMINI_MODEL]
        # Remove duplicates while preserving order
        unique_models = []
        for m in candidate_models:
            if m and m not in unique_models:
                unique_models.append(m)

        for model_name in unique_models:
            try:
                logger.info(f"Generating Reel script with Gemini model: {model_name}...")
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json"
                    }
                )
                data = json.loads(response.text)
                raw_scenes = data.get("scenes", [])
                scenes = []
                for s in raw_scenes:
                    sub_list = s.get("subtitles") or []
                    if not sub_list:
                        raw_speech = s.get("telugu_speech", "")
                        words = raw_speech.split()
                        chunk_sz = max(3, len(words) // 2) if len(words) > 3 else len(words)
                        sub_list = [" ".join(words[i:i+chunk_sz]) for i in range(0, len(words), chunk_sz)] if words else ["ఆరోగ్య చిట్కా"]

                    sq = s.get("search_queries") or []
                    if not sq and s.get("visual_query"):
                        sq = [s.get("visual_query")]
                    elif not sq:
                        sq = ["healthy lifestyle food"]

                    scenes.append(Scene(
                        telugu_speech=s.get("telugu_speech", "").strip(),
                        subtitles=[sub.strip() for sub in sub_list if sub.strip()],
                        visual_query=sq[0] if sq else "healthy lifestyle",
                        search_queries=sq,
                        visual_concept=s.get("visual_concept", ""),
                        shot_type=s.get("shot_type", "cinematic"),
                        negative_keywords=s.get("negative_keywords", [])
                    ))

                if scenes:
                    return ReelScript(
                        topic=topic,
                        category=category,
                        hook=data.get("hook", topic),
                        hook_title=data.get("hook_title", topic),
                        cta_text=data.get("cta_text", "ఆరోగ్యమే మహాభాగ్యం | షేర్ చేయండి ✨"),
                        scenes=scenes,
                        caption=data.get("caption", f"Health tips: {topic} #TeluguHealth #HealthTips"),
                        medical_disclaimer=data.get("medical_disclaimer", "General awareness kosam mathrame."),
                        music_mood=data.get("music_mood", "calm")
                    )
            except Exception as e:
                logger.warning(f"Gemini generation error with {model_name}: {e}. Trying next candidate...")

        logger.error("All Gemini model attempts exhausted. Falling back to verified mock script.")
        return self._mock_script(topic, category)

    def _mock_script(self, topic: str, category: str) -> ReelScript:
        """Verified fallback multi-scene script with native Telugu narration, subtitles, and concrete queries."""
        scenes = [
            Scene(
                telugu_speech=f"రోజూ ఉదయాన్నే {topic} గురించి తెలుసుకోవడం మనందరికీ ఎంతో అవసరం.",
                subtitles=[f"*{topic}* నిజాలు!", "రోజూ ఉదయాన్నే *ముఖ్యమైన టిప్*", "మీ బాడీ ఆరోగ్యం కోసం!"],
                visual_query="healthy nutrition food",
                search_queries=["healthy fresh food bowl", "healthy organic vegetables", "clean eating nutrition"],
                visual_concept="Fresh vibrant healthy food on table",
                shot_type="closeup"
            ),
            Scene(
                telugu_speech="మనం తీసుకునే ఆహారమే మన శరీరానికి ఔషధం లాగా పని చేస్తుంది.",
                subtitles=["ఆహారమే *శరీరానికి ఔషధం*!", "సరైన ఆహారం *సహజ రక్షణ*", "శరీరానికి అమృతం లాంటిది"],
                visual_query="vegetables fresh salad",
                search_queries=["fresh colorful salad bowl", "organic vegetables kitchen", "healthy meal preparation"],
                visual_concept="Close up of fresh healthy salad preparation",
                shot_type="macro"
            ),
            Scene(
                telugu_speech="నియమబద్ధమైన అలవాట్లు పాటిస్తే రోగనిరోధక శక్తి రెట్టింపు అవుతుంది.",
                subtitles=["మంచి అలవాట్లు *ఇమ్యూనిటీ బూస్ట్*", "యాక్టివ్ ఎనర్జీ *డబుల్ పవర్*", "రోజూ క్రమం తప్పకుండా"],
                visual_query="fitness exercise wellness",
                search_queries=["morning stretching exercise", "walking active morning", "healthy lifestyle energy"],
                visual_concept="Morning fitness and active movement",
                shot_type="pan"
            ),
            Scene(
                telugu_speech="రోజూ తగినంత నీరు తాగడం వల్ల శరీరం లోపల టాక్సిన్స్ తొలగిపోతాయి.",
                subtitles=["రోజూ *తగినంత నీరు*", "శరీరంలోని *టాక్సిన్స్ అవుట్*", "సహజమైన ఎనర్జీ రికవరీ"],
                visual_query="drinking clean water glass",
                search_queries=["drinking water glass fresh", "pouring fresh water clear", "healthy hydration glass"],
                visual_concept="Pouring and drinking fresh clear water",
                shot_type="closeup"
            ),
            Scene(
                telugu_speech="ఆరోగ్యమే మహాభాగ్యం! ఈ ఉపయోగకరమైన విషయాన్ని మీ స్నేహితులకు షేర్ చేయండి.",
                subtitles=["*ఆరోగ్యమే మహాభాగ్యం*!", "ఈరోజే ప్రారంభించండి *హెల్తీ హ్యాబిట్*", "ఫ్రెండ్స్ కు *షేర్ చేయండి* ✨"],
                visual_query="doctor consultation health",
                search_queries=["doctor talking smiling patient", "wellness lifestyle peaceful", "happy healthy family"],
                visual_concept="Doctor smiling consultation and healthy lifestyle",
                shot_type="cinematic"
            )
        ]
        return ReelScript(
            topic=topic,
            category=category,
            hook=f"{topic} gurinchi doctors cheppe real facts!",
            hook_title=f"🌿 {topic}: ముఖ్యమైన విషయాలు",
            cta_text="🌿 ఆరోగ్యంగా ఉండండి | సేవ్ & షేర్ చేయండి ✨",
            scenes=scenes,
            caption=(
                f"🌿 {topic} గురించి తెలుసుకోవాల్సిన ముఖ్యమైన హెల్త్ టిప్స్:\n\n"
                "ఆరోగ్యమే మహాభాగ్యం! చిన్న చిన్న ఆరోగ్యకరమైన అలవాట్లతో మీ ఆరోగ్యాన్ని పదిలంగా కాపాడుకోండి.\n\n"
                "Key takeaways:\n"
                "1. Follow balanced nutrition daily.\n"
                "2. Drink enough clean water.\n"
                "3. Consult doctor for personalized health advice.\n\n"
                "#TeluguHealth #HealthTips #Arogyam #HealthyLiving #DoctorAdvice #NutritionTips"
            ),
            medical_disclaimer="General awareness kosam mathrame. Doctor consultation mandatory.",
            music_mood="calm"
        )
