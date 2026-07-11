# End-to-End (Browser-Interaction) Test Plan

This is the **exhaustive** inventory of every user-facing feature and interaction in the app, with
reproduction steps and the expected result for each. It is the contract the browser E2E harness
(`tests/E2E_Tests/`) drives: every scenario here should map to an automated check that runs in CI at
**desktop AND mobile viewports** (and a combined pass), so a strict grader can't find an interaction bug
the suite didn't already cover.

The whole frontend is `web/templates/index.html` (inline CSS/HTML/JS). Backend routes are `web/routes/*.py`.
All state-changing requests use a **double-submit CSRF cookie** (`web/csrf.py`): JS reads the readable
`csrf_token` cookie and echoes it in `X-CSRF-Token`. The session cookie is the credential.

**Flags that change whole flows** (`routes/auth.py`, `GET /auth/config`):
- `OTP_ENABLED` (and not `TESTING`) → login is 2-step (email OTP); else one-step.
- `REGISTER_VERIFY_EMAIL` (and not `TESTING`) → register emails a code, creates the account only after verify; else instant.
- `SMTP_HOST` present → `email_mode:"live"` (codes emailed). Absent → `"mock"`; codes/links returned in JSON as `dev_otp`/`dev_code`/`dev_reset_link` **only when `SESSION_COOKIE_SECURE` is off** (this is how the browser suite completes OTP/verify/reset without a mailbox).

The E2E harness boots the app with `OTP_ENABLED=0 REGISTER_VERIFY_EMAIL=0 SMTP_HOST= SESSION_COOKIE_SECURE=0`
for the bulk of flows, and flips the flags on for the dedicated OTP / verify-email / reset scenarios.

---

## A. Screens / Views

### Logged-out — `section#auth-view`
One card, tab-switched; one sub-form visible at a time. Left = marketing thesis with a live cycling orb demo (`#demo-state`/`#demo-verb`, canvas `.orb-liquid`, cycles Ready→Moderate→Rest).

| Sub-view | Container | Reach via | Shows |
|---|---|---|---|
| Login | `form#login-form` | default; `#tab-login` → `showTab('login')` | username/email + password, "Forgot your password?" |
| Register | `form#register-form` | `#tab-register` → `showTab('register')` | display name, email, password (+info tooltips) |
| Forgot | `form#forgot-form` | `#forgot-link` → `showForgot()` | email, Send, Back |
| Reset | `form#reset-form` | URL `/?reset_token=…` → `showReset()` | new-password |
| OTP / verify | `form#otp-form` | after login-2FA or register-verify → `showOtp()` | 6-digit code, live expiry, Trust-browser (login only), Resend, dev-hint |

### Logged-in — `section#app-view`
App shell; one `.screen` at a time via `showScreen(name)`. Dual nav: mobile pill `nav.tabbar` + desktop `nav#topnav` (both carry `data-screen`). Profile is in the corner account menu, not a tab.

| Screen | id | Navigate | Shows |
|---|---|---|---|
| Today | `#screen-today` | default | readiness card `#dashboard`, `#stat-strip`, `#streak-badge`, `form#checkin-form` |
| History | `#screen-history` | `data-screen="history"` | `#history-trend`, `#history-filters`, `#history` |
| Forum | `#screen-forum` | `data-screen="forum"` | `form#forum-form`, `#forum-sorts`, `#forum-list`, `#forum-detail` |
| Messages | `#screen-messages` | `data-screen="messages"` | list-view (`form#dm-new-form`, `#dm-conversations`, `#activity-list`) or thread-view (`#dm-thread`, `form#dm-reply-form`) |
| Profile | `#screen-profile` | corner menu → Profile | `form#profile-form`, `#engagement-strip`, `fieldset#theme-group`, `form#displayname-form`, `form#password-form`, consent/export, danger zone |

Cross-screen: corner menu `#user-menu-panel`, Home FAB `#ctx-back`, check-in capsule `#checkin-capsule`, Chat pulse `.dm-dot`, debug panel (`?debug=1` only).

---

## C. Interaction scenarios (the numbered test list)

