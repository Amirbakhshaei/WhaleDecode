def __getattr__(name: str):
    if name == "LangGraphReasoner":
        from whaledecode.adapters.llm_graph.reasoner import LangGraphReasoner
        return LangGraphReasoner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["LangGraphReasoner"]
