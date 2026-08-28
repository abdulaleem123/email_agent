"""Requirements 3 & 9: classify every inbound message into hot / warm / cold
with a confidence score, and bump the lead's priority so replies float to the
top of the list — even when they came in reply to a manual (user-sent) email
while the agent was paused."""
import time

HOT_SIGNALS = ["let's schedule", "book a call", "book a meeting", "when are you free",
               "send the proposal", "pricing", "quote", "budget", "interested",
               "sounds good", "let's talk", "call me", "share the contract",
               "how much", "start", "kick off", "onboard"]
WARM_SIGNALS = ["tell me more", "more details", "case study", "portfolio",
                "what do you do", "how does it work", "maybe later", "next month",
                "circle back", "who are you", "examples", "reviews", "?"]
COLD_SIGNALS = ["not interested", "unsubscribe", "remove me", "stop emailing",
                "no thanks", "wrong person", "do not contact", "spam"]


def classify_reply(body: str) -> tuple[str, int]:
    """Returns (temperature, confidence 0-100)."""
    text = (body or "").lower()

    cold_hits = sum(s in text for s in COLD_SIGNALS)
    if cold_hits:
        return "cold", min(95, 60 + cold_hits * 15)

    hot_hits = sum(s in text for s in HOT_SIGNALS)
    warm_hits = sum(s in text for s in WARM_SIGNALS)

    if hot_hits >= 2:
        return "hot", min(95, 70 + hot_hits * 10)
    if hot_hits == 1:
        return "hot", 65
    if warm_hits >= 2:
        return "warm", min(85, 55 + warm_hits * 10)
    if warm_hits == 1:
        return "warm", 50
    # A reply with no signals is still engagement.
    return "warm", 40


def priority_bump(current: float, temperature: str) -> float:
    """Monotonic priority: newer replies + hotter leads sort first.
    Uses epoch seconds as the base so a fresh reply always tops the list."""
    weight = {"hot": 2_000_000, "warm": 500_000, "cold": 0}[temperature]
    return max(current, time.time() + weight)
