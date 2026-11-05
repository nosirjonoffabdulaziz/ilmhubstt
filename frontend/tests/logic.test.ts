// Brauzer rejimi mantiqining unit testlari: node tests/run.mjs
import assert from "node:assert/strict";
import { parseTranscript, mergeLines, buildResult, transcriptPrompt, guessMime, paragraphsText, CloudJob } from "../src/services/cloud";
import { youtubeId } from "../src/services/youtube";
import { rankModels, parseSSE, addUsage, emptyUsage } from "../src/services/gemini";
import { renderExport } from "../src/services/exportLocal";
import { normalizeSummary, summaryMarkdown, parseHms } from "../src/services/summary";

const tests: [string, () => void][] = [];
const test = (n: string, f: () => void) => tests.push([n, f]);

test("youtubeId: barcha havola turlari", () => {
  const id = "dQw4w9WgXcQ";
  for (const u of [`https://www.youtube.com/watch?v=${id}`, `https://youtu.be/${id}?si=abc`, `youtube.com/shorts/${id}`,
    `https://m.youtube.com/watch?v=${id}&t=30s`, `https://www.youtube.com/live/${id}`, `https://music.youtube.com/watch?v=${id}&list=x`,
    `https://www.youtube.com/embed/${id}`]) assert.equal(youtubeId(u), id, u);
  for (const u of ["https://example.com/a.mp3", "https://youtube.com/watch?v=short", "salom", "https://vimeo.com/123"]) assert.equal(youtubeId(u), null, u);
});

test("parseTranscript: vaqtlar, abzaslar, ortiqcha belgilar", () => {
  const raw = "```\n[00:00:01] Assalomu alaykum.\n[00:00:07] Bugun mavzu — ta’lim.\n\n**[00:01:02]** Yangi abzas\ndavomi shu yerda.\n01:05:03 - Soat bilan\n```";
  const l = parseTranscript(raw);
  assert.equal(l.length, 4);
  assert.deepEqual(l.map((x) => x.start), [1, 7, 62, 3903]);
  assert.equal(l[0].para, true);
  assert.equal(l[1].para, false);
  assert.equal(l[2].para, true);
  assert.equal(l[2].text, "Yangi abzas davomi shu yerda.");
  assert.equal(l[3].text, "Soat bilan");
});

test("mergeLines: nisbiy vaqtni siljitish va takrorni olib tashlash", () => {
  const all = [{ start: 880, end: 895, text: "Oldingi gap.", para: false }];
  const lines = parseTranscript("[00:00:00] Oldingi gap.\n[00:00:10] Yangi gap bir.\n[00:00:10] Yangi gap bir.\n[00:00:30] Ikkinchi.");
  const out = mergeLines(all, lines, 900, 1800, true);
  assert.deepEqual(out.map((x) => [x.start, x.text]), [[910, "Yangi gap bir."], [930, "Ikkinchi."]]);
});

test("mergeLines: model nisbiy o'rniga mutlaq vaqt yozsa ham to'g'ri", () => {
  const lines = parseTranscript("[00:15:05] A.\n[00:16:00] B.\n[00:29:00] C.");
  const out = mergeLines([], lines, 900, 1800, true);
  assert.deepEqual(out.map((x) => x.start), [905, 960, 1740]);
});

test("mergeLines: kesishsiz rejimda mutlaq vaqt, orqaga sakrash tashlanadi", () => {
  const all = [{ start: 600, end: 610, text: "X", para: false }];
  const lines = parseTranscript("[00:10:20] Bir.\n[00:02:00] Aylana takror.\n[00:10:40] Ikki.");
  const out = mergeLines(all, lines, 610, undefined, false);
  assert.deepEqual(out.map((x) => x.text), ["Bir.", "Ikki."]);
});

