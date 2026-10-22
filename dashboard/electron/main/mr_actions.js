import { submitDecisions } from './decisions_submit.js'
import { decisionsDisagreement } from './local_first.js'
import { repoFromPrUrl } from './mr_repos.js'

// What MR Review does after each of its writes, local-first (CONTEXT.md "Dashboard actions render their true result
// locally at once, and confirm in the background"; pipeline review P4/P5, 2026-10-21). index.js wires these to its IPC
// handlers; they are here so a test can drive the same code with a fake GitHub and count every call.
//
// Before: each action called githubChanged(null), which marked all 13 repos changed, and the screen then re-listed them
// all (three overlapping mr:list calls, up to 43 s) before it showed the answer it had just written. Now an action:
//   - applies GitHub's own answer to its write to the remembered state (localFirst), so the next screen read has it;
//   - asks GitHub about that one PR or ticket, once, conditionally, in the background (localFirst.confirm*);
//   - never marks every repo changed. Only a correction or a stale Approve check re-reads one repo.
//
// notify(channel, payload) reaches the renderer: 'decisions:recorded' when the record comment lands, 'mr:corrected'
// when GitHub disagreed and the view took GitHub's version (localFirst calls it).

const NEEDS_REWORK = 'needs-reengagement'
const quiet = (p) => { Promise.resolve(p).catch(() => {}) }
const ticketOf = (n) => (Number.isInteger(Number(n)) && Number(n) > 0 ? Number(n) : null)
const prNumberOf = (url) => Number((String(url).match(/\/pull\/(\d+)$/) || [])[1]) || null

export function createMrActions({ state, exec, localFirst, listOpenPrs, card, headCheck, notify = () => {} }) {
  const say = (channel, payload) => { try { notify(channel, payload) } catch { /* the screen being gone never fails an action */ } }

  return {
    // Decisions answered from the dashboard: one GET, the PATCH, then the answer is on screen (from GitHub's reply to
    // the PATCH). The record comment and any label move continue in the background and report through notify.
    async submitDecisions({ repo, number, answers }) {
      return localFirst.serialize(`${repo}#${Number(number)}`, async () => {
        const { recorded, sent, ...result } = await submitDecisions({ repo, number, answers }, { exec, background: true })
        quiet(recorded?.then((rec) => say('decisions:recorded', { repo, number: Number(number), ...rec })))
        if (result.unchanged) return result
        const ver = localFirst.setPrBody(repo, number, result.body)
        if (result.disagreed) {
          const message = decisionsDisagreement(sent, result.body)
          if (message) say('mr:corrected', { repo, number: Number(number), url: `https://github.com/${repo}/pull/${Number(number)}`, message })
        }
        quiet(localFirst.confirmBody(repo, number, { ver, etag: result.etag, body: result.body }))
        let pr = null
        try { pr = await card(`https://github.com/${repo}/pull/${Number(number)}`) } catch { pr = null }
        return { ...result, pr }
      })
    },

    // The open PRs Approve's order check runs against: the remembered list, after one conditional check that this
    // repo's open PRs (numbers, head commits, bases) are still what GitHub has. Stale re-reads that one repo.
    async approvePrs(url) {
      const repo = repoFromPrUrl(url)
      let prs = await listOpenPrs()
      const { fresh } = repo ? await headCheck(repo, prs.filter((p) => p.repo === repo)) : { fresh: false }
      if (!fresh && repo) {
        state.changed(repo)
        prs = await listOpenPrs()
      }
      return prs
    },

    merged(url) {
      const repo = repoFromPrUrl(url)
      const n = prNumberOf(url)
      if (!repo || !n) return
      const ver = localFirst.removePr(repo, n)
      quiet(localFirst.confirmClosed(repo, n, { ver, url, verb: 'merged' }))
    },

    // The merge gate sent it back instead (tests failed, CI red): several things changed on GitHub at once, so that one
    // repo is re-read on the next look.
    reengaged(url) {
      const repo = repoFromPrUrl(url)
      if (repo) state.changed(repo)
    },

    denied({ url, ticketNumber, action }) {
      const repo = repoFromPrUrl(url)
      if (!repo) return
      if (action === 'drop') {
        const n = prNumberOf(url)
        if (!n) return
        const ver = localFirst.removePr(repo, n)
        quiet(localFirst.confirmClosed(repo, n, { ver, url, verb: 'dropped' }))
        return
      }
      const t = ticketOf(ticketNumber)
      if (!t) return
      const ver = localFirst.setTicketLabel(repo, t, NEEDS_REWORK, true)
      quiet(localFirst.confirmLabel(repo, t, { ver, label: NEEDS_REWORK, present: true, url }))
    },

    cleared({ url, ticket }) {
      const repo = repoFromPrUrl(url)
      const t = ticketOf(ticket)
      if (!repo || !t) return
      const ver = localFirst.setTicketLabel(repo, t, NEEDS_REWORK, false)
      quiet(localFirst.confirmLabel(repo, t, { ver, label: NEEDS_REWORK, present: false, url }))
    }
  }
}