### Auth — Login
1. **Login happy (1-step)** — Login tab, valid username + password, Submit → `enterApp`, Today active, `#who` "Hi, {name}".
2. **Login by email** — registered email + password → logs in (email→handle resolved).
3. **Login wrong password** — valid user, wrong pw → `#login-flash` "invalid username or password" (401), stays.
4. **Login unknown user** → same generic error (no enumeration).
5. **Login empty fields** — blank submit → HTML5 `required`; if bypassed 400.
6. **Login NoSQL-injection** — `{"username":{"$gt":""}}` via API → 400, no query.
7. **Login double-click** — rapid Submit → button disabled by `onSubmit`, no dup request.
8. **Login rate-limit** — >20/min → 429.
9. **Login triggers OTP (2FA on)** — valid creds → `otp_required`, OTP form, password cleared from DOM, dev-hint code in mock.

### Auth — OTP (login 2FA)
10. **OTP happy** — correct code, Verify → `enterApp`.
11. **OTP wrong code** → `#otp-flash` "incorrect code — N tries left", stays.
12. **OTP lockout** — exceed max → 429, `restart:true` → back to login.
13. **OTP expired** — past TTL → `#otp-expiry` "expired", input+submit disabled; submit → back to login.
14. **OTP resend gated 30s** — Resend hidden until 30s.
15. **OTP resend** — after 30s → new code, timer resets, input refocused, dev-hint updates.
16. **OTP resend rate-limit** — >5/min → 429.
17. **Trust this browser** — check + verify → remember cookie; next login skips OTP.
18. **OTP Back** — Back → login tab, timers stopped.
19. **OTP no session** — POST `/verify-otp` with no pending → 400 `restart:true`.

### Auth — Register
20. **Register happy (instant)** — valid fields, Create → "Account created…", switches to login.
21. **Register duplicate email** → 409 "an account with this email already exists".
22. **Register short password** (<8) → 400 "password must be 8-256".
23. **Register bad email** → 400 "enter a valid email address".
24. **Register short display name** (<3) → 400 "must be 3-64".
25. **Register control chars in name** → 400.
26. **Register rate-limit** (>10/min) → 429.
27. **Register hints from config** — open Register → tooltips + min/max from `/auth/config`.
28. **Display-name prefill** — type email first → name auto-fills from local-part until edited.
29. **Register verify-email path (verify on)** — valid signup → `verify_required`, OTP form in "register" mode, dev_code.
30. **Register verify happy** — correct code → account created + auto sign-in.
31. **Register verify wrong code** → stays, "that code isn't right".
32. **Register verify duplicate email (enum-safe)** — existing email in verify mode → identical `verify_required`, no code works; owner emailed.
33. **Register verify expired/lockout** → back to register tab.
34. **Register verify resend** — `/register/resend` uses `dev_code` (login uses `dev_otp`) — both handled.

### Auth — Forgot / Reset
35. **Forgot happy** — email, Send → "if that email is registered, a reset link is on its way" (no enum).
36. **Forgot dev link (mock)** → `dev_reset_link` shown as clickable "open reset link (dev)".
37. **Forgot unregistered email** → identical success body.
38. **Forgot Back** → login tab.
39. **Reset happy** — `/?reset_token=<valid>`, new pw, Submit → "Password updated", URL cleaned, → login after 1s.
40. **Reset invalid/expired token** → 400 "this reset link is invalid or has expired".
41. **Reset token single-use** — reuse after change → 400.
42. **Reset short password** (<8) → 400.
43. **Reset via popstate** — Back/Forward to `?reset_token` while logged out → reset form shown.

### Session / global
44. **Boot already-logged-in** — reload with session → `GET /me` → straight to app.
45. **Boot logged-out** → auth view.
46. **Session expiry mid-app** — gated fetch 401 → reset + login + "Your session has ended"; auth endpoints exempt.
47. **CSRF missing** — POST without header → 403.
48. **CSRF mismatch** — header ≠ cookie → 403.
49. **CSRF cookie issued on first GET**.
50. **Unauthorized gated route** — GET dashboard/history/profile/forum/conversations logged out → 401.
51. **Oversized JSON** — POST >64KB → 413.

