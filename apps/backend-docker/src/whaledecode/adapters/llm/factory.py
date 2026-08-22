from langchain_core.language_models import BaseChatModel

from whaledecode.adapters.llm.fallback_router import (
    create_gemini_with_groq_fallback,
    create_groq_with_key_fallback,
)
from whaledecode.config.settings import Settings


class LLMFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_heavy_reasoning_llm(self) -> BaseChatModel:
        from langchain_google_genai import ChatGoogleGenerativeAI

        gemini_key = self._settings.GEMINI_API_KEY.get_secret_value()
        groq_key = self._settings.GROQ_API_KEY.get_secret_value()

        if groq_key:
            # Gemini primary with Groq fallback for heavy reasoning
            return create_gemini_with_groq_fallback(
                gemini_key=gemini_key,
                gemini_model=self._settings.MODEL_HEAVY_REASONING,
                groq_key=groq_key,
                groq_model=self._settings.MODEL_STRUCTURED_DATA,
                temperature=0.2,
            )
        # No Groq fallback available
        return ChatGoogleGenerativeAI(
            model=self._settings.MODEL_HEAVY_REASONING,
            google_api_key=gemini_key,
            temperature=0.2,
            max_retries=0,
            timeout=15,
        )

    def get_structured_data_llm(self) -> BaseChatModel:
        groq_key = self._settings.GROQ_API_KEY.get_secret_value()
        secondary_key = (
            self._settings.GROQ_API_KEY_SECONDARY.get_secret_value()
            if self._settings.GROQ_API_KEY_SECONDARY
            else None
        )
        return create_groq_with_key_fallback(
            primary_key=groq_key,
            model=self._settings.MODEL_STRUCTURED_DATA,
            secondary_key=secondary_key,
            temperature=0.2,
        )

    def get_fast_chat_llm(self) -> BaseChatModel:
        groq_key = self._settings.GROQ_API_KEY.get_secret_value()
        secondary_key = (
            self._settings.GROQ_API_KEY_SECONDARY.get_secret_value()
            if self._settings.GROQ_API_KEY_SECONDARY
            else None
        )
        return create_groq_with_key_fallback(
            primary_key=groq_key,
            model=self._settings.MODEL_FAST_CHAT,
            secondary_key=secondary_key,
            temperature=0.3,
        )
