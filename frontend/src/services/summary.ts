// Transkripsiyadan tuzilgan xulosa va tahlil (Gemini, JSON sxema bilan).
import { addUsage, emptyUsage, generate, GeminiError, Usage } from "./gemini";
import { idbGet, idbPut } from "./idb";

export interface Summary {
  title: string;
  genre: string;
  overview: string;
  audience: string;
  main_idea: string;
  sections: { start: string; title: string; summary: string }[];
  key_points: string[];
  facts: { fact: string; time: string; check: boolean }[];
  real_life: { idea: string; how: string }[];
  actions: { step: string; why: string; when: string }[];
  quotes: { text: string; time: string; speaker: string }[];
  terms: { term: string; meaning: string }[];
  questions: string[];
  conclusion: string;
}
export interface StoredSummary { summary: Summary; lang: string; model: string; created: number; usage: Usage }

const S = (description: string) => ({ type: "STRING", description });
const SCHEMA = {
  type: "OBJECT",
  properties: {
    title: S("Short, specific title of the recording"),
    genre: S("Type of content: podcast, lecture, interview, sermon, news, lesson, meeting, etc."),
    overview: S("What the recording is about: 3-6 sentences"),
    audience: S("Who will benefit most from it, one sentence"),
    main_idea: S("The single central message in one sentence"),
    sections: {
      type: "ARRAY", description: "Timeline of the recording: 3-12 parts in order",
      items: { type: "OBJECT", properties: { start: S("HH:MM:SS when the part starts"), title: S("part title"), summary: S("1-3 sentences") }, required: ["start", "title", "summary"] },
    },
    key_points: { type: "ARRAY", description: "5-12 most important ideas", items: { type: "STRING" } },
    facts: {
      type: "ARRAY", description: "Concrete facts, numbers, names, dates, claims and examples stated in the recording",
      items: { type: "OBJECT", properties: { fact: S("the fact as stated"), time: S("HH:MM:SS"), check: { type: "BOOLEAN", description: "true if it is a statistic or claim worth double-checking" } }, required: ["fact", "time", "check"] },
    },
    real_life: {
      type: "ARRAY", description: "How the ideas connect to everyday life, work, study or family",
      items: { type: "OBJECT", properties: { idea: S("the idea"), how: S("a concrete real-life situation or example") }, required: ["idea", "how"] },
    },
    actions: {
      type: "ARRAY", description: "Practical steps the listener can take, 3-10, most important first",
      items: { type: "OBJECT", properties: { step: S("the action, starting with a verb"), why: S("why it matters, based on the recording"), when: S("when/how often: today, this week, daily...") }, required: ["step", "why", "when"] },
    },
    quotes: {
      type: "ARRAY", description: "2-6 memorable quotes, copied exactly from the transcript in its original language",
      items: { type: "OBJECT", properties: { text: S("exact quote"), time: S("HH:MM:SS"), speaker: S("speaker if known, else empty") }, required: ["text", "time", "speaker"] },
    },
    terms: {
      type: "ARRAY", description: "Important terms or names explained (0-10)",
      items: { type: "OBJECT", properties: { term: S("term"), meaning: S("short explanation") }, required: ["term", "meaning"] },
    },
    questions: { type: "ARRAY", description: "3-5 questions for reflection or discussion", items: { type: "STRING" } },
    conclusion: S("Final takeaway: 2-4 sentences"),
  },
  required: ["title", "genre", "overview", "audience", "main_idea", "sections", "key_points", "facts", "real_life", "actions", "quotes", "terms", "questions", "conclusion"],
};

const LANG: Record<string, string> = {
  uz: "Uzbek (modern Latin alphabet, correct orthography with o‘ g‘ and ’)",
  ru: "Russian",
  en: "English",
};

export function summaryPrompt(lang: string, title: string): string {
  return [
    "You are an expert editor and analyst. Below is a time-stamped transcript of an audio/video recording" + (title ? ` titled "${title}"` : "") + ".",
    `Write a structured, practical analysis in ${LANG[lang] || LANG.uz}. Quotes stay in the original language of the transcript.`,
    "Rules:",
    "- Base everything ONLY on the transcript. Do not invent facts, names, numbers or advice that are not supported by it.",
    "- If the transcript contains errors, interpret them sensibly but never fabricate content.",
    "- Times must come from the transcript time stamps (HH:MM:SS).",
    "- Real-life connections and actions must follow from the ideas in the recording and be concrete and useful.",
    "- Be clear and concise; avoid filler phrases.",
    "",
    "TRANSCRIPT:",
  ].join("\n");
}

function parseJson(text: string): any {
  const t = text.trim().replace(/^```[a-z]*\s*/i, "").replace(/```\s*$/, "");
  try { return JSON.parse(t); } catch { /* */ }
  const a = t.indexOf("{");
  const b = t.lastIndexOf("}");
  if (a >= 0 && b > a) { try { return JSON.parse(t.slice(a, b + 1)); } catch { /* */ } }
  return null;
}

