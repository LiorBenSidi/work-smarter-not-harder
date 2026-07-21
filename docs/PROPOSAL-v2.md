> _**Status:** the team's **revised** spec — a cleaner rewrite addressing Noam's "plan in phases / don't AI-dump"
> feedback (authored in Elad's Claude Code) — and the **current** feature spec the team builds to. It was sent to
> the TA on 28 Jun; the TA responded (8 Jul) with the graded rubric [`GUIDELINES.md`](GUIDELINES.md)
> (`WSNH_Guidelines.pdf`), **now the source of truth** (it supersedes Noam's feedback). Those guidelines permit
> notified feature changes, so the main scope change (**F6+F7 merged → 8 features**) stands — **nothing is
> pending**. The **5 course test types + feature×test matrix are still required** (tracked in the repo /
> [`DESIGN.md`](DESIGN.md), not in this doc)._

---

# PROJECT REQUIREMENTS – Work Smarter, Not Harder

## 1. Project Overview

Work Smarter, Not Harder is an AI-powered sports coaching platform that helps athletes make smarter training, recovery, and nutrition decisions.

Instead of only answering:

"Am I ready to train?"

the platform also helps answer:

- What should I do in my next workout?
- What should I improve first?
- How many calories should I eat?
- Is my workout program balanced?
- Should I adjust how hard I train right now?

The system combines an AI-based assessment of the athlete's current training state with workout recommendations, recovery analysis, nutrition guidance, and personalized action plans.

---

## 2. Problem Statement

Many athletes train consistently but still struggle with lack of progress, poor recovery, program imbalance, incorrect calorie intake, uncertainty about what to improve first, and not knowing how to adjust training based on their current state.

Most fitness applications track workouts but do not provide intelligent decision support. Our platform acts as a personal AI sports coach that turns raw inputs into concrete, prioritized guidance.

---

## 3. Target Users

### Beginner Users

Provide:

- Age, gender, height, weight
- Goal

System provides:

- Calorie target
- Beginner workout program
- Recommended training frequency

### Intermediate Users

Provide:

- Personal information
- Training frequency
- Fitness goal

System helps optimize training and recovery.

### Advanced Users

Provide:

- Recovery metrics
- Training load
- Workout program
- Performance history

System performs deeper analysis and recommendations.

---

## 4. Cold Start Users

Many users will have very little historical information.

For new users the system initially relies on:

- Basic athlete information (age, gender, height, weight)
- Training goals
- Currently available recovery and effort metrics
- Current training frequency

As more information is collected, recommendations become increasingly personalized. This allows the platform to be useful from day one while continuously improving over time.

---

## 5. AI Decision Engine

The platform uses a single, unified AI decision engine rather than separate, disconnected components. The engine has two responsibilities that operate as one pipeline:

1. **State assessment.** A supervised machine-learning model evaluates the athlete's recent metrics and produces an assessment of their current training state. The output is a small set of readiness/training-state categories. The exact category definitions and their number are intentionally kept flexible at this stage and may be refined as we explore the data.

2. **Recommendation generation.** The same engine combines that assessment with the user's goals, workout program, and recovery metrics to generate:
   - Action plans
   - Workout recommendations
   - Program adjustments
   - Calorie recommendations

### Chosen Model

Random Forest is our current model of choice for the state-assessment step.

Rationale:

- Covered in the ML course
- Runs locally with fast inference
- Easy to interpret and explain
- Performs well on structured, tabular fitness data

The choice of model is not locked in; the engine is designed so the classifier can be swapped or extended without changing the surrounding recommendation logic.

### Input Features (candidate set)

- Sleep duration
- Resting heart rate (and change from baseline)
- Fatigue and soreness indicators
- Weekly training frequency
- Training load
- Calorie balance (deficit/surplus)
- Body-weight trend

The final feature set will be determined during data exploration and may change.

---

## 6. Dataset and Training Data

The system draws on two complementary types of data:

- **Recovery / wellness data** — athlete-level metrics (sleep, heart rate, fatigue, soreness, training load, effort, and a readiness indicator) used to train and validate the state-assessment model.
- **Program / exercise data** — a large catalog of real workout programs and exercises used to power workout recommendations and program-balance analysis.

Potential sources include public fitness and sports-science datasets, recovery/wellness logging datasets, and established sports-science guidelines. Where the available labeled data is limited, we may use resampling and distribution-preserving augmentation (e.g., bootstrapping whole records, or class-balancing techniques) to strengthen the training set. Any synthetic augmentation will be documented transparently.

---

## 7. Main Features

### Feature 1 – User Accounts
Register, login, logout, password hashing.

### Feature 2 – Athlete Profile
Age, gender, height, weight, goal.

### Feature 3 – Training-State Analysis
Assess the athlete's current training state and surface it to the user.

### Feature 4 – Calorie Recommendation
Estimate a daily calorie target.

### Feature 5 – Workout Generator
Recommend training plans according to goal, available training days, equipment, and split preference, drawing on the program catalog.

### Feature 6 – Program Balance & Action Plan
A single analysis pipeline that detects undertrained muscle groups and other gaps, then turns those findings into prioritized, actionable recommendations.

Examples of recommendations:

- Improve sleep
- Increase calories
- Add volume to an undertrained area
- Adjust training load

> **Note:** Balance analysis and the action plan are implemented as one pipeline (analysis feeds prioritization), but remain two distinct capabilities from the user's perspective.

### Feature 7 – Dashboard
Display current state, current workout plan, calories, and progress history.

### Feature 8 – History Tracking
Store previous analyses and recommendations.

---

## 8. Container Architecture

The system uses three containers.

### Container 1 – Web Container
Frontend, authentication, API endpoints. Only this container is exposed to users.

### Container 2 – Database Container (MongoDB)
User data, profiles, programs, analysis history. Internal only.

### Container 3 – AI Container
Model inference and recommendation generation. Internal only.

### Architecture Diagram

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

---

## 9. Database Design

Collections:

**users** — username, password_hash

**profiles** — age, gender, height, weight, goal, training_frequency

**programs** — workout programs

**analysis_history** — assessment result, recommendations, calories, timestamp

---

## 10. Parallel Programming and Scalability

The system is designed to scale horizontally.

- Current version: a single AI container.
- The web container can distribute inference requests across multiple AI replicas.
- Docker replicas allow horizontal scaling without changing application logic.

Benefits: parallel prediction requests, faster response times, and a better user experience under load.

---

## 11. Security

- **Password security** — passwords stored only as hashes.
- **Authentication** — protected endpoints require login.
- **Rate limiting** — protection against spam and abuse.
- **Input validation** — invalid inputs are rejected.
- **Injection protection** — defenses against NoSQL injection.
- **Internal services** — only the web container is exposed externally.

---

## 12. Risk Assessment

Key failure modes and mitigations:

- **AI service unavailable** → graceful error handling; the rest of the app stays usable.
- **Database unavailable** → fallback handling so the user can continue with reduced functionality.
- **Missing wearable data** → fall back to manually entered values.
- **Abuse / spam** → rate limiting and upload-size restrictions.
- **Invalid input** → validation before any computation.

---

## 13. Testing & CI

Tests are maintained as real, executable code and run automatically in the CI pipeline on every commit. Coverage focuses on the core flows: authentication, the AI assessment and recommendation pipeline, and the workout/calorie features. Integration and basic load checks are included for the request-heavy paths.

---

## 14. MVP

A minimum working version includes: user accounts, the AI decision engine (assessment + recommendations), database persistence, the dashboard, calorie recommendation, the workout generator, and Docker deployment.

---

## 15. Future Work & Stretch Goals

### Collaborative-Filtering Personalization (Future)
As the platform collects more users and historical training data, recommendations can be improved with collaborative filtering — recommending strategies based on athletes with similar characteristics (age, gender, experience, goals, recovery patterns, workout history). Over time, recommendations shift from population-based toward highly personalized, based on the user's own history. This is planned as future work and is not part of the core deliverable.

### Smartwatch Integration
Garmin Connect, Apple Health, Google Fit, Strava, fitbit

### Additional Features
Progress graphs, exercise video library, injury-prevention module, personalized progression recommendations.
