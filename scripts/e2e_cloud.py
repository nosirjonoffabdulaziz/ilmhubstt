"""Brauzer (BYOK, Vercel) rejimining to'liq E2E testi: statik sayt + soxta Gemini serveri + Chrome.

  cd frontend && ILMHUB_STATIC=1 node build.mjs && cd ..
  python scripts/e2e_cloud.py --out docs/screenshots

Tekshiriladi: kalit kiritish (noto'g'ri/to'g'ri), YouTube havolasi -> davom ettirib yozish -> avtomatik xulosa,
xulosa sahifasi va vaqtga o'tish, eksport (TXT/SRT/MD), katta faylni Files API orqali yuklash -> parchalar,
sahifa yangilanganda to'xtatilgan ishni davom ettirish, tarix, telefon ko'rinishi, konsol xatolari.
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import http.server
import json
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import fake_gemini  # noqa: E402

KEY = fake_gemini.GOOD_KEY
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_static(port: int):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=str(ROOT / "frontend" / "dist"))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def make_audio(path: Path, seconds: int):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
                    "-ac", "1", "-b:a", "56k", str(path)], check=True)


async def run(out: Path) -> int:
    from playwright.async_api import async_playwright

    out.mkdir(parents=True, exist_ok=True)
    gport, sport = free_port(), free_port()
    fake_gemini.serve(gport)
    serve_static(sport)
    gbase = f"http://127.0.0.1:{gport}"
    url = f"http://127.0.0.1:{sport}/"
    tmp = Path(tempfile.mkdtemp(prefix="stt-cloud-"))
    big = tmp / "uzun_podkast.mp3"
    make_audio(big, fake_gemini.FILE_DURATION)  # 40 daqiqa ≈ 16.8 MB (> 15 MB -> Files API)
    problems: list[str] = []
    ok: list[str] = []

    def check(cond: bool, msg: str):
        (ok if cond else problems).append(msg)

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])

        async def page_for(w, h, theme="light", lang="uz", mobile=False):
            ctx = await browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2, is_mobile=mobile,
                                            has_touch=mobile, accept_downloads=True, bypass_csp=True, color_scheme=theme)
            await ctx.add_init_script(
                f"localStorage.setItem('ilmhubstt.geminiBase', '{gbase}');"
                f"if(!localStorage.getItem('ilmhubstt.prefs'))localStorage.setItem('ilmhubstt.prefs', JSON.stringify({{lang:'{lang}', theme:'{theme}'}}))")
            # YouTube/Google'ga internet yo'q — tez rad etamiz (haqiqiy saytda ular ishlaydi)
            await ctx.route("https://www.youtube.com/**", lambda r: r.abort())
            await ctx.route("https://i.ytimg.com/**", lambda r: r.abort())
            pg = await ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and "ERR_FAILED" not in m.text and "429" not in m.text
                  and "Failed to load resource" not in m.text and problems.append(f"console: {m.text}"))
            pg.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
            return ctx, pg

        # ---------- 1) Kalit va YouTube ----------
        ctx, pg = await page_for(1440, 960)
        await pg.goto(url)
        await pg.wait_for_selector("text=YouTube yoki audio/video havolasini qo‘ying")
        await pg.screenshot(path=str(out / "20_cloud_home_link_uz.png"), full_page=True)
        keybox = pg.locator(".keycard input[type=password]")
        await keybox.fill("AQ.wrong-key-000000000000000")
        await pg.locator(".keycard button[type=submit]").click()
        await pg.wait_for_selector(".keycard .note.err", timeout=10000)
        check("noto" in (await pg.locator(".keycard .note.err").inner_text()).lower() or "kalit" in (await pg.locator(".keycard .note.err").inner_text()).lower(),
              "noto'g'ri kalit rad etildi")
        await keybox.fill(f'  "{KEY}" ')
        await pg.locator(".keycard button[type=submit]").click()
        await pg.wait_for_selector(".keycard", state="detached", timeout=10000)
        check(await pg.evaluate("localStorage.getItem('ilmhubstt.geminiKey')") == KEY, "to'g'ri kalit tozalanib saqlandi")

        await pg.fill("input[type=url]", "https://example.com/sahifa")
        await pg.wait_for_selector("text=To‘g‘ridan-to‘g‘ri fayl havolasi")
        await pg.fill("input[type=url]", "salom dunyo")
        await pg.wait_for_selector(".link-dz .note.err")
        await pg.fill("input[type=url]", YT)
        await pg.wait_for_selector(".yt-row >> text=YouTube · dQw4w9WgXcQ", timeout=15000)
        btn = pg.locator(".card-cta button.btn-primary")
        await btn.wait_for(state="visible")
        check((await btn.inner_text()).strip().startswith("Matnga aylantirish va xulosa"), "tugma: aylantirish va xulosa")
        await pg.screenshot(path=str(out / "21_cloud_youtube_ready_uz.png"), full_page=True)
        await btn.click()
        await pg.wait_for_url("**/#/c/*", timeout=10000)
        await pg.wait_for_selector("text=Gemini yozayotgan matn")
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path=str(out / "22_cloud_progress_uz.png"), full_page=True)
        await pg.wait_for_selector(".res-grid", timeout=90000)
        st = json.load(urllib.request.urlopen(gbase + "/__state"))
        gen = [r for r in st["requests"] if not r["json"]]
        check(len(gen) >= 4, f"YouTube: 429 dan keyin qayta urinish va MAX_TOKENS'da davom ettirish ({len(gen)} so'rov)")
        check(all("youtube.com/watch?v=dQw4w9WgXcQ" in json.dumps(r["media"]) for r in gen), "YouTube fileUri yuborildi")
        check(any(r["json"] for r in st["requests"]), "avtomatik xulosa so'raldi")
        segs = await pg.locator(".tabs button").count()
        check(segs == 4, "4 ta tab (tahrir, segmentlar, xom, xulosa)")
        editor = await pg.locator("textarea.editor").input_value()
        n0 = editor.count("-gap:")
        check(n0 == fake_gemini.YT_DURATION // fake_gemini.STEP, f"barcha gaplar bor, takrorsiz ({n0} / {fake_gemini.YT_DURATION // fake_gemini.STEP})")
        check("Bu 0-gap" in editor and "Bu 74-gap" in editor, "boshidan oxirigacha")
        check(editor.count("Bu 29-gap") == 1 and editor.count("Bu 30-gap") == 1, "uzilgan joyda takror yoki yo'qotish yo'q")
        await pg.screenshot(path=str(out / "23_cloud_result_uz.png"), full_page=True)

        await pg.click(".tabs button:has-text('Segmentlar')")
        await pg.wait_for_selector(".sg .w.unc")
        check(await pg.locator(".sg .w.unc").count() > 0, "[eshitilmadi] noaniq deb belgilandi")

        await pg.click(".tabs button.tab-ai")
        await pg.wait_for_selector("text=O‘zbekcha nutq sinovi", timeout=10000)
        check(await pg.locator(".an-steps li").count() == 1, "amaliy qadamlar ko'rsatildi")
        check(await pg.locator(".an-facts .badge").count() == 1, "tekshirish kerak bo'lgan fakt belgilandi")
        await pg.screenshot(path=str(out / "24_cloud_summary_uz.png"), full_page=True)
        async with pg.expect_download() as d:
            await pg.click(".an-head button:has-text('.md')")
        md = Path(await (await d.value).path()).read_text("utf-8")
        check(md.startswith("# O‘zbekcha nutq sinovi") and "## Nimalar qilish kerak" in md, "xulosa .md yuklab olindi")

        await pg.click(".tabs button:has-text('Tahrirlangan')")
        await pg.fill("textarea.editor", editor + "\nQo‘shimcha tahrir.")
        await pg.wait_for_selector("text=Saqlandi", timeout=10000)
        await pg.wait_for_timeout(1300)
        async with pg.expect_download() as d:
            await pg.click("button.btn-primary.desk-only:has-text('Yuklab olish')")
        txt = Path(await (await d.value).path()).read_text("utf-8")
        check(txt.rstrip().endswith("Qo‘shimcha tahrir.") and "o‘zbekcha" in txt, "TXT eksport tahrir bilan, UTF-8")
        await pg.click("button:has-text('Boshqa formatlar')")
        async with pg.expect_download() as d:
            await pg.click(".menu button:has-text('SRT')")
        srt = Path(await (await d.value).path()).read_text("utf-8")
        check(srt.startswith("1\n00:00:00,000 --> 00:00:20,000\n"), "SRT eksport")
        await pg.reload()
        await pg.wait_for_selector("textarea.editor")
        check((await pg.locator("textarea.editor").input_value()).rstrip().endswith("Qo‘shimcha tahrir."), "tahrir sahifa yangilangandan keyin saqlanib qoldi")

        # ---------- 2) Katta fayl: Files API + parchalar + to'xtab davom etish ----------
        await pg.goto(url)
        await pg.click(".src-tabs button:has-text('Fayl')")
        await pg.set_input_files("input[type=file]", str(big))
        await pg.wait_for_selector("text=Fayl tayyor")
        await pg.locator(".card-cta button.btn-primary").click()
        await pg.wait_for_url("**/#/c/*")
        await pg.wait_for_selector("text=Gemini yozayotgan matn")
        # matn yozila boshlaganda sahifani yangilaymiz -> "to'xtatilgan" -> davom ettirish
        fake_gemini.CHUNK_DELAY = 0.3
        await pg.wait_for_function("document.querySelectorAll('.segs .sg:not(.live)').length >= 4", timeout=60000)
        await pg.reload()
        fake_gemini.CHUNK_DELAY = 0.02
        try:
            await pg.wait_for_selector("text=Davom ettirish", timeout=15000)
        except Exception:
            await pg.screenshot(path=str(out / "fail.png"), full_page=True)
            print(await pg.inner_text("main"))
            raise
        await pg.screenshot(path=str(out / "25_cloud_paused_uz.png"), full_page=True)
        await pg.click("button:has-text('Davom ettirish')")
        await pg.wait_for_selector(".res-grid", timeout=120000)
        st = json.load(urllib.request.urlopen(gbase + "/__state"))
        files = [r for r in st["requests"] if '"fileUri": "http' in json.dumps(r["media"]) and "youtube" not in json.dumps(r["media"])]
        check(len(files) >= 3, f"fayl Files API orqali yuklandi va parchalarda yuborildi ({len(files)} so'rov)")
        check(any("endOffset" in json.dumps(r["media"]) for r in files), "parcha chegaralari (videoMetadata) yuborildi")
        editor = await pg.locator("textarea.editor").input_value()
        want = fake_gemini.FILE_DURATION // fake_gemini.STEP
        got = sorted({int(x.split("-gap")[0].split("Bu ")[-1]) for x in editor.split("\n") for x in x.split(". ") if "-gap" in x})
        check(len(got) >= want - 2 and got[0] == 0 and got[-1] == want - 1, f"40 daqiqalik fayl to'liq ({len(got)}/{want})")
        check(len(editor.split("Bu 45-gap")) == 2, "parchalar chegarasida takror yo'q")
        await pg.screenshot(path=str(out / "26_cloud_file_result_uz.png"), full_page=True)

        await pg.goto(url + "#/history")
        await pg.wait_for_selector("text=uzun_podkast.mp3")
        check(await pg.locator(".card .row.gap12").count() >= 2, "tarixda ikkala ish bor")
        await pg.screenshot(path=str(out / "27_cloud_history_uz.png"), full_page=True)
        await ctx.close()

        # ---------- 3) Noto'g'ri (yopiq) YouTube video — tushunarli xato ----------
        ctx, pg = await page_for(1280, 900, "dark", "ru")
        await pg.goto(url)
        await pg.evaluate(f"localStorage.setItem('ilmhubstt.geminiKey', '{KEY}')")
        await pg.reload()
        await pg.fill("input[type=url]", "https://youtu.be/BADVIDEO123")
        await pg.wait_for_selector(".yt-row >> text=YouTube · BADVIDEO123", timeout=15000)
        await pg.locator(".card-cta button.btn-primary").click()
        await pg.wait_for_selector("text=Видео должно быть открытым", timeout=30000)
        check(True, "yopiq video: tushunarli xato (RU)")
        await pg.screenshot(path=str(out / "28_cloud_error_dark_ru.png"), full_page=True)
        await ctx.close()

        # ---------- 4) Telefon ----------
        ctx, pg = await page_for(390, 844, "dark", "uz", mobile=True)
        await pg.goto(url)
        await pg.wait_for_selector("text=YouTube yoki audio/video havolasini qo‘ying")
        sw = await pg.evaluate("document.documentElement.scrollWidth")
        check(sw <= 390, f"telefonda gorizontal scroll yo'q ({sw})")
        await pg.screenshot(path=str(out / "29_cloud_mobile_dark_uz.png"), full_page=True)
        await pg.evaluate(f"localStorage.setItem('ilmhubstt.geminiKey', '{KEY}')")
        await pg.fill("input[type=url]", YT)
        await pg.wait_for_selector(".yt-row >> text=YouTube · dQw4w9WgXcQ", timeout=15000)
        await pg.locator(".mobile-cta button.btn-primary").click()
        await pg.wait_for_selector(".res-grid", timeout=90000)
        await pg.click(".tabs button.tab-ai")
        await pg.wait_for_selector("text=O‘zbekcha nutq sinovi", timeout=10000)
        sw = await pg.evaluate("document.documentElement.scrollWidth")
        check(sw <= 390, f"telefonda xulosa sahifasi sig'adi ({sw})")
        await pg.screenshot(path=str(out / "30_cloud_mobile_summary_uz.png"), full_page=True)
        await ctx.close()
        await browser.close()

    print("\n".join("  ✓ " + m for m in ok))
    if problems:
        print("\nMUAMMOLAR:\n" + "\n".join("  ✗ " + m for m in problems))
        return 1
    print(f"\nHammasi o'tdi: {len(ok)} tekshiruv")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    a = ap.parse_args()
    sys.exit(asyncio.run(run(Path(a.out))))