const arr = (v: any) => (Array.isArray(v) ? v : []);
const str = (v: any) => (typeof v === "string" ? v.trim() : v == null ? "" : String(v));

export function normalizeSummary(d: any): Summary {
  return {
    title: str(d?.title), genre: str(d?.genre), overview: str(d?.overview), audience: str(d?.audience), main_idea: str(d?.main_idea),
    sections: arr(d?.sections).map((x: any) => ({ start: str(x?.start), title: str(x?.title), summary: str(x?.summary) })).filter((x: any) => x.title || x.summary),
    key_points: arr(d?.key_points).map(str).filter(Boolean),
    facts: arr(d?.facts).map((x: any) => ({ fact: str(x?.fact ?? x), time: str(x?.time), check: !!x?.check })).filter((x: any) => x.fact),
    real_life: arr(d?.real_life).map((x: any) => ({ idea: str(x?.idea ?? x), how: str(x?.how) })).filter((x: any) => x.idea),
    actions: arr(d?.actions).map((x: any) => ({ step: str(x?.step ?? x), why: str(x?.why), when: str(x?.when) })).filter((x: any) => x.step),
    quotes: arr(d?.quotes).map((x: any) => ({ text: str(x?.text ?? x), time: str(x?.time), speaker: str(x?.speaker) })).filter((x: any) => x.text),
    terms: arr(d?.terms).map((x: any) => ({ term: str(x?.term), meaning: str(x?.meaning) })).filter((x: any) => x.term),
    questions: arr(d?.questions).map(str).filter(Boolean),
    conclusion: str(d?.conclusion),
  };
}

export async function makeSummary(transcript: string, lang: string, title: string,
  opts: { signal?: AbortSignal; onStatus?: (s: string, d: any) => void; onProgress?: (chars: number) => void } = {}): Promise<StoredSummary> {
  if (!transcript.trim()) throw new GeminiError("summary_empty");
  const res = await generate([{ text: summaryPrompt(lang, title) + "\n" + transcript }], {
    json: true, schema: SCHEMA, signal: opts.signal, onStatus: opts.onStatus, onText: (t) => opts.onProgress?.(t.length),
  });
  const data = parseJson(res.text);
  if (!data) throw new GeminiError("summary_bad_json", res.text.slice(0, 200));
  return { summary: normalizeSummary(data), lang, model: res.model, created: Date.now(), usage: addUsage(emptyUsage(), res.usage, res.model) };
}

export const loadSummary = (key: string) => idbGet<StoredSummary>("summaries", key);
export const storeSummary = (key: string, s: StoredSummary) => idbPut("summaries", key, s);

export function parseHms(s: string): number | null {
  const m = /^(?:(\d+):)?(\d{1,2}):(\d{2})/.exec(s.trim());
  if (!m) return null;
  return (m[1] ? +m[1] * 3600 : 0) + +m[2] * 60 + +m[3];
}

/** Markdown ko'rinishi (yuklab olish va nusxalash uchun). */
export function summaryMarkdown(s: Summary, L: Record<string, string>): string {
  const o: string[] = [];
  o.push(`# ${s.title || L.title}`);
  if (s.genre) o.push(`*${s.genre}*`);
  o.push("", `## ${L.overview}`, s.overview);
  if (s.main_idea) o.push("", `**${L.main_idea}:** ${s.main_idea}`);
  if (s.audience) o.push("", `**${L.audience}:** ${s.audience}`);
  if (s.key_points.length) o.push("", `## ${L.key_points}`, ...s.key_points.map((x) => `- ${x}`));
  if (s.sections.length) o.push("", `## ${L.sections}`, ...s.sections.map((x) => `- **${x.start} — ${x.title}.** ${x.summary}`));
  if (s.facts.length) o.push("", `## ${L.facts}`, ...s.facts.map((x) => `- ${x.fact}${x.time ? ` (${x.time})` : ""}${x.check ? ` ⚠ ${L.check}` : ""}`));
  if (s.real_life.length) o.push("", `## ${L.real_life}`, ...s.real_life.map((x) => `- **${x.idea}** — ${x.how}`));
  if (s.actions.length) o.push("", `## ${L.actions}`, ...s.actions.map((x, i) => `${i + 1}. **${x.step}** — ${x.why}${x.when ? ` _(${x.when})_` : ""}`));
  if (s.quotes.length) o.push("", `## ${L.quotes}`, ...s.quotes.map((x) => `> «${x.text}»${x.speaker ? ` — ${x.speaker}` : ""}${x.time ? ` (${x.time})` : ""}`));
  if (s.terms.length) o.push("", `## ${L.terms}`, ...s.terms.map((x) => `- **${x.term}** — ${x.meaning}`));
  if (s.questions.length) o.push("", `## ${L.questions}`, ...s.questions.map((x) => `- ${x}`));
  if (s.conclusion) o.push("", `## ${L.conclusion}`, s.conclusion);
  return o.join("\n") + "\n";
}
