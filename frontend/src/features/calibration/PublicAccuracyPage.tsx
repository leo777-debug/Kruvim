import { Link } from "react-router-dom";
import AccuracyReport from "./AccuracyReport";
export default function PublicAccuracyPage() {
  return <main className="mx-auto max-w-3xl px-5 py-12"><h1 className="mb-3 text-2xl font-semibold">Kruvim accuracy</h1>
    <p className="mb-6 text-muted">Transparent measurements from creators who chose to contribute. Results include uncertainty and exclude ineligible comparisons.</p>
    <AccuracyReport publicReport /><Link className="text-sm text-brand" to="/login">Sign in to Kruvim</Link></main>;
}
