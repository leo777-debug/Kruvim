import { Link } from "react-router-dom";
import { Page } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/primitives";

export default function HelpPage() {
  return <Page title="How Kruvim works" subtitle="Check your content before you post."><Card className="max-w-3xl space-y-6 p-5 text-sm leading-relaxed">
    <section><h2 className="mb-2 font-semibold">1. Add what you want to share</h2><p>Paste your text or script, or upload a video, audio recording, image or document. Choose the platform and who it is for, then press Test it. More options lets you compare versions and fine-tune the test.</p></section>
    <section><h2 className="mb-2 font-semibold">2. Let your audience react</h2><p>Kruvim models people from your chosen audience using local context and, when available, your own aggregate analytics. A quick read appears after the first sample answers. The score is refined as the rest of the test finishes.</p></section>
    <section><h2 className="mb-2 font-semibold">3. Read the verdict and try a fix</h2><p>See who likes it, where attention drops and what to improve first. You can ask the simulated people why they reacted that way, or open Details for the full report, evidence and method.</p></section>
    <section><h2 className="mb-2 font-semibold">Bring your real results</h2><p><Link className="text-brand" to="/my-audience">My audience</Link> lets you import aggregate analytics or enter them yourself. Link published posts to earlier tests to measure how close the predictions were. Simulated reactions and memories are always labelled; they are predictions, not real follower feedback.</p></section>
    <section><h2 className="mb-2 font-semibold">Try it without an API key</h2><p>Dry run works without a model and shows how the product works with deterministic simulated answers. Add your own model in Settings for richer answers. Local models work too; keys are blank until you choose to add one.</p></section>
    <section><h2 className="mb-2 font-semibold">If a test fails</h2><p>The test shows a reason and a Retry button. Advanced in the sidebar keeps the population, calibration, monitoring, saved audiences and workspace usage available.</p></section>
  </Card></Page>;
}
