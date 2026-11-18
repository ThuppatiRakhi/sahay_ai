"""Conversational response generator for SahayAI.

Handles greetings, small talk, general knowledge, education, programming,
and everyday inquiries without ChromaDB retrieval, scheme citations, or disclaimers.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from rag.llm_client import GroqLLMClient
from rag.query_rewriter import normalize_language_code, normalize_language_name

logger = logging.getLogger(__name__)


def get_conversational_system_prompt(target_lang: str) -> str:
    """Constructs conversational system prompt enforcing the user's preferred language."""
    lang_rules = {
        "telugu": (
            "CRITICAL LANGUAGE RULE: You MUST respond entirely in natural, fluent Telugu script (తెలుగు). "
            "Do NOT respond in English or Hindi unless the user explicitly requests another language in their query. "
            "Even if the user asks in English, Romanized Telugu (Tenglish), or mixed language, your response must be in authentic, fluent Telugu script. "
            "Do NOT translate official scheme names (e.g. 'AICTE Pragati Scholarship for Girl Students', 'PM-USP CSSS'), "
            "portal names ('National Scholarship Portal', 'NSP'), or official terminology into confusing literal translations; "
            "keep standard official names and acronyms recognizable."
        ),
        "hindi": (
            "CRITICAL LANGUAGE RULE: You MUST respond entirely in natural, fluent Hindi using Devanagari script (हिन्दी). "
            "Do NOT respond in English or Telugu unless the user explicitly requests another language in their query. "
            "Even if the user asks in English, Hinglish, or mixed language, your response must be in Devanagari Hindi script. "
            "Do NOT translate official scheme names (e.g. 'AICTE Pragati Scholarship for Girl Students', 'PM-USP CSSS'), "
            "portal names ('National Scholarship Portal', 'NSP'), or official terminology into confusing literal translations; "
            "keep standard official names and acronyms recognizable."
        ),
        "english": (
            "CRITICAL LANGUAGE RULE: Respond in clear, natural, and helpful English. "
            "Do NOT respond in Hindi or Telugu unless explicitly requested by the user."
        ),
    }

    norm = normalize_language_name(target_lang)
    rule = lang_rules.get(norm, lang_rules["english"])

    return f"""You are SahayAI, an intelligent, respectful, and helpful AI assistant for Indian citizens.
You can converse naturally, explain general knowledge, educational, scientific, and programming concepts clearly, engage in polite small talk, and assist with general inquiries.

Language Requirement:
{rule}

Core Principles:
1. Answer the user's question directly, clearly, politely, and accurately in the required language.
2. Do NOT invent or introduce government schemes, scholarships, or reservations into general conversations unless the user explicitly asks about them.
3. If asked who you are or what you can do, introduce yourself as SahayAI, an AI assistant dedicated to helping citizens with general inquiries and government scholarship guidance.
4. Maintain a warm, encouraging, and natural conversational tone.
"""


