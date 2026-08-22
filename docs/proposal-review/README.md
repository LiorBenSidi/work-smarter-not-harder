# Proposal review sources

The documents the graded build is measured against, kept here so [#596](https://github.com/LiorBenSidi/work-smarter-not-harder/issues/596) can link to them instead of naming files that live only in a chat thread.

The build block — **75 points** under the TA's guidelines ([`04-ta-guidelines.pdf`](04-ta-guidelines.pdf), 8 Jul), which supersede the 80/10/10 split in Noam's earlier feedback — is graded as *"a working, localhost web application that implements your proposed idea. It should include everything mentioned in your proposal. **EVERYTHING** (except the stretch goals). If you want to remove some features, let us know beforehand."* — so the proposal is not background reading, it is the specification.

| File | What it is |
|---|---|
| [`01-original-proposal.md`](01-original-proposal.md) | the proposal submitted in Week 7, graded 100/100 |
| [`02-revised-proposal.md`](02-revised-proposal.md) | the revision sent to Noam on 28 Jun. Its first block lists every change vs. the original |
| [`03-noam-feedback-and-guidelines.md`](03-noam-feedback-and-guidelines.md) | Noam's first-round feedback (25 Jun) — the −5 penalties, the 8 forum sub-features, the CI/CD wording. Its **80/10/10 split is superseded** by the TA's 75 + 5 + 10 + 10 in `04-ta-guidelines.pdf`. |
| [`04-ta-guidelines.pdf`](04-ta-guidelines.pdf) | the guidelines PDF the TA sent on 8 Jul |
| [`email-1-revised-proposal-sent-28jun.png`](email-1-revised-proposal-sent-28jun.png) | the mail that sent the revision, showing which three files went with it |
| [`email-2-ta-guidelines-reply-08jul.png`](email-2-ta-guidelines-reply-08jul.png) | the TA's reply attaching the guidelines PDF |

## What the revision changed

`02-revised-proposal.md` opens with its own change-log. The load-bearing ones:

- **§5** — the Random Forest classifier and the recommendation engine became one **AI Decision Engine** with two stages (assess → recommend)
- **§5** — the fixed five output classes were dropped for a smaller flexible set
- **§6** — dataset reworked: recovery/wellness data **and** program/exercise data, plus distribution-preserving augmentation
- **§7** — features 6 + 7 **merged**: Program Balance Analysis feeds the Action Plan
- **§13** — MVP replaced by a phased build, answering Noam's *"plan in phases"*
- **§14** — collaborative filtering moved to Future Work; smartwatch narrowed to Fitbit
- **removed** — the Testing Plan and feature×test matrix left the proposal; they live in the repo and the final report

## The one approved deviation

**Only the hand-written exercise catalog** was ever agreed as a departure, settled with the TA directly. Everything else named in the proposal has to exist in the build — which is what #528 caught once already, and what #596 tracks.

The two screenshots carry the sender and recipient addresses of that correspondence. They are kept deliberately: they are the record of what was asked and what was answered.
