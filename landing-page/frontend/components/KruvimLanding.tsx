"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { ArrowRight, ArrowUpRight, Menu, X } from "lucide-react";
import { motion, MotionConfig, useReducedMotion } from "motion/react";
import DemoVideo from "./DemoVideo";
import { siteInfo } from "../lib/site-info";
import "./landing.css";

function Reveal({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  const reduced = useReducedMotion();
  return (
    <motion.div className={className} initial={false}
      whileInView={reduced ? undefined : { opacity: [0.7, 1], y: [12, 0] }}
      viewport={{ once: true, amount: 0.1 }} transition={{ duration: 0.45 }}>
      {children}
    </motion.div>
  );
}

function Logo() {
  return <svg viewBox="0 0 24 24" width="27" height="27" aria-hidden="true">
    <rect width="24" height="24" rx="5" fill="currentColor" />
    <path d="M7 16.5 12 7l5 9.5" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinejoin="round" />
    <circle cx="12" cy="7" r="2.1" fill="#fff" />
    <circle cx="7" cy="16.5" r="2.1" fill="#fff" />
    <circle cx="17" cy="16.5" r="2.1" fill="#fff" />
  </svg>;
}

function LandingForm({ kind }: { kind: "signup" | "feedback" }) {
  const isSignup = kind === "signup";
  const [status, setStatus] = useState<"idle" | "submitting" | "success" | "error">("idle");
  const [notice, setNotice] = useState("");
  const started = useRef(0);
  useEffect(() => { started.current = Date.now(); }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status === "submitting") return;
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    if (isSignup && String(values.full_name).trim().length < 2) { setStatus("error"); setNotice("Please enter your full name (at least two characters)."); return; }
    if (!isSignup && String(values.message).trim().length < 10) { setStatus("error"); setNotice("Please write at least 10 characters of feedback."); return; }
    setStatus("submitting"); setNotice("");
    try {
      const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
      const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
      if (!url || !key) throw new Error("The form is temporarily unavailable. Please try again later.");
      const response = await fetch(`${url}/functions/v1/kruvim-forms`, {
        method: "POST", headers: { "Content-Type": "application/json", apikey: key },
        body: JSON.stringify({ ...values, kind, started_at: started.current }), signal: AbortSignal.timeout(15000),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "We could not save this right now. Please try again.");
      form.reset(); setStatus("success"); setNotice(data.message); started.current = Date.now();
    } catch (error) {
      setStatus("error"); setNotice(error instanceof Error && error.name !== "TimeoutError" && error.name !== "TypeError" ? error.message : "We could not connect. Please try again in a moment.");
    }
  }
  return <form className="landing-form" onSubmit={submit} aria-busy={status === "submitting"}>
    <div className="k-form-row"><label htmlFor={`${kind}-name`}>Full name {!isSignup && <small>Optional</small>}<input id={`${kind}-name`} name="full_name" autoComplete="name" required={isSignup} minLength={isSignup ? 2 : undefined} maxLength={120} placeholder="Your full name" /></label><label htmlFor={`${kind}-email`}>Email address {!isSignup && <small>Optional</small>}<input id={`${kind}-email`} name="email" type="email" autoComplete="email" required={isSignup} maxLength={254} placeholder="you@example.com" /></label></div>
    {isSignup ? <><label htmlFor="signup-company">Company or private name <small>Optional</small><input id="signup-company" name="entity_name" autoComplete="organization" maxLength={160} placeholder="Your company, studio or personal brand" /></label><label htmlFor="signup-phone">Phone number<input id="signup-phone" name="phone" type="tel" autoComplete="tel" required minLength={7} maxLength={30} pattern={String.raw`[+0-9 \(\)\.\-]{7,30}`} title="Enter a phone number with at least 7 digits, including your country code." placeholder="+971 50 000 0000" /></label><p className="form-disclosure">We’ll use these details to contact you about Kruvim early access.</p></> : <label htmlFor="feedback-message">Your feedback<textarea id="feedback-message" name="message" required minLength={10} maxLength={4000} rows={4} placeholder="What are you trying to understand about your audience?" /></label>}
    <div className="form-trap" aria-hidden="true"><label>Website<input name="website" tabIndex={-1} autoComplete="off" /></label></div>
    <button className="k-cta" type="submit" disabled={status === "submitting"}>{status === "submitting" ? "Sending…" : isSignup ? "Join the early access list" : "Send feedback"}<ArrowUpRight size={19}/></button>
    <div className={`form-message ${status}`} role={status === "error" ? "alert" : "status"} aria-live="polite">{notice}</div>
  </form>;
}

export default function KruvimLanding() {
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = () => setMenuOpen(false);
  return (
    <MotionConfig reducedMotion="user">
      <main className="k-landing" id="top">
        <a className="k-skip" href="#overview">Skip to content</a>
        <header className="k-nav">
          <a href="#top" className="k-logo" aria-label="Kruvim home"><Logo /><span>Kruvim</span></a>
          <nav id="landing-navigation" className={menuOpen ? "open" : ""} aria-label="Main navigation">
            <a href="#demo" onClick={closeMenu}>Product demo</a>
            <a href="#how-it-works" onClick={closeMenu}>How it works</a>
            <a href="#feedback" onClick={closeMenu}>Feedback</a>
          </nav>
          <a className="nav-cta" href="#signup">Request early access <ArrowUpRight size={15} /></a>
          <button className="menu-toggle" aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-controls="landing-navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>
            {menuOpen ? <X /> : <Menu />}
          </button>
        </header>

        <section className="k-hero page-width" id="overview" aria-labelledby="hero-heading">
          <div className="hero-intro">
            <div className="hero-title">
              <p className="section-label">Synthetic audience research</p>
              <h1 id="hero-heading">Test your content.<br />Before it goes live.</h1>
            </div>
            <div className="hero-summary">
              <p>Explore how an audience could respond to your next video, campaign or idea. Kruvim lets you test content with simulated audiences before you publish.</p>
              <a className="text-link" href="#signup">Request early access <ArrowRight size={17} /></a>
            </div>
          </div>
          <DemoVideo />
        </section>

        <section className="product-explanation page-width" id="how-it-works">
          <Reveal className="explanation-heading">
            <p className="section-label">The workflow</p>
            <h2>A closer look at<br />the response.</h2>
            <p className="explanation-lede">For creators, agencies and teams who want to understand how their content might be received.</p>
          </Reveal>
          <div className="workflow-list">
            {[
              ["Set the context", "Add your content and choose the audience you want to explore. Give the simulation a clear starting point."],
              ["Observe the conversation", "Follow simulated reactions and audience activity. Look at differences between segments and explore individual perspectives."],
              ["Review and refine", "Read the report, ask audience agents questions and use the findings to inform your next edit."],
            ].map(([title, text], index) => <Reveal key={title} className="workflow-row">
              <span className="step-number">0{index + 1}</span>
              <div><h3>{title}</h3><p>{text}</p></div>
            </Reveal>)}
            <p className="simulation-note">Simulated responses help you explore possibilities. They are not a guarantee of real audience behavior.</p>
          </div>
        </section>

        <section className="access-section" id="signup">
          <div className="page-width access-layout">
            <Reveal className="access-copy">
              <p className="section-label">Early access</p>
              <h2>Try Kruvim with<br />your next idea.</h2>
              <p>Leave your details and we’ll be in touch about early access.</p>
              <span className="access-note">For individuals and organizations.</span>
            </Reveal>
            <Reveal><LandingForm kind="signup" /></Reveal>
          </div>
        </section>

        <section className="feedback-section page-width" id="feedback">
          <Reveal>
            <p className="section-label">Feedback</p>
            <h2>What do you need<br />to know about your audience?</h2>
            <p>Tell us what you’re working on and what you’d like Kruvim to help you understand.</p>
          </Reveal>
          <Reveal><LandingForm kind="feedback" /></Reveal>
        </section>

        <footer className="k-footer-new">
          <div className="page-width">
            <div className="footer-main">
              <div className="footer-brand"><a href="#top" className="k-logo"><Logo /><span>Kruvim</span></a><p>Test your content before it goes live.</p></div>
              <section><h3>Contact</h3><a className="footer-link contact-link" href={`mailto:${siteInfo.contactEmail}`}>{siteInfo.contactEmail}</a></section>
              <section><h3>Social</h3><a className="footer-link" href={siteInfo.instagramUrl} target="_blank" rel="noreferrer">Instagram · {siteInfo.instagramHandle} <ArrowUpRight size={12} /></a><span className="pending-label">TikTok · Coming soon</span></section>
            </div>
            <div className="footer-bottom"><span>© 2026 Kruvim</span><a href="#top">Back to top <ArrowUpRight size={13} /></a></div>
          </div>
        </footer>
      </main>
    </MotionConfig>
  );
}
