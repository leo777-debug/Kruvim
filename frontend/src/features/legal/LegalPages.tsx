import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Logo } from "@/components/layout/Logo";
import { Callout } from "@/components/ui/primitives";

/** Fill these in before launch. Until `company` is set, both pages show that they are drafts awaiting legal review. */
export const LEGAL = {
  company: "",                // e.g. "Kruvim Technologies FZ-LLC"
  address: "",
  email: "",                  // privacy and legal contact
  jurisdiction: "",           // e.g. "the Abu Dhabi Global Market"
  updated: "28 October 2026",
};
const v = (x: string, placeholder: string) => x || `[${placeholder}]`;

function LegalShell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="min-h-full bg-bg">
      <header className="flex h-14 items-center gap-2 px-6"><Link to="/" className="flex items-center gap-2"><Logo className="h-[22px] w-[22px]" /><span className="text-[15px] font-semibold">Kruvim</span></Link></header>
      <main className="mx-auto max-w-3xl px-4 pb-16 pt-6">
        <h1 className="text-xl font-semibold">{title}</h1>
        <p className="mt-1 text-xs text-muted">Last updated {LEGAL.updated}</p>
        {!LEGAL.company && <Callout tone="warn" className="mt-4" title="Draft">This document is a draft for the beta and has not yet been finalised or reviewed by counsel.</Callout>}
        <div className="legal mt-6 space-y-5 text-sm leading-relaxed [&_h2]:mb-1.5 [&_h2]:font-semibold [&_li]:ml-5 [&_li]:list-disc [&_ul]:space-y-1">{children}</div>
        <p className="mt-10 text-xs text-muted"><Link className="text-brand" to="/privacy">Privacy policy</Link> · <Link className="text-brand" to="/terms">Terms of use</Link> · <Link className="text-brand" to="/help#limits">What predictions can and can't tell you</Link></p>
      </main>
    </div>
  );
}

export function PrivacyPage() {
  const company = v(LEGAL.company, "Company legal name"), email = v(LEGAL.email, "privacy contact email");
  return (
    <LegalShell title="Privacy policy">
      <section><h2>Who we are</h2><p>Kruvim is operated by {company}, {v(LEGAL.address, "registered address")} ("we"). We are responsible for the personal data described here. Contact us at {email}.</p></section>
      <section><h2>What we collect</h2><ul>
        <li><strong>Account:</strong> your name, email address and a one-way hash of your password (we never store the password itself).</li>
        <li><strong>Your workspace:</strong> the content you test (scripts, posts, files, links), data you upload (including barometer files), simulations, reports, forecasts and settings.</li>
        <li><strong>Model keys:</strong> API keys you add for model providers, encrypted at rest and never shown back in full.</li>
        <li><strong>Usage:</strong> how many model calls and credits your workspace uses, for limits and billing.</li>
        <li><strong>Security and reliability logs:</strong> IP address, request times and error reports, kept for up to 30 days to protect the service and fix problems. Error reports never include the content you test or your keys.</li>
        <li><strong>Cookies:</strong> one essential cookie that keeps you signed in. Your theme and layout preferences stay in your browser. We use no advertising or tracking cookies.</li>
      </ul></section>
      <section><h2>How we use it</h2><p>To provide and secure Kruvim: run your simulations, show your results, enforce spending and rate limits, prevent abuse, respond to support requests and improve reliability. We do not sell personal data and do not use your content to train AI models.</p></section>
      <section><h2>Model providers</h2><p>Simulations are produced by AI models. When you run a test, its content is sent to the model provider your workspace uses (for example OpenAI, Anthropic, Google, OpenRouter or another provider you choose, or your own local server). That provider processes it under its own terms and privacy policy. In dry-run mode nothing is sent to a model provider.</p></section>
      <section><h2>Simulated people</h2><p>The people in a simulation are synthetic. They are generated from statistics and public data, not from any real individual's records. Please do not upload personal data about other people unless you have a lawful basis to do so.</p></section>
      <section><h2>Who we share it with</h2><ul>
        <li>Service providers that host and run Kruvim (cloud hosting, database and storage, email, error monitoring), under contracts that protect your data.</li>
        <li>The model provider your workspace chooses, as described above.</li>
        <li>People you choose to share with: workspace members, and anyone who has a results link you create.</li>
        <li>Authorities, where the law requires it.</li>
      </ul></section>
      <section><h2>Public forecasts</h2><p>Forecasts are private unless your workspace marks one public before locking it. The public hash ledger contains only cryptographic hashes and times, never your content or workspace name.</p></section>
      <section><h2>How long we keep it</h2><p>Your account and workspace data are kept while your account is active. When you ask us to delete your account we delete it within 30 days, and it leaves our backups as they expire. Security logs and error reports are kept for up to 30 days.</p></section>
      <section><h2>Security</h2><p>Passwords are hashed with Argon2id, model keys and other secrets are encrypted, connections use HTTPS, and every workspace is isolated from the others. No system is perfectly secure; tell us at {email} if you find a problem.</p></section>
      <section><h2>Your rights</h2><p>Depending on where you live (for example under the UAE Personal Data Protection Law or the GDPR), you can ask to access, correct, export or delete your personal data, or object to some processing. Write to {email}; we answer within 30 days. You may also complain to your data protection authority.</p></section>
      <section><h2>International transfers</h2><p>Kruvim and the model providers you choose may process data outside your country. Where required, we use safeguards such as contractual clauses.</p></section>
      <section><h2>Age</h2><p>Kruvim is for people aged 18 and over.</p></section>
      <section><h2>Changes</h2><p>We will tell you about material changes before they take effect.</p></section>
    </LegalShell>
  );
}

