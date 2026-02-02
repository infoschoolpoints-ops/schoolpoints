def normalize_ui_icons(text: str) -> str:
    if not text:
        return text

    replacements = {
        "✅": "\ue0a2",
        "✔️": "\ue0a2",
        "✔": "\ue0a2",
        "⭐": "\U0001F7D4",
        "🌟": "\U0001F7D4",
        "ℹ️": "\U0001F6C8",
        "ℹ": "\U0001F6C8",
        "⚠️": "\u26A0",
        "⚠": "\u26A0",
        "❌": "\u26A0",
        "💌": "\ue135",
        "⬇️": "\u23F7",
        "⬇": "\u23F7",
        "⚙️": "\U0001F527",
        "⚙": "\U0001F527",
        "🚪": "\U0001F3C3",
        "⏰": "\U0001F562",
        "🕒": "\U0001F562",
        "🕓": "\U0001F562",
        "🕔": "\U0001F562",
        "🕕": "\U0001F562",
        "🕖": "\U0001F562",
        "🕗": "\U0001F562",
        "🕘": "\U0001F562",
        "🕙": "\U0001F562",
        "🕚": "\U0001F562",
        "🕛": "\U0001F562",
    }

    for src, dst in replacements.items():
        text = text.replace(src, dst)

    text = text.replace("\u200d", "").replace("\ufe0f", "")
    return text