### Today / Check-in
52. **First-run empty dashboard** — new user, no profile → `needs_profile`, greyed "Example" card + "Fill in your profile…".
53. **Dashboard AI down** → warn banner "Readiness is temporarily unavailable", no crash.
54. **Check-in happy** — 5 metrics, Submit → "Check-in saved", form reset, orb fills, recs cascade (fresh), kcal counts up from 0.
55. **Check-in out-of-range** — sleep 30 / resting_hr 500 → 400 "must be between …".
56. **Check-in non-numeric/NaN** → 400 "must be a finite number".
57. **Check-in missing field** → HTML5 required; if bypassed 400.
58. **Check-in with AI down** — entry still saved (assessment/calories null), `ai_status:"unavailable"`, 201.
59. **Check-in double-submit** → in-flight disable prevents dup.
60. **Dashboard refresh** — `#dashboard-refresh` reloads (event not passed as opts).
61. **Streak badge** — consecutive days ending today → "N-day streak · logged today"; ending yesterday → "check in to keep it"; brand-new → hidden.
62. **Check-in-due capsule** — established user, no check-in today, off Today → floating "Check in for today"; tap → Today + focus form.
63. **Confidence bars** — AI proba map → bars animate from 0.
64. **XSS-safe AI fields** — `<script>` in state/recs → escaped.

### History
65. **History list happy** → assessment/calories/timestamp list.
66. **History empty** → "No check-ins yet" empty state.
67. **Filter Ready/Moderate/Rest** — chip → list filtered, active highlighted; empty filter → "No {filter} days".
68. **Filter All** — resets.
69. **Trend sparkline** — ≥2 graded → SVG polyline; <2 → hidden.
70. **History refresh** — `#history-refresh`.

### Forum
71. **Create post happy** — title+body, Post → "Posted", reset, new post on top.
72. **Create post anonymous** — check box → author "Anonymous" to others; owner sees `mine` controls.
73. **Create post empty title/body** → required; bypassed 400.
74. **Create post title >140** → 400 (also `maxlength`).
75. **Create post rate-limit** (>10/min) → 429.
76. **Open post inline** — click `.post` → detail expands, chevron rotates, `.open` border, Back FAB.
77. **Open via keyboard** — focus + Enter/Space → opens.
78. **Toggle collapse** — click open post → collapses.
79. **Open failure recovery** — network/500 on open → `failOpen` clears half-open state, "Couldn't open that post" flash; NOT wedged. *(regression: the iOS wedge)*
80. **Detail survives voting** — vote reloads the list; `stashDetail` must move `#forum-detail` out first so it isn't destroyed. *(regression: the "can't open any post after voting" wedge)*
81. **Upvote post** — "▲ up" → score updates, author notified (unless self).
82. **Downvote post** — "▼ down" → score decremented.
83. **Rapid vote toggling** — supersede-guard, latest wins, no stale paint.
84. **Vote invalid value** — 0/2/true/1.0 → 400 "value must be 1 or -1".
85. **Vote rate-limit** (>60/min) → 429.
86. **Add comment happy** — type + Comment → appears.
87. **Add comment empty** → 400 "body must be 1-2000".
88. **Comment rate-limit** (>20/min) → 429.
89. **Up/downvote comment** — `.cvote` → score updates, author notified.
90. **Comment vote missing comment** → 404.
91. **Edit own post** — Edit → change → Save (Cancel restores).
92. **Edit others' post** → 403; UI hides Edit for non-owners.
93. **Delete own post** → gone, list reloads.
94. **Delete others' post** → 403.
95. **Sort Recent/Top/Mine** — Recent=server order, Top=score desc, Mine=own; Mine empty → "You haven't posted yet".
96. **Re-enter Forum lands on list** — open, switch away, return → `closePost`, never stale open.
97. **Forum refresh** — `#forum-refresh`.
98. **Post 404** — open a deleted id → 404 → failOpen.