export function TermsPage() {
  const company = v(LEGAL.company, "Company legal name"), email = v(LEGAL.email, "contact email");
  return (
    <LegalShell title="Terms of use">
      <section><h2>The beta</h2><p>Kruvim is provided by {company} as an invite-only beta. Features may change, break or be removed, and the service may be interrupted. Please keep anything you learn about unreleased features confidential and send us your feedback; we may use feedback without obligation.</p></section>
      <section><h2>Your account</h2><p>Keep your password and API keys safe; you are responsible for activity in your account. Workspace owners and admins control their workspace's members, keys and limits.</p></section>
      <section><h2>Acceptable use</h2><p>You must not use Kruvim to:</p><ul>
        <li>break the law or infringe anyone's rights, including data protection and data licences;</li>
        <li>plan or run election manipulation, disinformation campaigns, harassment, or targeting of identifiable individuals;</li>
        <li>upload personal data about other people without a lawful basis;</li>
        <li>attack, probe or overload the service, or try to reach other workspaces' data;</li>
        <li>resell or provide access to the service without our written agreement.</li>
      </ul><p>We may suspend accounts that do.</p></section>
      <section><h2>Your content and data</h2><p>You keep all rights to what you upload and create. You give us permission to store and process it only to provide Kruvim to you. You confirm you have the rights and licences needed for data you upload, including public statistics and reports whose licence may restrict commercial use.</p></section>
      <section><h2>Model providers and your keys</h2><p>If you add your own API keys, the model provider's terms and charges apply to you. Spending limits and safety caps reduce the risk of unexpected costs but are not a guarantee; check usage with your provider too.</p></section>
      <section><h2>Simulated results are not advice</h2><p>Results, reports, scores and forecasts are simulations generated by AI models from synthetic people and data. They are not polls, measurements or facts, they can be wrong, and they are <strong>not financial, legal, political, medical or other professional advice</strong>. You are responsible for decisions you make. Track-record statistics describe past forecasts and do not promise future accuracy.</p></section>
      <section><h2>Fees</h2><p>The beta is free unless we agree otherwise in writing. Credits and plans may change; we will tell you before paid features begin.</p></section>
      <section><h2>Ending</h2><p>You can stop using Kruvim and ask us to delete your account at any time. We may end the beta or your access with reasonable notice, or immediately for serious breaches of these terms.</p></section>
      <section><h2>Liability</h2><p>The beta is provided "as is". To the extent the law allows, we are not liable for indirect or consequential losses, or for decisions made using simulated results, and our total liability is limited to the amount you paid us in the 12 months before the claim (zero during a free beta). Nothing here limits liability that cannot be limited by law.</p></section>
      <section><h2>Law</h2><p>These terms are governed by the laws of {v(LEGAL.jurisdiction, "jurisdiction")}, whose courts have jurisdiction. Contact: {email}.</p></section>
    </LegalShell>
  );
}
