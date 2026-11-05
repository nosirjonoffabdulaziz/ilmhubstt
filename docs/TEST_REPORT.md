# Test hisoboti — ilmhubstt 1.0.0

Sana: 2026-11-05. Muhit: Linux, Python 3.13, FFmpeg 6.1, Chrome (Playwright), 2 yadroli CPU, 7 GB RAM.

## Nima haqiqatan sinovdan o‘tdi

| Qism | Natija |
|---|---|
| Backend unit + integratsiya testlari (`pytest`) | **161 / 161 o‘tdi** |
| 2 soatlik audio yuklama testi (`pytest -m slow`) | **o‘tdi** |
| Brauzer E2E (`scripts/e2e_browser.py`, Chrome) | **o‘tdi**, konsol xatosi yo‘q |
| Brauzer (Vercel/BYOK) rejimi unit testlari (`npm test`) | **12 / 12 o‘tdi** |
| Brauzer rejimi E2E (`scripts/e2e_cloud.py`, soxta Gemini) | **25 / 25 tekshiruv o‘tdi** |

### Formatlar (haqiqiy FFmpeg bilan yaratilgan fayllar)
MP3, WAV, M4A, OGG (Vorbis), OPUS, FLAC, AAC (ADTS), WEBM, MP4 (video+audio), MOV, MKV — barchasi qabul qilindi,
16 kHz mono PCM’ga o‘tkazildi va to‘liq oqimdan (yuklash → navbat → natija → eksport) o‘tdi.
Rad etish to‘g‘ri ishlaydi: PDF va soxta `.mp3` → `unsupported_format`; audiosiz video → `no_audio_track`;
boshqa fayllarga ishora qiluvchi playlist (`.m3u8`) bloklanadi.

### 2 soatlik fayl (demo dvigatel bilan, tanish qismi simulyatsiya)
- Fayl: 120 daqiqa, 43 MB MP3. Yuklash: 0,5 s (lokal).
- FFmpeg konvertatsiya + pauzadan bo‘laklash + normallashtirish + natija: jami ~72 s.
- 12 ta bo‘lak, progress hech qachon orqaga qaytmadi, bo‘laklar orasida matn yo‘qolmadi, takror yo‘q.
- Server xotirasi cho‘qqisi: ~255 MB (audio butunlay xotiraga yuklanmaydi).
- **Test topgan va tuzatilgan xato:** 2-bo‘lakdan boshlab progress qotib qolardi.

### Ishonchlilik va xavfsizlik
- Server ish o‘rtasida majburan o‘chirildi → qayta yoqilganda ish saqlangan bo‘lakdan davom etib tugadi.
- Bekor qilish, navbat tartibi, `server_busy`, `rate_limited`, `too_long`, `file_too_large`, kirish kaliti.
- Boshqa ishning tokeni bilan natijani ko‘rib bo‘lmaydi (404), path traversal, xavfsiz fayl nomlari.
- TXT eksport UTF-8, `o‘ g‘ ’` belgilari buzilmaydi; SRT/VTT formati to‘g‘ri; Range so‘rovli audio ijro.

### Brauzer (Chrome) — E2E
Desktop 1440px (light/dark, UZ/RU/EN), telefon 390px (light/dark): fayl tanlash → yuklash progressi →
jarayon sahifasi → natija → noaniq so‘z oynasi → tahrirni avtomatik saqlash → TXT va SRT yuklab olish → tarix.
320, 360, 768, 1024, 1280 px kengliklarda gorizontal scroll yo‘q. Skrinshotlar: `docs/screenshots/`.

### AI’siz imlo tuzatuvchi (o‘zbek)
Foydalanuvchi yuborgan haqiqiy umumiy-Whisper natijasi (151 so‘z, «Majburiyatnoma» audiosi) bilan sinaldi:
- To‘g‘ri tiklandi: Majburiyatnoma, kuzgi ta’til, o‘quvchining hayoti, xavfsizligini ta’minlash to‘g‘risida, ota-onasi,
  sifatida, farzandimning, bo‘sh vaqtini, etish hamda, xulq-atvorini nazorat qilish, Yo‘l harakati qoidalariga,
  jamoat transportidan, rioya qilish, Yong‘in, Elektr jihozlari, ehtiyotkor bo‘lish, Suv havzalari, qurilish maydonlari,
  muloqotda, Ota-onasining ruxsatisiz, qilmasdan, tark etmaslik, xatti-harakatlardan tiyilish, mas’uliyatimni…
- Tiklab bo‘lmagan 7–9 ta so‘z (vasagligi, xaqslar, Kiji, toluq…) «noaniq» deb belgilandi, taxmin yozilmadi.
- To‘g‘ri o‘zbekcha matnlarda (6 ta gap, ism, raqam, atama bilan) **0 ta o‘zgarish** — himoya rejimi ishlaydi.
- Tezlik: buzilgan matnda ~40 ms/so‘z; sifatli matnda deyarli 0 (faqat tekshiruv).

### Lokal AI muharrir (Ollama)
Soxta Ollama HTTP serveri bilan sinaldi (haqiqiy API formati: `/api/tags`, `/api/chat`):
- Tuzatishlar qabul qilinadi va so‘zlar vaqt belgilariga to‘g‘ri bog‘lanadi (vaqtlar tartibi saqlanadi).
- Xavfli javoblar rad etiladi: gap qo‘shib yuborish, kirill yozuviga o‘tish, raqamni o‘zgartirish.
  «Tuzatilgan matn:» kabi izoh va qo‘shtirnoqlar tozalanadi.
