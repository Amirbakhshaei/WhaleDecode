from langchain_core.language_models import BaseChatModel

from whaledecode.adapters.llm.fallback_router import (
    FallbackLLMRouter,
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
        """General bot conversational messages: Gemini (3.5 flash-lite) primary, Groq Llama-70b fallback."""
        gemini_key = self._settings.GEMINI_API_KEY.get_secret_value()
        groq_key = self._settings.GROQ_API_KEY.get_secret_value()
        if gemini_key and groq_key:
            return create_gemini_with_groq_fallback(
                gemini_key=gemini_key,
                gemini_model=self._settings.MODEL_HEAVY_REASONING,
                groq_key=groq_key,
                groq_model=self._settings.MODEL_STRUCTURED_DATA,
                temperature=0.3,
            )
        if groq_key:
            return create_groq_with_key_fallback(
                primary_key=groq_key,
                model=self._settings.MODEL_FAST_CHAT,
                temperature=0.3,
            )
        # Only Gemini available
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=self._settings.MODEL_HEAVY_REASONING,
            google_api_key=gemini_key,
            temperature=0.3,
            max_retries=0,
            timeout=15,
        )

    def get_ask_llm(self) -> BaseChatModel:
        """/ask command: GPT OSS 20b via Groq, Llama-70b fallback."""
        groq_key = self._settings.GROQ_API_KEY.get_secret_value()
        fallback = create_groq_with_key_fallback(
            primary_key=groq_key,
            model=self._settings.MODEL_STRUCTURED_DATA,
            temperature=0.3,
        )
        primary = create_groq_with_key_fallback(
            primary_key=groq_key,
            model=self._settings.MODEL_ASK,
            temperature=0.3,
        )
        return FallbackLLMRouter(primary, [fallback])
