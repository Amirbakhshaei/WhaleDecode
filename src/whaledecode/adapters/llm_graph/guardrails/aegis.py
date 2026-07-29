from typing import Any

from whaledecode.config.settings import Settings


class AegisGuardrail:
    def __init__(self, settings: Settings | None = None) -> None:
        self._disclaimer = settings.DISCLAIMER_TEXT if settings else "Not financial advice. DYOR."

    def validate_output(self, report: dict[str, Any]) -> dict[str, Any]:
        if not report.get("disclaimer"):
            report["disclaimer"] = self._disclaimer
        score = report.get("risk_score", 0.0)
        if not isinstance(score, (int, float)) or score < 0 or score > 1:
            report["risk_score"] = 0.5
        if not report.get("summary"):
            report["summary"] = "Analysis completed."
        return report

    def scrub_pii(self, text: str) -> str:
        import re
        text = re.sub(r"@\w+", "[redacted]", text)
        text = re.sub(r"\b\w{8,}@\w+\.\w+\b", "[email redacted]", text)
        return text

    def check_disclaimer(self, text: str) -> bool:
        keywords = ["not financial advice", "dyor", "disclaimer"]
        return any(kw in text.lower() for kw in keywords)

    def filter_for_public(self, report: dict[str, Any]) -> dict[str, Any] | None:
        blocked = {"DUST_SPAM", "ROUTINE_TRANSFER"}
        event_type = report.get("event_type", "")
        if event_type in blocked:
            return None
        score = report.get("risk_score", 0.0)
        if isinstance(score, (int, float)) and score < 0.3:
            return None
        report["summary"] = self.scrub_pii(report.get("summary", ""))
        report = self.validate_output(report)
        return report
