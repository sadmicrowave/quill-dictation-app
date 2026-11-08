// Quill support relay: receives a problem report from the app and opens an issue on GitHub.
//
// The app holds only this relay's public address. The GitHub token lives here, as a Cloudflare secret, so it can be
// replaced or revoked at any time without releasing a new version of Quill.
//
// Defence in depth: the app sends only SYS log lines, and this relay drops anything else, caps every size,
// takes the reply address only when INCLUDE_CONTACT is "true" (use that only with a private repository), and
// defuses @mentions so a report cannot notify strangers.

const MAX_BODY = 80_000;
const MAX_MESSAGE = 4000;
const MAX_LOG_LINES = 400;
const MAX_LINE = 400;
const KINDS = new Set(["problem", "crash"]);
const SYS_LINE = /^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} [A-Z]+ SYS /;
const HOURLY_LIMIT = 5;

const reply = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const defuse = (text) => text.replace(/@/g, "@\u200b");           // an @name inside a report notifies nobody

export function validate(data) {
  if (!data || typeof data !== "object") return null;
  const kind = KINDS.has(data.kind) ? data.kind : "problem";
  const message = typeof data.message === "string" ? data.message.trim().slice(0, MAX_MESSAGE) : "";
  if (!message) return null;
  const contact = typeof data.contact === "string" ? data.contact.trim().slice(0, 200) : "";
  const facts = {};
  if (data.facts && typeof data.facts === "object") {
    for (const [key, value] of Object.entries(data.facts).slice(0, 20)) {
      facts[String(key).slice(0, 40)] = String(value).slice(0, 200);
    }
  }
  const log = (Array.isArray(data.log) ? data.log : [])
    .filter((line) => typeof line === "string" && SYS_LINE.test(line))      // anything not labelled SYS is dropped
    .slice(-MAX_LOG_LINES)
    .map((line) => line.slice(0, MAX_LINE));
  return { kind, message, contact, facts, log };
}

export function buildIssue(report, includeContact) {
  const first = report.message.split("\n")[0].slice(0, 70);
  const lines = [];
  lines.push(report.kind === "crash" ? "_Quill hit an unexpected error last time._" : "_Sent from the Report a Problem form._", "");
  lines.push("### What happened", "", defuse(report.message), "");
  lines.push("### About this copy", "", ...Object.entries(report.facts).map(([k, v]) => `- **${defuse(k)}:** ${defuse(v)}`), "");
  if (includeContact && report.contact) lines.push("### Reply address", "", defuse(report.contact), "");
  else if (report.contact) lines.push("_A reply address was given but is not stored in this issue._", "");
  if (report.log.length) lines.push(`### Diagnostic log (${report.log.length} SYS lines)`, "", "```", ...report.log, "```");
  return { title: `[${report.kind}] ${defuse(first)}`, body: lines.join("\n"), labels: ["support", report.kind] };
}

async function allowed(request, env) {
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  if (env.LIMITER) {                                                   // Cloudflare rate-limit binding (per minute)
    const { success } = await env.LIMITER.limit({ key: ip });
    if (!success) return false;
  }
  if (env.RATE) {                                                      // optional KV counter (per hour)
    const key = `${ip}:${new Date().toISOString().slice(0, 13)}`;
    const count = Number(await env.RATE.get(key)) || 0;
    if (count >= HOURLY_LIMIT) return false;
    await env.RATE.put(key, String(count + 1), { expirationTtl: 3700 });
  }
  return true;
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return reply({ ok: false, error: "POST only" }, 405);
    if (Number(request.headers.get("content-length") || 0) > MAX_BODY) return reply({ ok: false, error: "too large" }, 413);
    if (!(await allowed(request, env))) return reply({ ok: false, error: "rate limited" }, 429);

    let data;
    try {
      const text = await request.text();
      if (text.length > MAX_BODY) return reply({ ok: false, error: "too large" }, 413);
      data = JSON.parse(text);
    } catch {
      return reply({ ok: false, error: "bad request" }, 400);
    }
    const report = validate(data);
    if (!report) return reply({ ok: false, error: "bad request" }, 400);

    const issue = buildIssue(report, env.INCLUDE_CONTACT === "true");
    const response = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/issues`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${env.GITHUB_TOKEN}`,
        accept: "application/vnd.github+json",
        "user-agent": "quill-support-relay",
        "x-github-api-version": "2022-11-28",
      },
      body: JSON.stringify(issue),
    });
    if (!response.ok) return reply({ ok: false, error: "could not create the issue" }, 502);
    const created = await response.json();
    return reply({ ok: true, reference: `#${created.number}` });
  },
};
