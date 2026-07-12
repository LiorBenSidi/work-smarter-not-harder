# Pause / resume the CI-CD pipeline (minute control)

GitHub Actions on a private repo draws from a **monthly free-minute pool** that resets on the 1st.
To stay in control of that pool — especially the moment it resets — the whole pipeline has an on/off switch.
Two independent levers, pick by need:

## 1. `RUN_CI` repo variable — the in-repo master switch (recommended)

Every job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) is gated on `vars.RUN_CI != 'false'`.

```sh
R=LiorBenSidi/work-smarter-not-harder
gh variable set RUN_CI -R "$R" --body false   # PAUSE — every job skips, ~0 Actions minutes
gh variable set RUN_CI -R "$R" --body true    # RESUME — normal CI
gh variable delete RUN_CI -R "$R"             # RESUME (unset == on, the default)
```

- **Paused ≠ deadlocked.** A skipped job reports its status check as *passing*, so the required
  `checks` / `cross-container` contexts still go green while paused — PRs can still merge without spending minutes.
- Unset (or anything other than `false`) == **on**, so the default is the normal pipeline.
- Independent of `DEPLOY_ENABLED` (which gates only the deploy job). Pausing CI pauses build + deploy too.

**Toggling the fresh monthly quota:** set `RUN_CI=false` before the reset → when minutes come back the pipeline
stays paused (0 burn) until you flip `RUN_CI=true` for the run you actually want.

## 2. `gh workflow disable` — the hard off (no runs at all)

```sh
gh workflow disable CI -R LiorBenSidi/work-smarter-not-harder   # workflow never triggers
gh workflow enable  CI -R LiorBenSidi/work-smarter-not-harder   # back to normal
```

Use this to guarantee **zero** runs (e.g. freeze everything). Note: while disabled the required checks are
never reported, so PRs into `main` show "Expected — waiting for status" and can't merge until you re-enable.
That's why `RUN_CI` (lever 1) is preferred for day-to-day pausing — it keeps merges unblocked.

## Which to use

| Goal | Lever |
|---|---|
| Conserve minutes but still merge PRs | `RUN_CI=false` |
| Freeze the fresh monthly quota until you choose to run CI | `RUN_CI=false` (set it before the reset) |
| Guarantee absolutely no runs (not merging anyway) | `gh workflow disable CI` |
| Turn deploy off but keep tests running | `DEPLOY_ENABLED=false` (leave `RUN_CI` on) |
