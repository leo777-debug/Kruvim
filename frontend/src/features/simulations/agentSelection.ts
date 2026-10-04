/** Keep a valid current-list selection; an absent or filtered-out agent falls back to the first. */
export function selectedAgent(refs: readonly string[], requested: string | null): string | null {
  return requested && refs.includes(requested) ? requested : refs[0] ?? null;
}