test("buildResult: so'zlar, noaniq belgilar, matn", () => {
  const job = {
    id: "a".repeat(32), kind: "cloud", created: 0, source: { type: "youtube", name: "Video", videoId: "dQw4w9WgXcQ" },
    options: { language: "uz", mode: "clean", script: "latin", vocabulary: "" }, status: "completed", stage: "", progress: 100, detail: {},
    error: null, duration: 30, processed: 30, live: [], usage: emptyUsage(), model: "gemini-3-flash-preview", started: 0, finished: 1000, warnings: [],
    segments: [{ start: 0, end: 10, text: "Salom, bu [eshitilmadi] so‘z.", para: true }, { start: 10, end: 20, text: "Ikkinchi gap.", para: false },
      { start: 20, end: 30, text: "Yangi abzas.", para: true }],
  } as unknown as CloudJob;
  const r = buildResult(job);
  assert.equal(r.stats.words, 8);
  assert.equal(r.stats.uncertain, 1);
  assert.equal(r.edited_text, "Salom, bu [eshitilmadi] so‘z. Ikkinchi gap.\n\nYangi abzas.");
  const w = r.segments[0].words;
  assert.ok(w.every((x, i) => i === 0 || x.s >= w[i - 1].s));
  assert.match(r.model, /gemini/i);
  const srt = renderExport(r, r.edited_text, "srt").body;
  assert.match(srt, /^1\n00:00:00,000 --> 00:00:10,000\nSalom/);
  assert.match(renderExport(r, r.edited_text, "vtt").body, /^WEBVTT\n\n00:00:00.000 --> /);
  assert.equal(JSON.parse(renderExport(r, r.edited_text, "json").body).segments.length, 3);
  assert.equal(paragraphsText(job.segments), r.edited_text);
});

test("prompt: o'zbek lotin qoidalari, davom ettirish", () => {
  const p = transcriptPrompt({ language: "uz", mode: "clean", script: "latin", vocabulary: "ILMHUB, Dilshod" }, true, { from: 600, relative: false, tail: ["[00:09:50] Oxirgi."] });
  assert.match(p, /LATIN/);
  assert.match(p, /Continue from 00:10:00/);
  assert.match(p, /ILMHUB, Dilshod/);
  assert.match(p, /\[00:09:50\] Oxirgi\./);
  const q = transcriptPrompt({ language: "kk", mode: "verbatim", script: "original", vocabulary: "" }, false, { from: 900, to: 1800, relative: true, tail: [] });
  assert.match(q, /KAZAKH/);
  assert.match(q, /excerpt/);
});

test("rankModels: eng yangi flash birinchi, tts/embedding chiqariladi", () => {
  const r = rankModels(["gemini-2.5-flash", "gemini-3-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash-preview-tts", "gemini-3.1-flash-lite", "gemini-embedding-001"]);
  assert.equal(r[0], "gemini-3-flash-preview");
  assert.ok(!r.includes("gemini-2.5-flash-preview-tts"));
  assert.ok(!r.includes("gemini-embedding-001"));
});

test("parseSSE: bo'lingan oqim", () => {
  const a = parseSSE('data: {"a":1}\r\n\r\ndata: {"b"');
  assert.deepEqual(a.events, [{ a: 1 }]);
  const b = parseSSE(a.rest + ':2}\n\n');
  assert.deepEqual(b.events, [{ b: 2 }]);
});

test("addUsage: audio narxi alohida", () => {
  const u = addUsage(emptyUsage(), { promptTokenCount: 115600, candidatesTokenCount: 20000, promptTokensDetails: [{ modality: "AUDIO", tokenCount: 115200 }] }, "gemini-3-flash-preview");
  assert.ok(Math.abs(u.cost_usd - (115200 * 1 + 400 * 0.5 + 20000 * 3) / 1e6) < 1e-9);
});

test("guessMime", () => {
  assert.equal(guessMime("a.M4A"), "audio/mp4");
  assert.equal(guessMime("https://x.uz/b.mp3?x=1"), "audio/mpeg");
  assert.equal(guessMime("video.mov"), "video/quicktime");
  assert.equal(guessMime("noext", "audio/x-m4a"), "audio/mp4");
});

test("summary: normalize va markdown", () => {
  const s = normalizeSummary({ title: "T", overview: "O", key_points: ["a", "", 3], facts: [{ fact: "F", time: "00:01:00", check: true }], actions: ["Qil"] });
  assert.deepEqual(s.key_points, ["a", "3"]);
  assert.equal(s.actions[0].step, "Qil");
  const md = summaryMarkdown(s, { title: "", overview: "Nima haqida", main_idea: "", audience: "", key_points: "Fikrlar", sections: "", facts: "Faktlar", check: "tekshiring", real_life: "", actions: "Qadamlar", quotes: "", terms: "", questions: "", conclusion: "" });
  assert.match(md, /^# T/);
  assert.match(md, /- F \(00:01:00\) ⚠ tekshiring/);
  assert.equal(parseHms("01:02:03"), 3723);
  assert.equal(parseHms("02:03"), 123);
});

let fail = 0;
for (const [n, f] of tests) {
  try { f(); console.log("ok   -", n); } catch (e) { fail++; console.log("FAIL -", n, "\n", e); }
}
console.log(`\n${tests.length - fail}/${tests.length} o'tdi`);
if (fail) process.exit(1);
