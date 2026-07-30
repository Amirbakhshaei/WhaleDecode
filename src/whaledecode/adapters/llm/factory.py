from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq

from whaledecode.config.settings import Settings


class LLMFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_heavy_reasoning_llm(self) -> BaseChatModel:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=self._settings.MODEL_HEAVY_REASONING,
            google_api_key=self._settings.GEMINI_API_KEY.get_secret_value(),
            temperature=0.2,
        )

    def get_structured_data_llm(self) -> BaseChatModel:
        return ChatGroq(
            model=self._settings.MODEL_STRUCTURED_DATA,
            groq_api_key=self._settings.GROQ_API_KEY.get_secret_value(),
            temperature=0.2,
        )

    def get_fast_chat_llm(self) -> BaseChatModel:
        return ChatGroq(
            model=self._settings.MODEL_FAST_CHAT,
            groq_api_key=self._settings.GROQ_API_KEY.get_secret_value(),
            temperature=0.3,
        )