class ConversationalHandler:
    """Generates non-RAG conversational responses for general citizen queries."""

    def __init__(self, llm_client: Optional[GroqLLMClient] = None):
        self._llm_client = llm_client

    @property
    def llm_client(self) -> GroqLLMClient:
        """Lazily initialize LLM client if not injected."""
        if self._llm_client is None:
            self._llm_client = GroqLLMClient()
        return self._llm_client

    def generate_response(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        target_language: str = "en",
    ) -> Dict[str, Any]:
        """Generates conversational response using the configured LLM.

        Args:
            query: Citizen input string.
            conversation_history: Prior conversational messages.
            target_language: Target response language code or name.

        Returns:
            Dictionary with answer, empty citations, and None disclaimer.
        """
        system_prompt = get_conversational_system_prompt(target_language)
        messages = [{"role": "system", "content": system_prompt}]

        if conversation_history:
            for msg in conversation_history[-6:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": query})

        try:
            raw_response = self.llm_client.generate(messages=messages, max_tokens=1024)
            # In test environments with mocked LLMs, if mock returned JSON string with 'answer', extract it
            if raw_response.startswith("{") and '"answer"' in raw_response:
                try:
                    parsed = json.loads(raw_response)
                    answer_text = parsed.get("answer", raw_response)
                except Exception:
                    answer_text = raw_response
            else:
                answer_text = raw_response
        except Exception as exc:
            logger.warning("LLM generation failed for conversational query, using fallback: %s", exc)
            answer_text = self._fallback_response(query, target_language)

        answer_text = re.sub(r"[\u202f\u00a0]", " ", answer_text)

        canon_code = normalize_language_code(target_language)

        return {
            "answer": answer_text,
            "sources": [],
            "disclaimer": None,
            "evidence_sufficient": True,
            "intent": "general_conversation",
            "citations": [],
            "language": canon_code,
            "current_status_verified": False,
        }

    def generate_clarification(
        self,
        query: str,
        language: str = "en",
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates natural clarification when user intent cannot be determined confidently.

        Args:
            query: Citizen input text.
            language: Detected or preferred language code.
            prompt: Optional specific clarification prompt.

        Returns:
            Dictionary with natural clarification prompt, empty citations, and None disclaimer.
        """
        lang_code = normalize_language_code(language)
        if prompt:
            clarification = prompt
        elif lang_code == "hi":
            clarification = (
                "नमस्ते! मैं आपकी किस प्रकार सहायता कर सकता हूँ? क्या आप सरकारी छात्रवृत्ति योजनाओं "
                "(जैसे एआईसीटीई प्रगति, सक्षम, स्वनाथ, पीएम-यूएसपी) के बारे में जानकारी चाहते हैं, "
                "या आपका कोई सामान्य शैक्षिक या तकनीकी प्रश्न है?"
            )
        elif lang_code == "te":
            clarification = (
                "నమస్కారం! నేను మీకు ఎలా సహాయపడగలను? మీరు ప్రభుత్వ స్కాలర్‌షిప్ పథకాల "
                "(ఏఐసీటీఈ ప్రగతి, సక్షమ్, స్వానాథ్, పీఎం-యూఎస్‌పీ వంటివి) గురించి సమాచారం తెలుసుకోవాలనుకుంటున్నారా, "
                "లేదా ఏదైనా సాధారణ ప్రశ్న అడగాలనుకుంటున్నారా?"
            )
        else:
            clarification = (
                "I'd be glad to help! Could you please clarify what you're looking for? "
                "You can ask me about government scholarship schemes (such as AICTE Pragati, Saksham, "
                "Swanath, PM-USP CSSS, or Top Class SC) or ask any general educational or programming question."
            )

        return {
            "answer": clarification,
            "sources": [],
            "disclaimer": None,
            "evidence_sufficient": True,
            "intent": "ambiguous",
            "citations": [],
            "language": lang_code,
            "current_status_verified": False,
        }

    def _fallback_response(self, query: str, language: str) -> str:
        """Deterministic fallback when LLM API is unavailable or offline."""
        q_lower = query.lower()
        lang_code = normalize_language_code(language)

        if any(w in q_lower for w in ["hello", "hi", "hey", "namaste", "namaskar", "ela"]):
            if lang_code == "hi":
                return "नमस्ते! मैं सहायएआई (SahayAI) हूँ। मैं आपकी क्या सहायता कर सकता हूँ?"
            if lang_code == "te":
                return "నమస్కారం! నేను సహాయ్ ఏఐ (SahayAI). నేను మీకు ఎలా సహాయపడగలను?"
            return "Hello! I am SahayAI. How can I help you today?"

        if any(w in q_lower for w in ["thank", "dhanyavad", "shukriya"]):
            if lang_code == "hi":
                return "आपका बहुत-बहुत धन्यवाद! यदि आपके पास कोई अन्य प्रश्न है, तो बेझिझक पूछें।"
            if lang_code == "te":
                return "మీకు చాలా ధన్యవాదాలు! మీకు మరిన్ని సందేహాలు ఉంటే అడగవచ్చు."
            return "You're very welcome! Feel free to ask if you have any other questions."

        if any(w in q_lower for w in ["who are you", "what are you", "what is sahayai", "tum kaun ho", "meeru evaru"]):
            if lang_code == "te":
                return "నేను సహాయ్ ఏఐ (SahayAI), పౌరుల సందేహాలు మరియు ప్రభుత్వ స్కాలర్‌షిప్‌ల మార్గదర్శకత్వం కోసం రూపొందించబడిన సహాయకుడిని."
            if lang_code == "hi":
                return "मैं सहायएआई (SahayAI) हूँ, नागरिकों के सामान्य प्रश्नों और सरकारी छात्रवृत्ति मार्गदर्शन के लिए आपका एआई सहायक।"
            return "I am SahayAI, your AI assistant for citizen guidance and government scholarship exploration."

        if lang_code == "te":
            return "సాధారణ ప్రశ్నలు మరియు ప్రభుత్వ స్కాలర్‌షిప్‌ల వివరాల కోసం నేను మీకు సహాయం చేయగలను. మీకు ఏమి సమాచారం కావాలి?"
        if lang_code == "hi":
            return "मैं सामान्य प्रश्नों और सरकारी छात्रवृत्ति मार्गदर्शन में आपकी सहायता के लिए यहाँ हूँ। मैं आपकी क्या मदद कर सकता हूँ?"
        return "I am here to assist you with general questions and government scholarship guidance. How can I help?"