- Ollama o‘chiq yoki model yuklanmagan bo‘lsa, ish baribir tugaydi va ogohlantirish chiqadi.
- Brauzerda: tugma, «AI muharrir tahrirlamoqda» bosqichi, ko‘k belgilar va xulosa qatori tekshirildi.
- **Haqiqiy Gemma modeli bilan sinalmagan** (bu muhitda model yuklab bo‘lmadi): o‘zbekcha tahrir sifatini
  o‘z kompyuteringizda tekshiring.

### Google Gemini dvigateli
Soxta Gemini REST serveri bilan (haqiqiy API formati: `models`, `:generateContent`, `x-goog-api-key`) sinaldi:
- Kalitni Sozlamalardan kiritish: noto‘g‘ri kalit rad etildi, to‘g‘risi tekshirilib `.env` ga yozildi, o‘chirish ishladi.
- 4 daqiqalik fayl 2 bo‘lakka bo‘linib yuborildi; vaqt belgilari to‘g‘ri siljitildi; tokenlar va narx hisoblandi.
- 429 (limit) va 503 da kutib qayta urinish; jami kutish oshsa aniq xato; model topilmasa zaxira modelga o‘tish;
  `thinkingConfig` qo‘llanmasa usiz qayta yuborish; proksi ortidan kalit o‘zgartirish bloklandi.
- Brauzerda: Sozlamalar → kalit → bosh sahifa → yuklash → natija va narx (konsol xatosiz).
- **Haqiqiy Google serveri bilan sinalmagan** (bu muhitda Google API’ga kirish yo‘q) — kalitingiz bilan birinchi
  sinovni qisqa audio bilan qiling.

### YouTube havola, xulosa va Vercel (brauzer) rejimi
Statik build (`node build.mjs --static`) + Google API formatini takrorlovchi soxta Gemini serveri + Chrome:
- Kalit: noto‘g‘ri kalit rad etildi; qo‘shtirnoq/bo‘sh joy bilan qo‘yilgan kalit tozalanib saqlandi.
- YouTube (25 daqiqa): 429 dan keyin kutib qayta urinish; javob token chegarasida uzilganda yarim satr tashlanib,
  shu joydan davom ettirildi — 75/75 gap, takror ham, yo‘qotish ham yo‘q; avtomatik xulosa yaratildi.
- Katta fayl (40 daqiqa, 16,8 MB): Files API’ga bo‘laklab yuklandi, 15 daqiqalik parchalarda yozildi
  (nisbiy vaqtlar to‘g‘ri siljitildi) — 120/120 gap. Ish o‘rtasida sahifa yangilandi → «To‘xtatilgan» →
  «Davom ettirish» → saqlangan joydan tugadi.
- Xulosa tabi: bo‘limlar, faktlar (⚠ tekshirish belgisi), amaliy qadamlar, iqtiboslar; `.md` yuklab olish.
- TXT/SRT eksport, tahrir sahifa yangilangandan keyin saqlanib qolishi, tarix, yopiq video xatosi (RU),
  telefon 390 px (gorizontal scroll yo‘q), konsol xatolari yo‘q.
- **Haqiqiy Google serveri va haqiqiy YouTube bilan sinalmagan** (bu muhitda ularga kirish yo‘q). Deploydan keyin
  birinchi sinovni qisqa ochiq YouTube videosi bilan qiling.

## Nima bu muhitda sinab ko‘rilMAGAN (ochiq aytamiz)

1. **Haqiqiy nutqni tanish (faster-whisper modeli).** Bu test muhitida PyPI/Hugging Face’ga kirish yo‘q edi,
   shuning uchun model o‘rnatilmadi. faster-whisper adapteri uning ommaviy API’sini takrorlovchi soxta modul bilan
   test qilindi (parametrlar, so‘z vaqtlari, xatolarni xaritalash). Haqiqiy o‘zbek/qirg‘iz/qozoq audio bilan
   WER/CER va tezlikni o‘z kompyuteringizda o‘lchang:
   `python scripts/real_asr_check.py --dir test_audio/uz --language uz --csv natija.csv`
2. **ElevenLabs bulut dvigateli** — haqiqiy kalit bilan chaqirilmagan; so‘rov va javob tahlili soxta HTTP javob bilan test qilingan.
3. **Windows** — `.bat` skriptlar Windows’da ishga tushirib ko‘rilmagan (kod platformaga bog‘liq qismlarni hisobga oladi).
4. **Haqiqiy Android/iOS qurilmalar** — faqat Chrome’ning mobil emulyatsiyasida tekshirildi.
5. **Docker / GPU** — fayllar tayyor, lekin bu muhitda yig‘ilmagan.

## Sifat bo‘yicha halol eslatma
Whisper o‘zbek va qozoq tilini qo‘llaydi, **qirg‘iz tilini rasmiy qo‘llamaydi** (qozoq sozlamasi bilan ishlaydi).
Sheva, shovqin, bir vaqtda gapirish va ism/atamalarda xatolar bo‘ladi; tizim ularni «noaniq» deb belgilaydi,
lekin 100% aniqlik kafolatlanmaydi.
