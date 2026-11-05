"""Brauzerda to'liq E2E test (Playwright + Chrome). Ixtiyoriy vosita.

  pip install playwright && playwright install chromium
  python scripts/e2e_browser.py --audio test.mp3 --out screenshots/

Demo dvigatel bilan server ishga tushiriladi, haqiqiy yuklash -> progress -> natija -> tahrir ->
eksport oqimi bosiladi, konsol xatolari yig'iladi va skrinshotlar olinadi.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def run(audio: Path, out: Path, chrome: str | None) -> int:
    from playwright.async_api import async_playwright

    out.mkdir(parents=True, exist_ok=True)
    port = free_port()
    data = Path(tempfile.mkdtemp(prefix="stt-e2e-"))
    env = {**os.environ, "PORT": str(port), "DATA_DIR": str(data), "ENABLE_DUMMY_ENGINE": "1",
           "ASR_ENGINE": "dummy", "DUMMY_SPEED": "25", "RATE_LIMIT_PER_HOUR": "0"}
    proc = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT / "backend", env=env,
                            stdout=open(data / "server.log", "wb"), stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if requests.get(url + "/api/v1/health", timeout=1).ok:
                break
        except requests.RequestException:
            time.sleep(0.1)
    problems: list[str] = []
    try:
        async with async_playwright() as p:
            kw = {"executable_path": chrome} if chrome else {}
            browser = await p.chromium.launch(args=["--no-sandbox"], **kw)

            async def page_for(w, h, theme, lang, mobile=False):
                ctx = await browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2,
                                                is_mobile=mobile, has_touch=mobile, accept_downloads=True, bypass_csp=True,
                                                color_scheme=theme)
                await ctx.add_init_script(
                    f"localStorage.setItem('ilmhubstt.prefs', JSON.stringify({{lang:'{lang}', theme:'{theme}'}}))")
                pg = await ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "status of 422" not in m.text and problems.append(f"console[{lang}/{w}]: {m.text}"))
                pg.on("pageerror", lambda e: problems.append(f"pageerror[{lang}/{w}]: {e}"))
                return ctx, pg

            # ---- 1) Desktop light UZ: to'liq oqim ----
            ctx, pg = await page_for(1440, 900, "light", "uz")
            await pg.goto(url)
            await pg.wait_for_selector("text=Matnga aylantirish")
            await pg.screenshot(path=str(out / "01_desktop_home_empty_light_uz.png"), full_page=True)
            await pg.set_input_files("input[type=file]", str(audio))
            await pg.wait_for_selector("text=Fayl tayyor")
            await pg.fill("input.input", "ILMHUB, Samarqand")
            await pg.screenshot(path=str(out / "02_desktop_home_file_light_uz.png"), full_page=True)
            await pg.click(".card-cta button.btn-primary")
            await pg.wait_for_selector("text=Matnga aylantirilmoqda", timeout=30000)
            await pg.wait_for_function("document.querySelector('.pbar i') && parseFloat(document.querySelector('.pbar i').style.width) > 20", timeout=60000)
            await pg.screenshot(path=str(out / "03_desktop_progress_light_uz.png"), full_page=True)
            await pg.wait_for_selector(".editor", timeout=120000)
            await pg.screenshot(path=str(out / "04_desktop_result_editor_light_uz.png"), full_page=True)
            await pg.click(".tabs button:nth-child(2)")
            await pg.wait_for_selector(".sg .unc")
            await pg.click(".sg .unc >> nth=0")
            await pg.wait_for_selector(".pop")
            await pg.screenshot(path=str(out / "05_desktop_result_segments_light_uz.png"), full_page=True)
            await pg.keyboard.press("Escape")
            await pg.click("body", position={"x": 5, "y": 5})
            # tahrir va avtomatik saqlash
            await pg.click(".tabs button:nth-child(1)")
            await pg.fill(".editor", "Tahrir sinovi: o‘zbekcha g‘alaba, ma’no.")
            await pg.wait_for_selector("text=Saqlandi", timeout=10000)
            await asyncio.sleep(1.5)
            async with pg.expect_download() as dl_info:
                await pg.click(".res-actions .btn-primary")
            dl = await dl_info.value
            path = await dl.path()
            content = Path(path).read_text(encoding="utf-8")
            if content != "Tahrir sinovi: o‘zbekcha g‘alaba, ma’no.\n":
                problems.append(f"TXT eksport mos emas: {content!r}")
            if not dl.suggested_filename.endswith("_ilmhubstt.txt"):
                problems.append(f"fayl nomi: {dl.suggested_filename}")
            # boshqa formatlar menyusi
            await pg.click(".res-actions button:has-text('Boshqa formatlar')")
            async with pg.expect_download() as d2:
                await pg.click(".menu button:has-text('SRT')")
            srt = Path(await (await d2.value).path()).read_text(encoding="utf-8")
            if "-->" not in srt:
                problems.append("SRT eksport bo'sh")
            # tarix
            await pg.goto(url + "/#/history")
            await pg.wait_for_selector("text=Tayyor")
            await pg.screenshot(path=str(out / "06_desktop_history_light_uz.png"), full_page=True)
            await ctx.close()

            # ---- 2) Desktop dark RU va EN ----
            for lang, name in (("ru", "07_desktop_result_dark_ru.png"), ("en", "08_desktop_home_dark_en.png")):
                ctx, pg = await page_for(1440, 900, "dark", lang)
                await pg.goto(url)
                await pg.wait_for_selector(".dz")
                if lang == "ru":
                    await pg.set_input_files("input[type=file]", str(audio))
                    await pg.wait_for_selector(".ok-t")
                    await pg.click(".card-cta button.btn-primary")
                    await pg.wait_for_selector(".editor", timeout=120000)
                    await pg.click(".tabs button:nth-child(2)")
                    await pg.wait_for_selector(".sg .unc")
                await pg.screenshot(path=str(out / name), full_page=True)
                await ctx.close()

            # ---- 3) Telefon (390x844) ----
            ctx, pg = await page_for(390, 844, "light", "uz", mobile=True)
            await pg.goto(url)
            await pg.wait_for_selector(".dz")
            await pg.screenshot(path=str(out / "09_mobile_home_light_uz.png"))
            await pg.set_input_files("input[type=file]", str(audio))
            await pg.wait_for_selector(".mobile-cta button.btn-primary:not([disabled])")
            await pg.evaluate("window.scrollTo(0, 620)")
            await pg.screenshot(path=str(out / "10_mobile_settings_light_uz.png"))
            await pg.click(".mobile-cta button.btn-primary")
            await pg.wait_for_selector("text=Matnga aylantirilmoqda", timeout=30000)
            await asyncio.sleep(2)
            await pg.screenshot(path=str(out / "11_mobile_progress_light_uz.png"))
            await pg.wait_for_selector(".editor", timeout=120000)
            await pg.click(".tabs button:nth-child(2)")
            await pg.wait_for_selector(".sg .unc")
            await pg.screenshot(path=str(out / "12_mobile_result_light_uz.png"))
            sw = await pg.evaluate("document.documentElement.scrollWidth")
            if sw > 390:
                problems.append(f"mobil: gorizontal scroll bor ({sw}px)")
            await ctx.close()

            ctx, pg = await page_for(390, 844, "dark", "uz", mobile=True)
            await pg.goto(url + "/#/settings")
            await pg.wait_for_selector("h1:has-text('Sozlamalar')")
            await pg.screenshot(path=str(out / "13_mobile_settings_page_dark_uz.png"))
            await pg.goto(url + "/#/")
            pdf = out / "_hujjat.pdf"
            pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
            await pg.set_input_files("input[type=file]", str(pdf))
            await pg.wait_for_selector(".ok-t, .err-t")
            await pg.click(".mobile-cta button.btn-primary")
            await pg.wait_for_selector(".note.err", timeout=15000)
            await pg.evaluate("window.scrollTo(0, 400)")
            await pg.screenshot(path=str(out / "14_mobile_error_dark_uz.png"))
            pdf.unlink()
            await ctx.close()
            # Turli kengliklarda gorizontal scroll yo'qligini tekshirish (har biri yangi sahifada)
            for w in (320, 360, 768, 1024, 1280):
                for path in ("/", "/#/history", "/#/settings"):
                    c2, p2 = await page_for(w, 800, "light", "uz", mobile=w < 700)
                    await p2.goto(url + path)
                    await p2.wait_for_selector(".hdr")
                    await asyncio.sleep(0.3)
                    sw = await p2.evaluate("document.documentElement.scrollWidth")
                    if sw > w:
                        wide = await p2.evaluate(f"""() => [...document.querySelectorAll('*')]
                            .filter(e => e.getBoundingClientRect().right > {w} + 0.5)
                            .slice(0, 5).map(e => e.tagName + '.' + e.className)""")
                        problems.append(f"{w}px {path}: gorizontal scroll ({sw}px) {wide}")
                    await c2.close()
            await browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    if problems:
        print("MUAMMOLAR:")
        for pr in problems:
            print(" -", pr)
        return 1
    print("E2E: hammasi o'tdi. Skrinshotlar:", out)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, type=Path)
    ap.add_argument("--out", default=ROOT / "docs" / "screenshots", type=Path)
    ap.add_argument("--chrome", default=None)
    a = ap.parse_args()
    sys.exit(asyncio.run(run(a.audio, a.out, a.chrome)))
