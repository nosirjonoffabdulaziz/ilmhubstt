# Transliteratsiya profillari (kirill → lotin)

Kod: `backend/app/services/transliteration_service.py`. Testlar: `backend/tests/test_transliteration.py`.

ASR natijasi uch versiyada saqlanadi:

| Versiya | Maydon | Nima |
|---|---|---|
| Xom | `raw_text` | Model qanday chiqargan bo'lsa, o'zgarishsiz (kirill bo'lsa — kirill) |
| Lotin / tozalangan | `latin_text` | Transliteratsiya + apostrof standarti + tinish/bosh harf + (toza rejimda) to'ldiruvchi tovushlarsiz |
| Tahrirlangan | `edited_text` | Foydalanuvchi brauzerda o'zgartirgan matn (TXT eksport shundan olinadi) |

## O‘zbek — rasmiy lotin alifbosi (1995)

- `ў → o‘`, `ғ → g‘` (U+2018 «‘»), `ъ → ’` (tutuq, U+2019)
- `ш → sh`, `ч → ch`, `ҳ → h`, `х → x`, `қ → q`, `ё → yo`, `ю → yu`, `я → ya`, `ь →` (tushib qoladi)
- `е` → so‘z boshida, unli yoki ъ/ь dan keyin `ye`, aks holda `e` (Европа → Yevropa, поезд → poyezd)
- `ц` → so‘z boshida va undoshdan keyin `s`, unlidan keyin `ts` (цирк → sirk, лицей → litsey)
- Katta harflar: `Шаҳар → Shahar`, `ШАҲАР → SHAHAR`
- Lotin matndagi `o' o` oʻ` kabi variantlar yagona `o‘`/`g‘`/`’` shakliga keltiriladi.

## Qozoq — 2021-yilgi lotin alifbosi loyihasi (loyiha profili)

`ә→ä, ғ→ğ, қ→q, ң→ñ, ө→ö, ұ→ū, ү→ü, һ→h, ш→ş, ч→ç, ы→y, і→ı (katta: I), и/й→i (katta: İ), ц→ts, ю→iu, я→ia`

Qozoq lotin standarti hali yakuniy emas; zarurat bo‘lsa jadvalni `_KK` lug‘atida o‘zgartiring.

## Qirg‘iz — rasmiy lotin standarti yo‘q (loyiha profili)

`ө→ö, ү→ü, ң→ñ, ж→j, ч→ch, ш→sh, ы→ı (katta: I), и→i (katta: İ), й→y, х→h, ц→ts, ё→yo, ю→yu, я→ya`, so‘z boshidagi `е→ye`.

## Muhim qoidalar

- Ism, raqam, manzil, atama hech qachon almashtirilmaydi — faqat harflar transliteratsiya qilinadi.
- «Asl yozuv» tanlansa transliteratsiya qilinmaydi (faqat o‘zbek apostroflari standartlanadi).
