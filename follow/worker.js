// Follow-a-docket service for gapublicservice.org.
//
// The follow page on the Ghost site sends the reader's Ghost member token and
// a docket number here. This checks that the token was signed by the Ghost
// site, finds that member with the Admin API, and adds or removes the label
// "Docket NNNNN". The nightly alert job emails each docket's new filings to
// the members who carry its label.
//
// Written against standard Web APIs (Request, Response, fetch, WebCrypto), so
// it runs as a Cloudflare Worker or a Netlify Function. It holds the only
// copy of the Ghost Admin key outside GitHub secrets, in the host's settings:
//   GHOST_SITE_URL       https://gapublicservice.org  (whose tokens to trust)
//   GHOST_ADMIN_URL      the site's Ghost(Pro) admin address
//   GHOST_ADMIN_KEY      Admin API key "id:secret"
//   ALERTS_NEWSLETTER_ID the Ghost newsletter that docket alerts go out on
// Nothing here is live until it is deployed and the page is published.

const DOCKET = /^\d{1,6}$/;
const enc = new TextEncoder();

function b64url(bytes) {
  let s = btoa(String.fromCharCode(...new Uint8Array(bytes)));
  return s.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function unb64url(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(s + "===".slice((s.length + 3) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}
const json = (obj, status, headers) =>
  new Response(JSON.stringify(obj), { status, headers: { ...headers, "Content-Type": "application/json" } });

export function cors(env, request) {
  const origin = request.headers.get("Origin") || "";
  const site = new URL(env.GHOST_SITE_URL).origin;
  return origin === site
    ? { "Access-Control-Allow-Origin": site, "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type", "Vary": "Origin" }
    : { "Vary": "Origin" };
}

// --- Checking the reader's member token -----------------------------------
let jwksCache = { at: 0, keys: [] };

async function siteKeys(env, fetchImpl) {
  if (Date.now() - jwksCache.at < 10 * 60 * 1000 && jwksCache.keys.length) return jwksCache.keys;
  const r = await fetchImpl(new URL("/members/.well-known/jwks.json", env.GHOST_SITE_URL), { redirect: "follow" });
  if (!r.ok) throw new Error("could not read the site's signing keys");
  jwksCache = { at: Date.now(), keys: (await r.json()).keys || [] };
  return jwksCache.keys;
}

export async function verifyMemberToken(token, env, fetchImpl = fetch, now = Date.now() / 1000) {
  const parts = String(token || "").split(".");
  if (parts.length !== 3) return null;
  let header, claims;
  try {
    header = JSON.parse(new TextDecoder().decode(unb64url(parts[0])));
    claims = JSON.parse(new TextDecoder().decode(unb64url(parts[1])));
  } catch { return null; }
  if (header.alg !== "RS512") return null;
  const jwk = (await siteKeys(env, fetchImpl)).find((k) => !header.kid || k.kid === header.kid);
  if (!jwk) return null;
  const key = await crypto.subtle.importKey("jwk", { kty: jwk.kty, n: jwk.n, e: jwk.e },
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-512" }, false, ["verify"]);
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, unb64url(parts[2]),
    enc.encode(parts[0] + "." + parts[1]));
  if (!ok) return null;
  const site = new URL(env.GHOST_SITE_URL);
  const issuers = [site.origin + "/members/api", site.origin + "/members/api/"];
  if (claims.iss && !issuers.includes(claims.iss)) return null;
  if (typeof claims.exp !== "number" || claims.exp < now) return null;
  if (typeof claims.sub !== "string" || !claims.sub.includes("@")) return null;
  return claims.sub.toLowerCase();
}

// --- Ghost Admin API ------------------------------------------------------
export async function adminToken(key, now = Math.floor(Date.now() / 1000)) {
  const [kid, secret] = key.split(":");
  const head = b64url(enc.encode(JSON.stringify({ alg: "HS256", typ: "JWT", kid })));
  const body = b64url(enc.encode(JSON.stringify({ iat: now, exp: now + 300, aud: "/admin/" })));
  const raw = Uint8Array.from(secret.match(/../g), (h) => parseInt(h, 16));
  const k = await crypto.subtle.importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", k, enc.encode(head + "." + body));
  return head + "." + body + "." + b64url(sig);
}

async function admin(env, fetchImpl, method, path, body) {
  const r = await fetchImpl(new URL("/ghost/api/admin" + path, env.GHOST_ADMIN_URL), {
    method,
    headers: { Authorization: "Ghost " + (await adminToken(env.GHOST_ADMIN_KEY)),
               "Content-Type": "application/json", "Accept-Version": "v6.0" },
    body: body ? JSON.stringify(body) : undefined,
    redirect: "manual",
  });
  if (!r.ok) throw new Error(`Ghost answered ${r.status} to ${method} ${path.split("?")[0]}`);
  return r.json();
}

export function labelFor(docket) {
  return { name: `Docket ${docket}`, slug: `docket-${docket}` };
}

// --- The request handler ---------------------------------------------------
export async function handle(request, env, fetchImpl = fetch) {
  const headers = cors(env, request);
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers });
  if (request.method !== "POST") return json({ error: "Use POST." }, 405, headers);
  if (!headers["Access-Control-Allow-Origin"]) return json({ error: "Not allowed from this site." }, 403, headers);

  let input;
  try { input = await request.json(); } catch { return json({ error: "Bad request." }, 400, headers); }
  const docket = String(input.docket || "");
  const action = input.action;
  if (!DOCKET.test(docket) || !["status", "follow", "unfollow"].includes(action))
    return json({ error: "Bad request." }, 400, headers);

  const email = await verifyMemberToken(input.token, env, fetchImpl);
  if (!email) return json({ error: "Please sign in again." }, 401, headers);

  const filter = encodeURIComponent(`email:'${email.replace(/'/g, "\\'")}'`);
  const found = await admin(env, fetchImpl, "GET", `/members/?filter=${filter}&include=labels,newsletters&limit=1`);
  const member = found.members && found.members[0];
  if (!member || member.email.toLowerCase() !== email) return json({ error: "Please sign in again." }, 401, headers);

  const label = labelFor(docket);
  const has = (member.labels || []).some((l) => l.slug === label.slug);
  if (action === "status") return json({ docket, following: has }, 200, headers);

  const wantFollow = action === "follow";
  if (wantFollow === has) return json({ docket, following: has }, 200, headers);

  const labels = (member.labels || []).filter((l) => l.slug !== label.slug).map((l) => ({ name: l.name }));
  if (wantFollow) labels.push({ name: label.name });
  const update = { labels };
  if (wantFollow && env.ALERTS_NEWSLETTER_ID) {
    const ids = new Set((member.newsletters || []).map((n) => n.id));
    ids.add(env.ALERTS_NEWSLETTER_ID);
    update.newsletters = [...ids].map((id) => ({ id }));
  }
  await admin(env, fetchImpl, "PUT", `/members/${member.id}/`, { members: [update] });
  return json({ docket, following: wantFollow }, 200, headers);
}

// Cloudflare Worker entry point. A Netlify Function can export
// `default async (req, context) => handle(req, Netlify.env.toObject())`.
export default {
  async fetch(request, env) {
    try { return await handle(request, env); }
    catch (err) { return json({ error: "Something went wrong. Try again later." }, 502, cors(env, request)); }
  },
};
