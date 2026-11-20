import test from "node:test";
import assert from "node:assert/strict";
import { handle, verifyMemberToken, adminToken, labelFor } from "./worker.js";

const SITE = "https://gapublicservice.org";
const env = { GHOST_SITE_URL: SITE, GHOST_ADMIN_URL: "https://example.ghost.io",
  GHOST_ADMIN_KEY: "abc123:" + "11".repeat(32), ALERTS_NEWSLETTER_ID: "nl-alerts" };

const b64url = (b) => Buffer.from(b).toString("base64url");
const { publicKey, privateKey } = await crypto.subtle.generateKey(
  { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-512" },
  true, ["sign", "verify"]);
const jwk = { ...(await crypto.subtle.exportKey("jwk", publicKey)), kid: "k1" };

async function memberToken(claims, kid = "k1", key = privateKey) {
  const head = b64url(JSON.stringify({ alg: "RS512", typ: "JWT", kid }));
  const body = b64url(JSON.stringify(claims));
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(head + "." + body));
  return head + "." + body + "." + b64url(new Uint8Array(sig));
}
const good = () => memberToken({ sub: "Reader@Example.org", iss: SITE + "/members/api", exp: Date.now() / 1000 + 600 });

function fakeGhost(member) {
  const calls = [];
  const f = async (url, init = {}) => {
    url = String(url);
    calls.push({ url, method: init.method || "GET", body: init.body && JSON.parse(init.body) });
    if (url.endsWith("/members/.well-known/jwks.json")) return Response.json({ keys: [jwk] });
    if (url.includes("/ghost/api/admin/members/?")) return Response.json({ members: member ? [member] : [] });
    if (url.includes("/ghost/api/admin/members/m1/")) return Response.json({ members: [member] });
    return new Response("no", { status: 404 });
  };
  f.calls = calls;
  return f;
}
const post = (body, origin = SITE) => new Request("https://follow.example/", {
  method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body: JSON.stringify(body) });

test("accepts a token signed by the site and returns the email", async () => {
  assert.equal(await verifyMemberToken(await good(), env, fakeGhost()), "reader@example.org");
});

test("rejects expired, foreign-issuer and wrongly signed tokens", async () => {
  const f = fakeGhost();
  assert.equal(await verifyMemberToken(await memberToken({ sub: "a@b.org", iss: SITE + "/members/api", exp: 1 }), env, f), null);
  assert.equal(await verifyMemberToken(await memberToken({ sub: "a@b.org", iss: "https://evil.example/members/api", exp: 9e9 }), env, f), null);
  const other = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048,
    publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-512" }, true, ["sign", "verify"]);
  assert.equal(await verifyMemberToken(await memberToken({ sub: "a@b.org", exp: 9e9 }, "k1", other.privateKey), env, f), null);
  assert.equal(await verifyMemberToken("not.a.token", env, f), null);
});

test("follow adds the docket label and the alerts newsletter, keeping other labels", async () => {
  const member = { id: "m1", email: "reader@example.org", labels: [{ name: "Docket 44280", slug: "docket-44280" }],
    newsletters: [{ id: "nl-clips" }] };
  const f = fakeGhost(member);
  const r = await handle(post({ token: await good(), docket: "57171", action: "follow" }), env, f);
  assert.equal(r.status, 200);
  assert.deepEqual(await r.json(), { docket: "57171", following: true });
  const put = f.calls.find((c) => c.method === "PUT");
  assert.deepEqual(put.body.members[0].labels, [{ name: "Docket 44280" }, { name: "Docket 57171" }]);
  assert.deepEqual(put.body.members[0].newsletters, [{ id: "nl-clips" }, { id: "nl-alerts" }]);
});

test("unfollow removes only that label and leaves newsletters alone", async () => {
  const member = { id: "m1", email: "reader@example.org",
    labels: [{ name: "Docket 57171", slug: "docket-57171" }, { name: "Press", slug: "press" }], newsletters: [] };
  const f = fakeGhost(member);
  const r = await handle(post({ token: await good(), docket: "57171", action: "unfollow" }), env, f);
  assert.deepEqual(await r.json(), { docket: "57171", following: false });
  const put = f.calls.find((c) => c.method === "PUT");
  assert.deepEqual(put.body.members[0], { labels: [{ name: "Press" }] });
});

test("status reads without changing anything", async () => {
  const f = fakeGhost({ id: "m1", email: "reader@example.org", labels: [], newsletters: [] });
  const r = await handle(post({ token: await good(), docket: "56002", action: "status" }), env, f);
  assert.deepEqual(await r.json(), { docket: "56002", following: false });
  assert.equal(f.calls.some((c) => c.method === "PUT"), false);
});

test("refuses other sites, bad dockets and missing sign-in", async () => {
  const f = fakeGhost({ id: "m1", email: "reader@example.org", labels: [], newsletters: [] });
  assert.equal((await handle(post({ token: await good(), docket: "57171", action: "follow" }, "https://evil.example"), env, f)).status, 403);
  assert.equal((await handle(post({ token: await good(), docket: "57171; drop", action: "follow" }), env, f)).status, 400);
  assert.equal((await handle(post({ token: "", docket: "57171", action: "follow" }), env, f)).status, 401);
  assert.equal(f.calls.some((c) => c.method === "PUT"), false);
});

test("admin token and label naming", async () => {
  const t = await adminToken(env.GHOST_ADMIN_KEY, 1000);
  assert.equal(JSON.parse(Buffer.from(t.split(".")[0], "base64url")).kid, "abc123");
  assert.deepEqual(labelFor("56765"), { name: "Docket 56765", slug: "docket-56765" });
});
