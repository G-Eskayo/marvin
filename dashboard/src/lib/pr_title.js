// Replace bare "Implement G-Eskayo/marvin#123" PR titles with the actual ticket title.
// Bare titles come from the ticket pipeline's auto-generated PR titles (step 1 of the fix).
// Real ticket titles are available via parity.ticket when the ticket is known.

export function displayTitle(prTitle, ticketTitle) {
  if (!ticketTitle) return prTitle
  // Pipeline PRs have titles like "Implement G-Eskayo/marvin#123" or fallback forms
  const bareMatch = prTitle.match(/^Implement [\w-]+\/[\w-]+#\d+/)
  if (bareMatch) return ticketTitle
  return prTitle
}
