/** Wordmark glyph: a solid square with three linked nodes. Uses the accent only, so it works in both themes. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <rect width="24" height="24" rx="5" fill="rgb(var(--brand))" />
      <path d="M7 16.5 12 7l5 9.5" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinejoin="round" />
      <circle cx="12" cy="7" r="2.1" fill="#fff" />
      <circle cx="7" cy="16.5" r="2.1" fill="#fff" />
      <circle cx="17" cy="16.5" r="2.1" fill="#fff" />
    </svg>
  );
}
