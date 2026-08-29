# Work Smarter, Not Harder — Project Requirements

> **Changes from the original proposal**
>
> - **§5 — AI unified.** The separate Random Forest classifier and recommendation engine are now one "AI Decision Engine" with two stages (assess → recommend).
> - **§5 — Output classes generalized.** The fixed five classes (Ready / Moderate / Recovery Needed / Deload / Injury Risk) are gone; the output is now a small, flexible set we'll define after exploring the data.
> - **§6 — Dataset reworked.** Now names both data types — recovery/wellness data for the model and program/exercise data for recommendations — and adds a note on distribution-preserving augmentation.
> - **§7 — Features 6 + 7 merged.** Program Balance Analysis and Action Plan are now one pipeline (analysis feeds the plan), still two capabilities to the user.
> - **§12 — Risk Assessment condensed.** The per-failure breakdown is now a single sentence.
> - **Removed — Testing Plan & Manual Test Scenarios.** The test-type list and feature×test matrix are gone from the proposal; tests live in the repo/CI and the final report.
> - **§13 — MVP → Phased Build.** The "minimum working version" section is replaced with a short phased-build note, answering Noam's "plan in phases."
> - **§14 — Collaborative filtering moved to Future Work.** No longer presented as part of the core system (was in §4 Cold Start).
> - **§14 — Smartwatch made concrete.** Fitbit named as the realistic option (free API, matches our dataset's device family), with Garmin / Apple Health / Strava as further options.

---

## 1. Overview

Work Smarter, Not Harder is an AI-powered coaching platform for athletes. Most fitness apps are good at recording what you did; far fewer help you decide what to do next. That gap is what we want to close.

A typical tracker can tell you whether you trained today. Our platform tries to answer the harder questions athletes actually ask themselves: What should my next workout look like? What should I fix first? How much should I be eating? Is my program balanced, or am I quietly neglecting something? Should I be pushing harder right now, or easing off?

To do that, the system looks at an athlete's recent training and recovery data, forms a picture of where they are, and turns that picture into concrete, prioritized advice — workouts, recovery guidance, nutrition targets, and a clear sense of what to work on next. In short, it behaves like a personal coach rather than a logbook.

## 2. The Problem

Plenty of people train hard and consistently and still feel stuck. Progress stalls, recovery is hit or miss, the program drifts out of balance, calories are guesswork, and it's never quite clear what to prioritize or when to back off.

The information needed to answer these questions usually exists — it's just scattered across sleep, heart rate, soreness, training load, and nutrition, with nothing tying it together into a decision. Our goal is to be that connective layer: take the raw signals an athlete already has and turn them into guidance they can act on.

## 3. Who It's For

We're designing for three kinds of users, and the platform meets each of them where they are.

**Beginners** give us the basics — age, gender, height, weight, and their goal — and in return get a calorie target, a starter program, and a sensible training frequency to build from.

**Intermediate users** add their current training frequency and a more specific goal, and the platform shifts toward helping them optimize how they train and recover rather than just getting started.

**Advanced users** bring richer data — recovery metrics, training load, their current program, and performance history — which lets the system go deeper in both its analysis and its recommendations.

## 4. Starting From Nothing (Cold Start)

A lot of users will arrive with almost no history, so the platform has to be useful on day one. At the start we lean on what's immediately available: the basic athlete profile, the user's goals, whatever recovery and effort metrics they can provide, and their current training frequency.

From there it gets better as it learns. The more a user logs, the more personal the recommendations become, so the experience improves naturally over time instead of demanding a full history up front.

## 5. The AI Decision Engine

Rather than bolting together separate, disconnected pieces, the platform runs everything intelligent through a single decision engine. It works in two stages that feed into one another.

First, it **reads the athlete's state.** A machine-learning model looks at recent metrics and produces an assessment of where the athlete currently stands — sorting them into a small number of readiness/training-state categories. We're deliberately leaving the exact categories (and how many there are) open for now, so we can refine them as we get to know the data rather than committing to definitions we might regret.

Second, it **acts on that assessment.** The same engine takes the state it just inferred and combines it with the user's goals, their program, and their recovery metrics to produce the things the user actually sees: an action plan, workout recommendations, adjustments to their program, and calorie guidance.

For the assessment step we're starting with a Random Forest. It's a natural fit for a course project like this one: we covered it in the ML course, it runs locally and returns predictions quickly, its decisions are reasonably easy to interpret and explain, and it tends to do well on the kind of structured, tabular data we're working with. That said, we haven't locked ourselves in — the engine is built so the model can be swapped out or upgraded later without touching the recommendation logic around it.

The features we expect to feed the model are sleep duration, resting heart rate and how it's drifting from baseline, fatigue and soreness, weekly training frequency, training load, calorie balance, and body-weight trend. We'll finalize that list once we've spent real time with the data.

## 6. Data and Training

The platform draws on two complementary kinds of data.

The first is **recovery and wellness data** — athlete-level signals like sleep, heart rate, fatigue, soreness, training load, perceived effort, and a readiness indicator. This is what we'll use to train and validate the state-assessment model, so finding data with an actual readiness signal is a priority.

The second is **program and exercise data** — a large catalog of real workout programs and exercises that powers the workout recommendations and the program-balance analysis.

We'll pull from public fitness and sports-science datasets, recovery-logging datasets, and established training guidelines. Labeled recovery data is the scarcer of the two, so where it runs thin we may strengthen the training set with distribution-preserving techniques — for example, resampling whole records or balancing underrepresented classes — rather than inventing data out of thin air. Anything we generate this way will be documented openly in the report.

## 7. Features

**User accounts.** Registration, login, logout, and properly hashed passwords.

**Athlete profile.** Age, gender, height, weight, and goal.

**Training-state analysis.** The platform assesses where the athlete currently stands and surfaces that to them.

**Calorie recommendation.** A daily calorie target tailored to the user.

**Workout generator.** Recommends training plans based on the user's goal, the days they have available, their equipment, and their split preference, drawing on the program catalog.

**Program balance and action plan.** These run as a single pipeline: the system spots undertrained muscle groups and other gaps, then translates those findings into a short, prioritized list of things to do — improve sleep, eat more, add volume where it's lacking, dial training load up or down. To the user they read as two capabilities, but under the hood the analysis simply feeds the plan, which saves us from building the same logic twice.

**Dashboard.** The user's current state, active workout plan, calories, and progress history in one place.

**History tracking.** Past analyses and recommendations are stored so progress is visible over time.

## 8. Architecture

The system is split across three containers, each with a clear job.

The **web container** handles the frontend, authentication, and the API. It's the only container exposed to users.

The **database container** (MongoDB) holds user data, profiles, programs, and analysis history, and stays internal.

The **AI container** runs model inference and generates recommendations, and it stays internal as well.

```
User
 |
 v
Web Container
 |\
 | \
 v  v
AI Container   Database Container
```

## 9. Database

The data lives in four collections. **users** stores the username and password hash. **profiles** holds age, gender, height, weight, goal, and training frequency. **programs** stores workout programs. **analysis_history** keeps each assessment result, the recommendations it produced, calories, and a timestamp.

## 10. Parallelism and Scaling

The platform is built to scale out horizontally. Today it runs a single AI container, but the web container can distribute inference requests across multiple AI replicas, and Docker replicas let us add capacity without changing any application logic. The payoff is straightforward: prediction requests run in parallel, responses stay fast, and the experience holds up when traffic climbs.

## 11. Security

Passwords are only ever stored as hashes, and protected endpoints require login. We rate-limit requests to guard against spam and abuse, validate input before acting on it, and defend against NoSQL injection. As a structural safeguard, only the web container is ever exposed to the outside world.

## 12. Risk Assessment

The main risks are handled gracefully: if the AI service or database is unavailable the app degrades instead of breaking, missing wearable data falls back to manual entry, and spam, oversized uploads, and invalid input are caught by rate limiting and validation.

## 13. Phased Build

We build in phases so there's always a working product: first the core loop — accounts, the AI engine (assess + recommend), dashboard, and calorie/workout output on Docker — then the rest layered on top.

## 14. Future Work and Stretch Goals

**Collaborative-filtering personalization (future).** Once the platform has enough users and history, we can sharpen recommendations with collaborative filtering — drawing on athletes with similar profiles (age, gender, experience, goals, recovery patterns, training history) to inform someone's plan. Over time the recommendations would shift from population-based toward genuinely personal, grounded in the user's own history. This is planned as future work, not part of the core deliverable.

**Smartwatch integration.** Importing real wearable data — most likely Fitbit, since its API is free and it matches the device family our starting dataset comes from — with Garmin, Apple Health, and Strava as further options.

**Other ideas.** Progress graphs, an exercise video library, an injury-prevention module, and personalized progression recommendations.
