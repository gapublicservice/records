// Netlify entry point for the follow service. All the logic is in ../../worker.js.
// Settings come from the project's environment variables (Functions scope):
// GHOST_SITE_URL, GHOST_ADMIN_URL, GHOST_ADMIN_KEY (secret), ALERTS_NEWSLETTER_ID.
import { handle } from "../../worker.js";

const KEYS = ["GHOST_SITE_URL", "GHOST_ADMIN_URL", "GHOST_ADMIN_KEY", "ALERTS_NEWSLETTER_ID"];

export default async (request) => {
  const env = Object.fromEntries(KEYS.map((k) => [k, Netlify.env.get(k)]));
  if (KEYS.some((k) => !env[k])) {
    return new Response(JSON.stringify({ error: "Following isn't switched on yet." }), {
      status: 503, headers: { "Content-Type": "application/json" } });
  }
  try { return await handle(request, env); }
  catch { return new Response(JSON.stringify({ error: "Something went wrong. Try again later." }), {
    status: 502, headers: { "Content-Type": "application/json" } }); }
};

export const config = { path: "/follow" };
