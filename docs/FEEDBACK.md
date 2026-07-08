> ⚠️ SUPERSEDED by the TA's WSNH_Guidelines.pdf (8 Jul 2026) — see docs/GUIDELINES.md. Kept for history. The rubric is now 75 + 5 (Job Queue) + 10 + 10, not 80 + 10 + 10.

# Noam's feedback — final-project grading spec

> _Source: Noam's feedback on our submitted proposal (Moodle, 25 Jun 2026) — `feedback.md` in the course's
> `Parallel Programming/Project Guidelines/`. Reproduced **verbatim** below (a trailing copy-paste artifact line
> was removed). This is the **grading spec** for the final project: **80 + 10 + 10**._

---

Noam  is NI and can make mistakes.

# Project Guidelines: Work smarter

**Course:** Software Engineering for ML (Spring 2026)

**Authors:** Lior, Shiri, Elad

**Date:** June 2026

---

## Overview & Feedback

The idea is good and you might even want to plan in phases to make sure that if/when the amount of work explodes, you still have a viable product.

You give too much freedom to Gemini. This doc is no place for tests, mvp, badly layout risk assemsment etc. Your really should try harder.

I will suggest a few more features to make this project well-rounded and complete using what you learned this semester.

Hopefully, these features make sense with the vision you had for the project; if they don't, feel free to change to another similar feature that will test the same concepts.

> ⚠️ **Important:** Let me know via mail if you want to change these guidelines.

### Grading & Submission Policy
* **Target Score (100 pts):** These guidelines represent the requirements needed to achieve a perfect score. You do not have to complete them all, and we do not expect you to.
* **Partial Credit:** You will get partial credit for a partial completion of each feature.
* **Penalties:**
  * Each bug found: **-5 points**
  * Each week of delay in submission: **-5 points**

---

## Technical & Feature Guidelines

### 1. Project Proposal (80 Points)
Implement a working, localhost web application that implements your proposed idea.
It should include everything mentioned in your proposal. **EVERYTHING** (except the strech goals). If you want to remove some features, let us know beforehand.

### 2. Online Forum & Communication Suite (10 Points)
Implement an integrated online forum resembling a social network or microblogging platform where users can share ideas, achievements, academic tips, and app feedback.

#### Core Forum Features:
1. **Public Posting:** Clients can create posts visible to everyone. Posts must support a title, body, images, and video attachments.
2. **Anonymity:** Users must have an explicit toggle to post anonymously.
3. **Commenting System:** Users can comment on any post with support for text, images, and videos.
4. **Engagements & Metrics:** Implement Upvote/Downvote functionality for posts and comments. Users must have a profile dashboard to track their total received engagement metrics.
5. **Direct Messaging (DM):** A private, secure peer-to-peer messaging feature supporting text, images, and video attachments.
6. **Live Notifications:** Real-time push notifications inside the web app for new DMs and upvote/downvote interactions.
7. **Security & Rate Limiting:** You must architect defenses against spamming (e.g., api rate-limiting to prevent a single user from sending 1,000 messages rapidly) and storage abuse (e.g., file-size restrictions on video uploads).
8. **Cold Seeding:** The application must launch with pre-seeded data consisting of simulated "fake" client accounts, historical posts, and active comment threads to populate the UI.

> 💡 **Technical Note:** All forum feeds, chat history retrievals, and notification delivery must operate in real-time without requiring manual page refreshes.

### 3. Website Deployment & CI/CD (10 Points)
* **Website Deployment:** Deploy your website to an azure cloud server (we will supply you with a server and a domain if you choose to do implement this feature, but you have to implement the deployment yourself). The website should be accessible to the public and be able to scale easily (use parallelization in your code).
* **CI/CD Pipeline:** Implement a CI/CD pipeline for your project's private GitHub repository - the pipeline should include a test set that will run on each commit and check that all the tests pass - if they do, the pipeline should automatically deploy the new version of the website to the server. Only implementing the CI/CD pipeline without website deployment (only checking that the tests pass on each commit) will award you partial credit of 5 points.
