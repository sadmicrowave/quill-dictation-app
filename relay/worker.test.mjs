// Run:  node --test relay/worker.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import worker, { validate, buildIssue } from "./worker.js";

const SYS = "2026-11-07 12:12:47,533 INFO SYS Microphone on";
const good = { kind: "problem", message: "It stopped", contact: "me@example.com", facts: { Quill: "0.1.0" }, log: [SYS] };
const post = (body, headers = {}) => new Request("https://relay.example/", { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body), headers });

test("only SYS lines survive", () => {
  const r = validate({ ...good, log: [SYS, "2026-11-07 12:12:47,533 INFO USR Connected to Budget.xlsx", "free text"] });
  assert.deepEqual(r.log, [SYS]);
});

test("a report needs a message", () => assert.equal(validate({ ...good, message: "  " }), null));
test("sizes are capped", () => {
  const r = validate({ ...good, message: "x".repeat(9000), log: Array(900).fill(SYS) });
  assert.equal(r.message.length, 4000);
  assert.equal(r.log.length, 400);
});

test("@mentions are defused and the reply address is stored only when allowed", () => {
  const r = validate({ ...good, message: "ping @octocat" });
  const hidden = buildIssue(r, false);
  assert.ok(!hidden.body.includes("me@example.com"));
  assert.ok(!hidden.body.includes("@octocat"));
  assert.ok(buildIssue(r, true).body.includes("me\u0040\u200bexample.com"));
});

test("a good report creates an issue and returns its number", async () => {
  let sent;
  globalThis.fetch = async (url, init) => { sent = { url, init }; return new Response(JSON.stringify({ number: 42 }), { status: 201 }); };
  const res = await worker.fetch(post(good), { GITHUB_REPO: "o/r", GITHUB_TOKEN: "t", INCLUDE_CONTACT: "false" });
  assert.deepEqual(await res.json(), { ok: true, reference: "#42" });
  assert.equal(sent.url, "https://api.github.com/repos/o/r/issues");
  assert.equal(sent.init.headers.authorization, "Bearer t");
  assert.deepEqual(JSON.parse(sent.init.body).labels, ["support", "problem"]);
});

test("bad input never reaches GitHub", async () => {
  globalThis.fetch = async () => { throw new Error("must not be called"); };
  assert.equal((await worker.fetch(post("not json"), {})).status, 400);
  assert.equal((await worker.fetch(post({ message: "" }), {})).status, 400);
  assert.equal((await worker.fetch(new Request("https://relay.example/"), {})).status, 405);
});

test("the rate limit answers 429", async () => {
  const env = { LIMITER: { limit: async () => ({ success: false }) } };
  assert.equal((await worker.fetch(post(good), env)).status, 429);
});

test("a GitHub failure is a 502 without details", async () => {
  globalThis.fetch = async () => new Response("no", { status: 401 });
  const res = await worker.fetch(post(good), { GITHUB_REPO: "o/r", GITHUB_TOKEN: "bad" });
  assert.equal(res.status, 502);
  assert.deepEqual(await res.json(), { ok: false, error: "could not create the issue" });
});
