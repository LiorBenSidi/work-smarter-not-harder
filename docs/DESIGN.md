# Design — Work Smarter, Not Harder

> Living design doc. Update it as decisions are made; reference the PR that changes the design.
> Full requirements: [`PROPOSAL.md`](PROPOSAL.md) · [`Proj_Guidelines.pdf`](Proj_Guidelines.pdf).

## 1. Overview
_(One paragraph: what the system does — an AI sports-coaching platform; see `PROPOSAL.md`.)_

## 2. Architecture (3 containers — only `web` exposed)
- **web** — Flask: auth (werkzeug hashing), API, frontend.
- **db** — MongoDB: `users`, `profiles`, `programs`, `analysis_history`.
- **ai** — Random Forest readiness classifier + recommendation engine; internal REST `POST /predict`.

_(Add a component diagram + data-flow as it solidifies.)_

## 3. Data model
_(Collections + key fields — see PROPOSAL §9.)_

## 4. API contracts
| Endpoint | Method | Container | Notes |
|---|---|---|---|
| `/register` `/login` `/logout` | POST | web | auth |
| `/predict` | POST | ai (internal) | readiness classification |
| … | | | |

## 5. AI
- Model: Random Forest (trained offline, **baked into the image** — no runtime download).
- Features + output classes: see PROPOSAL §5.
- Scaling: `multiprocessing` for CPU-bound inference; replicas for multi-machine.

## 6. Decisions (mini-ADRs)
_(Short records of significant choices: date · decision · why · alternatives considered.)_
