"""Til sozlamalari: Whisper kodlari, yo'naltiruvchi prompt va to'ldiruvchi so'zlar."""
from __future__ import annotations

# Whisper rasmiy ro'yxatida uz va kk bor, ky (qirg'iz) yo'q.
WHISPER_SUPPORTED = {"uz", "kk", "ru", "en", "tr", "tg", "tk", "az"}

# Prompt modelni kerakli yozuv va tinish belgilariga yo'naltiradi (fakt sifatida matnga qo'shilmaydi).
PROMPTS = {
    "uz": "Assalomu alaykum. Bugun biz o‘zbek tilida suhbatlashamiz: savollar, javoblar va fikrlar.",
    "kk": "Сәлеметсіз бе. Бүгін біз қазақ тілінде сөйлесеміз: сұрақтар, жауаптар және ойлар.",
    "ky": "Саламатсыздарбы. Бүгүн биз кыргыз тилинде сүйлөшөбүз: суроолор, жооптор жана ойлор.",
}

# "Toza matn" rejimida olib tashlanadigan to'ldiruvchi tovushlar (faqat yakka so'z bo'lsa)
FILLERS = {
    "e", "ee", "eee", "eeee", "e-e", "a", "aa", "aaa", "aaaa", "m", "mm", "mmm", "hm", "hmm", "hmmm",
    "xm", "xmm", "em", "emm", "ehm", "uh", "um", "umm", "ah", "eh",
    "э", "ээ", "эээ", "э-э", "м", "мм", "ммм", "хм", "хмм", "а-а", "аа", "ааа", "ым", "ыы", "эм",
}


def whisper_language(lang: str, overrides: dict) -> tuple[str | None, list[str]]:
    """Foydalanuvchi tanlovi -> Whisper'ga beriladigan til kodi va ogohlantirishlar."""
    warnings: list[str] = []
    if lang == "auto":
        return None, warnings
    if lang in overrides and overrides[lang]:
        mapped = overrides[lang]
        if mapped != lang:
            warnings.append(f"lang_mapped_{lang}_{mapped}")
        return mapped, warnings
    if lang not in WHISPER_SUPPORTED:
        warnings.append(f"lang_unsupported_{lang}")
        return None, warnings
    return lang, warnings


def build_prompt(lang: str | None, vocabulary: str) -> str | None:
    parts = []
    if lang and lang in PROMPTS:
        parts.append(PROMPTS[lang])
    if vocabulary:
        parts.append(vocabulary.strip().rstrip(".") + ".")
    text = " ".join(parts).strip()
    return text or None


def vocabulary_terms(vocabulary: str) -> list[str]:
    terms = [t.strip() for t in vocabulary.replace("\n", ",").replace(";", ",").split(",")]
    return [t for t in terms if t][:100]
