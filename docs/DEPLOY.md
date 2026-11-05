> **Eng oson yo‘l — Vercel (serversiz, har kim o‘z Gemini kaliti bilan):** README → «Internetga joylash: GitHub → Vercel».
> Quyidagi qo‘llanma to‘liq server versiyasi (lokal Whisper, 2 soatlik fayllar) uchun — VPS/Docker.

# Telefon, internet va hosting

## A. Bir Wi-Fi tarmog‘ida telefon (tekin)

1. `scripts\run_lan_windows.bat` — ekranda `Telefonda: http://192.168.x.x:8000` manzili chiqadi.
2. Telefon shu Wi-Fi’da bo‘lsin, brauzerda shu manzilni oching.
3. Ochilmasa, administrator CMD’da port oching:
   `netsh advfirewall firewall add rule name="ilmhubstt" dir=in action=allow protocol=TCP localport=8000 profile=private`
4. `.env` faylida `APP_ACCESS_KEY=...` qo‘ying — tarmoqdagi boshqa qurilmalar kalitsiz kira olmaydi.

Audio kompyuterda ishlanadi; telefon faqat yuklaydi va natijani ko‘rsatadi.

## B. Internetdan kirish — Cloudflare Tunnel (tekin, HTTPS)

Kompyuteringiz yoqiq turishi kerak. Domen shart emas (vaqtinchalik manzil):

```
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://127.0.0.1:8000
```

Chiqqan `https://....trycloudflare.com` manzilini telefonda oching. **Majburiy:** `.env` da `APP_ACCESS_KEY`, `RATE_LIMIT_PER_HOUR` o‘rnatilgan bo‘lsin.
Doimiy manzil uchun Cloudflare’da bepul akkaunt va o‘z domeningiz bilan nomli tunnel yarating.

## C. Server / VPS (pullik)

- CPU server: `docker compose up -d --build` (Dockerfile ilova qilingan), oldida HTTPS uchun Caddy: `docs/Caddyfile.example`.
- 2 soatlik audio CPU’da uzoq ishlaydi; tezlik kerak bo‘lsa NVIDIA GPU’li server: `WHISPER_DEVICE=cuda`.
  GPU uchun CUDA 12 + cuDNN 9 kerak (faster-whisper hujjatiga qarang); Docker uchun `nvidia/cuda:12.x-cudnn-runtime` asosidagi obraz ishlating.
- Vercel/Netlify kabi serverless platformalar faqat statik frontend uchun mos; Whisper’ni u yerda uzoq ishlatib bo‘lmaydi.

## Internetga ochishdan oldin tekshiruv ro‘yxati

- [ ] HTTPS (Cloudflare Tunnel yoki Caddy)
- [ ] `APP_ACCESS_KEY` uzun tasodifiy qiymat
- [ ] `RATE_LIMIT_PER_HOUR`, `MAX_UPLOAD_MB`, `MAX_DURATION_MIN` server quvvatiga mos
- [ ] `RETENTION_HOURS` — saqlash siyosati foydalanuvchilarga aytilgan
- [ ] Proxy ortida bo‘lsa `TRUST_PROXY=1`
- [ ] Bulut dvigateli (ElevenLabs) yoqilgan bo‘lsa, foydalanuvchilar audio tashqi servisga ketishini biladi (interfeysda ko‘rsatiladi)
- [ ] Rozilik va qonuniy asosi bo‘lmagan yozuvlarni qayta ishlamaslik