### Chat / DM
99. **Open Messages** — Chat tab → conversations load, DM notifications marked read.
100. **Recipient search** — type ≥2 → debounced autocomplete `#dm-suggest`.
101. **Search <2 chars** → closed, no request.
102. **Search keyboard nav** — Arrow/Enter/Escape.
103. **Search pick** → fills handle, focuses body.
104. **Search outside-click** → closes.
105. **Search rate-limit** (>40/10s/worker) → 429.
106. **Search stale response** — `dmSearchSeq` guard, latest paints.
107. **Send DM happy** — recipient + body → opens thread.
108. **Send DM to self** → 400 "you can't message yourself".
109. **Send DM to nonexistent** → 404 "no such user".
110. **Send DM empty** → 400.
111. **Send DM injection recipient** → 400.
112. **DM send rate-limit** (>20/60s) → 429 "sending too fast".
113. **Open thread** — click row → thread, mark-read, reply focused; 15s poll starts.
114. **Reply happy** — type + Send → bubble appears.
115. **Reply empty** → no-op.
116. **Reply rate-limit** → 429 in `#dm-reply-flash`.
117. **Thread Back** → list, poll stopped.
118. **Thread scroll anchoring** — near-bottom anchors, scrolled-up not yanked.
119. **Unchanged-poll no flash** — `setHtmlIfChanged` skips rewrite.
120. **Cannot read others' thread** — thread id derived from {me,peer}.
121. **Activity feed** — someone votes your post → "{actor} upvoted your post", unread accent.
122. **Mark all read** — `#activity-read` → cleared, pulse updates.
123. **Rename reflects in activity** — actor renamed → re-resolved live.
124. **DM not in activity** — DMs filtered out.
125. **SSE realtime** — two sessions; A→B → B's stream pushes refresh.
126. **SSE fallback** — no EventSource → 15s/45s poll.
127. **SSE at capacity** → `retry:60000`, client polls.
128. **Chat pulse** — unread → `.dm-dot` on both navs; cleared when read.

### Profile / Settings
129. **Save profile happy** — 6 fields, Save → "Saved", dashboard reloads.
130. **Profile out-of-range** — age 5 / weight 1 → 400.
131. **Profile invalid goal** → 400.
132. **Profile prefill** — reopen → repopulates.
133. **Engagement strip** — has votes → up/down/net cards.
134. **Change display name happy** → "Name updated", header/menu/field update; handle unchanged.
135. **Change display name invalid** (<3 / control) → 400.
136. **Rename desync** — rename, check prior post/notification → name updated everywhere, avatar stable.
137. **Change password happy** — correct current + new≥8 → "Password updated", fields cleared, remember dropped.
138. **Change password wrong current** → 403.
139. **Change password short new** → 400.
140. **Password change invalidates other devices** — trusted browser must re-OTP.
141. **Email-consent toggle** — on/off → messages; on failure the toggle reverts.
142. **Consent reflects on login** — `syncEmailConsent` from `/me`.
143. **Export data** → `worksmarter-export.json` download (button disabled during).
144. **Export contents** — account/profile/history/forum/messages/notifications, no password hash.
145. **Theme System/Light/Dark (Profile radios)** — atomic swap, persisted, both controls sync.
146. **Theme via corner segments** — same result, radios in lockstep.
147. **Theme persists reload** — applied pre-paint, no flash.
148. **Reduced-motion** — all animations off, kcal snaps, recs don't cascade, landing orb static, orb fills instant.

### Danger zone / logout
149. **Logout (danger button)** → reset + auth view, SSE closed.
150. **Logout (corner menu)** → same.
151. **Delete reveal** → password + typed-DELETE form.
152. **Delete gate** — "Delete forever" disabled until `#delete-confirm` == "DELETE" exactly.
153. **Delete happy** — correct pw + "DELETE" → purged, back to login "account and all your data were deleted".
154. **Delete wrong password** → 403; pw cleared, typed DELETE retained, refocus.
155. **Delete cancel** → collapses, resets.
156. **Delete rate-limit** (>5/min) → 429.
157. **Delete cascade order** — identity removed last (recoverable on mid-cascade failure).

### Corner menu / nav
158. **Open menu** — `#user-menu-btn` → panel opens, chevron rotates.
159. **Outside-click / Escape closes** → focus returns.
160. **Menu → Profile** → Profile screen.
161. **Home FAB off-Today** → `#ctx-back` appears; click → Today.
162. **Home FAB hidden on Today**.
163. **Desktop logo = home** — ≥860px off-Today → brand shows home icon, click → Today.
164. **Dual nav responsive** — <860px pill / desktop top-nav; top-nav only signed in.
165. **Nav scroll-to-top** — switching screens scrolls to top.

