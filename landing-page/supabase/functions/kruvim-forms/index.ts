import { createClient } from "npm:@supabase/supabase-js@2.99.1";

const headers = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "apikey, content-type, authorization, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Content-Type": "application/json",
  "Cache-Control": "no-store",
};
const respond = (status: number, message: string) =>
  new Response(JSON.stringify({ message }), { status, headers });
const publishable = "sb_publishable_SHKmvE12etHp-OkQsZjU0w_qC0-KMoY";
const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null, { headers });
  if (req.method !== "POST") return respond(405, "Use POST.");
  // Publishable-key authentication for a public form; privileged keys stay in Edge secrets.
  if (req.headers.get("apikey") !== publishable) return respond(401, "Invalid API key.");
  try {
    const raw = await req.text();
    if (raw.length > 12000) return respond(413, "Your message is too long.");
    const body = JSON.parse(raw);
    if (!body || typeof body !== "object") return respond(400, "Please check your form.");
    if (body.website) return respond(400, "Please check your form.");
    const elapsed = Date.now() - Number(body.started_at);
    if (!Number.isFinite(elapsed) || elapsed < 2000 || elapsed > 86400000)
      return respond(400, "Please reload the page and try again.");
    const clean = (key: string) => typeof body[key] === "string" ? body[key].trim() : "";
    const name = clean("full_name");
    const email = clean("email").toLowerCase();
    const company = clean("entity_name");
    const phone = clean("phone");
    const message = clean("message");
    if (name.length > 120 || email.length > 254 || (email && !emailPattern.test(email)))
      return respond(400, "Please enter a valid name and email address.");
    let table: string;
    let record: Record<string, string | null>;
    if (body.kind === "signup") {
      if (name.length < 2 || !email || company.length > 160 ||
          !/^[+\d\s().-]{7,30}$/.test(phone) || phone.replace(/\D/g, "").length < 7)
        return respond(400, "Please check your name, email and phone number.");
      table = "landing_signups";
      record = { full_name: name, email, entity_name: company || null, phone };
    } else if (body.kind === "feedback") {
      if (message.length < 10 || message.length > 4000)
        return respond(400, "Please write between 10 and 4,000 characters.");
      table = "feedback_messages";
      record = { full_name: name || null, email: email || null, message };
    } else return respond(400, "Unknown form.");
    const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
      { auth: { persistSession: false, autoRefreshToken: false } });
    const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
    const salt = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const hash = async (value: string) => Array.from(new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(salt + value))
    )).map(b => b.toString(16).padStart(2, "0")).join("");
    // Atomic, persistent limits. No raw IP addresses are stored.
    for (const value of [ip, ...(email ? ["email:" + email] : [])]) {
      const { data, error } = await admin.rpc("kruvim_check_form_limit", { p_bucket: await hash(value) });
      if (error) return respond(503, "We could not save this right now. Please try again later.");
      if (!data) return respond(429, "Too many requests. Please try again in 10 minutes.");
    }
    const { error } = await admin.from(table).insert(record);
    // Duplicate signups return the same response to avoid exposing who has signed up.
    if (error && !(body.kind === "signup" && error.code === "23505"))
      return respond(503, "We could not save this right now. Please try again later.");
    return respond(200, body.kind === "signup" ? "You're on the list. Thank you for your interest in Kruvim." : "Thank you. Your feedback has been received.");
  } catch {
    return respond(400, "Please check your form and try again.");
  }
});
