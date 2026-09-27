from __future__ import annotations

from app.config import E_OTINISH_WEB_URL, EGOV_ANDROID_PACKAGE


def e_otinish_links() -> dict[str, str]:
    """Deep links / fallbacks for e-Otinish submission UX."""
    web = E_OTINISH_WEB_URL
    android_intent = (
        f"intent://eotinish#Intent;scheme=https;package={EGOV_ANDROID_PACKAGE};"
        f"S.browser_fallback_url={web};end"
    )
    return {
        "web_url": web,
        "android_intent": android_intent,
        "ios_app_store": "https://apps.apple.com/app/id1476128386",
        "android_play_store": (
            f"https://play.google.com/store/apps/details?id={EGOV_ANDROID_PACKAGE}"
        ),
    }