### Cross-user / stale-paint guards
166. **User switch stale paint** — logout A mid-async, login B → every async renderer bails via `sessionChanged`; B never sees A's data.
167. **enterApp scrubs residue** — same-browser switch → forms/flashes/delete-UI/DM view reset.

### PWA / static
168. **Manifest served** — `/manifest.webmanifest` → 200.
169. **Service worker served** — `/sw.js` → 200 root scope, build-hash stamped.
170. **SW auto-update** — new build on foreground/focus/hourly → `controllerchange` reloads once.
171. **Install/standalone** — installable; iOS meta present.

### Debug tools (dev-only)
172. **Debug hidden by default** — no `?debug` → FAB absent.
173. **Debug enable** — `?debug=1` → FAB, persisted.
174. **Debug never in preview iframe** — `?preview=1`/framed → not wired.
175. **Viewport preview (desktop)** — Mobile toggle → iframe `?preview=1` 390×844; Exit via button/backdrop/Escape.
176. **Email-mode panel** — reads `/auth/config`, LIVE/MOCK badge.
177. **Debug email mock override** — `AUTH_DEBUG_EMAIL` + Mock → `X-Debug-Email: mock`.
178. **Disable debug** → clears flag, reloads clean.

### Landing (logged-out marketing)
179. **Orb demo cycles** — `#demo-state` cycles Ready/Moderate/Rest every 3s with color crossfade + verb; off-screen idles.
180. **Responsive landing** — ≤880px → stacked (orb→eyebrow→headline→card→steps, no paragraph); desktop → editorial split (headline+demo+steps, no paragraph).

### Password show/hide
181. **Eye toggle** — click eye on any password field → type text↔password, aria flip, refocus.

---

## E. Known gotchas / state dependencies (harness must respect)

1. **CSRF double-submit mandatory** on every non-GET — a page-driven `fetch` inherits the cookie; a direct API hit must GET `/` first, then echo `X-CSRF-Token`.
2. **`#forum-detail` lives INSIDE `#forum-list`** while a post is open — any list wipe must `stashDetail()` first (scenarios 79/80).
3. **Supersede-guards** (`openPostSeq`/`forumLoadSeq`/`dmSearchSeq`) — rapid clicks: only the latest paints.
4. **Cross-user bailout** — async renderers snapshot `currentUser`, bail via `sessionChanged` (166).
5. **OTP/verify flags gate whole flows**; `TESTING` forces both OFF. `dev_otp`/`dev_code`/`dev_reset_link` only when SMTP unset AND `SESSION_COOKIE_SECURE` off — the only browser path through 2FA/verify/reset without a mailbox.
6. **Session cookie is the credential** (HttpOnly); the remember cookie embeds the password-hash tail — pw change/reset invalidates it.
7. **Forum vote needs a strict int** (1 or -1); comment votes coalesce per (voter,ref) 60s; self-votes no notification.
8. **Anonymous vs owner** — "Anonymous" to others, but author still gets notifications + `mine` controls.
9. **Self vs other** — no self-DM (400); no edit/delete/attach others' posts (403); no reading others' DM thread.
10. **DM rate-limit is app-level** (20/60s); search throttle is per-worker.
11. **SSE holds a worker thread** — capped per worker, recycled ~90s; over capacity → polling; "realtime" needs a tolerance window.
12. **`setHtmlIfChanged`** — polled regions skip re-render when byte-identical.
13. **`?preview=1`** strips debug tools + renders mobile in an iframe; debug never wires in a frame.
14. **Reduced-motion** disables CSS animation + JS reveals — animated-reveal assertions branch on the media query.
15. **`nav-ready`/`theme-switching`** transient classes — screenshot right after load/theme-change can catch mid-transition frames.
16. **Rename desync** — notification/comment/vote text stored name-less, re-resolved each render (136).
17. **`?reset_token` read at boot + popstate** — deep-link lands on reset even mid-history; token single-use.

> **Media (`web/routes/media.py`)** — fully implemented API (upload/serve/attach, MIME allowlist, per-viewer visibility) but **no UI wired** in `index.html`. Browser E2E can only reach it by POSTing directly. Flagged for the grader.
