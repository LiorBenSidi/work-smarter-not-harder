# PROJECT REQUIREMENTS – Work Smarter, Not Harder

## 1. Project Overview

Work Smarter, Not Harder is an AI-powered sports coaching platform that helps athletes make smarter training, recovery, and nutrition decisions.

Instead of only answering:

“Am I ready to train?”

the platform answers:

- What should I do in my next workout?
- What should I improve first?
- How many calories should I eat?
- Is my workout program balanced?
- Should I train harder, maintain, recover, or deload?

The system combines AI-based readiness classification, workout generation, recovery analysis, nutrition recommendations, and personalized action plans.

---

## 2. Problem Statement

Many athletes train consistently but struggle with:

- Lack of progress.
- Poor recovery.
- Program imbalance.
- Incorrect calorie intake.
- Uncertainty about what to improve first.
- Not knowing how to adjust training based on recovery status.

Most fitness applications track workouts but do not provide intelligent decision support.

Our platform acts as a personal AI sports coach.

---

## 3. Target Users

### Beginner Users

Provide:

- Age
- Gender
- Height
- Weight
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

For new users the system will initially rely on:

- Basic athlete information (age, gender, height, weight)
- Training goals
- Current recovery metrics
- Fatigue score
- Soreness score
- Current training frequency

As more information is collected, recommendations become increasingly personalized.

This allows the platform to be useful from day one while continuously improving over time.

### Future Personalization with Collaborative Filtering

As the platform collects more users and historical training data, recommendations can be further improved using **Collaborative Filtering** techniques.

For users with limited personal history, the system may recommend training strategies based on athletes with similar characteristics, such as age, gender, training experience, goals, recovery patterns, and workout history.

As more personal data is collected, the recommendations gradually shift from population-based recommendations to highly personalized recommendations based on the user's own historical performance.


---

## 5. AI Component

### Model

Random Forest Classifier (Local AI Model)

### Why Random Forest?

- Learned in ML course
- Runs locally
- Fast inference
- Easy to explain
- Good performance on structured fitness data

### Input Features

- Sleep hours
- Resting heart rate
- Heart-rate change from baseline
- Fatigue score
- Soreness score
- Weekly training frequency
- Training load
- Calorie deficit/surplus
- Body-weight trend

### Output Classes

The Random Forest classifies the athlete's current training readiness state.

1. Ready
2. Moderate
3. Recovery Needed
4. Deload Recommended
5. Injury Risk

### Recommendation Engine

The Random Forest only performs classification.

A separate recommendation engine uses:

- Classification result
- User goals
- Workout program
- Recovery metrics

to generate:

- Action plans
- Workout recommendations
- Program adjustments
- Calorie recommendations

---

## 6. Dataset and Training Data

The model will be trained using a combination of public fitness datasets and sports-science knowledge sources.

Potential sources:

- Kaggle fitness datasets
- ACSM recommendations
- ACE Fitness resources
- Sports science research articles
- Public recovery and performance datasets

Features used for training include:

- Sleep duration
- Fatigue
- Soreness
- Heart rate
- Training frequency
- Training load
- Calories
- Body weight trends

---

## 7. Main Features

### Feature 1 – User Accounts

- Register
- Login
- Logout
- Password hashing

### Feature 2 – Athlete Profile

- Age
- Gender
- Height
- Weight
- Goal

### Feature 3 – Readiness Analysis

Predict athlete readiness.

### Feature 4 – Calorie Recommendation

Estimate daily calorie target.

### Feature 5 – Workout Generator

Generate training plans according to:

- Goal
- Training days
- Split preference

### Feature 6 – Program Balance Analysis

Detect undertrained muscle groups.

### Feature 7 – Action Plan

Generate prioritized recommendations.

Examples:

- Improve sleep
- Increase calories
- Add chest volume
- Reduce training load

### Feature 8 – Dashboard

Display:

- Current readiness
- Current workout plan
- Calories
- Progress history

### Feature 9 – History Tracking

Store previous analyses and recommendations.

---

## 8. Container Architecture

The system uses three containers.

### Container 1 – Web Container

Responsibilities:

- Frontend
- Authentication
- API endpoints

Only this container is exposed to users.

### Container 2 – MongoDB Container

Responsibilities:

- User data
- Profiles
- Programs
- Analysis history

Internal only.

### Container 3 – AI Container

Responsibilities:

- Random Forest inference
- Recommendation generation

Internal only.

### Architecture Diagram

User
 |
 v
Web Container
 |\
 | \
 v  v
AI Container   MongoDB Container

---

## 9. Database Design

Collections:

### users

- username
- password_hash

### profiles

- age
- gender
- height
- weight
- goal
- training_frequency

### programs

- workout programs

### analysis_history

- readiness score
- classification
- calories
- timestamp

---

## 10. Parallel Programming and Scalability

The system is designed to scale.

Current version:

- One AI container

Future scaling:

- Multiple AI replicas
- Horizontal scaling
- Docker replicas
- Multiple machines

Benefits:

- Parallel prediction requests
- Faster response times
- Better user experience

Implementation Plan:

- Multiple AI containers can run simultaneously.
- The web container distributes prediction requests between AI replicas.
- Additional AI containers can be deployed on multiple machines.
- Docker replicas allow horizontal scaling without changing application logic.

---

## 11. Security

### Password Security

Passwords are stored only as hashes.

### Authentication

Protected endpoints require login.

### Rate Limiting

Protect against spam requests.

### Input Validation

Reject invalid inputs.

### Injection Protection

Prevent NoSQL injection attacks.

### Internal Services

Only the web container is exposed externally.

---

## 12. Fault Tolerance and Risk Assessment

### AI Service Failure

Impact:

Predictions unavailable.

Solution:

Graceful error handling.

### MongoDB Failure

Impact:

History cannot be saved.

Solution:

Fallback handling and recovery.

### Smartwatch API Failure

Impact:

Wearable data unavailable.

Solution:

Continue using manually entered data.

### Spam Requests

Impact:

Resource exhaustion.

Solution:

Rate limiting.

### Invalid Inputs

Impact:

Incorrect calculations.

Solution:

Input validation.

---

## 13. Testing Plan

### Test Types

- Unit Tests
- Integration Tests
- System Tests
- Stress Tests
- Security Tests

### Feature × Tests Matrix

| Feature | Unit | Integration | System | Stress | Security |
|----------|----------|----------|----------|----------|----------|
| Register | Yes | Yes | Yes | No | Yes |
| Login | Yes | Yes | Yes | No | Yes |
| User Profile | Yes | Yes | Yes | No | No |
| Readiness Analysis | Yes | Yes | Yes | Yes | No |
| Calorie Recommendation | Yes | Yes | Yes | No | No |
| Workout Generator | Yes | Yes | Yes | No | No |
| Program Balance Analysis | Yes | Yes | Yes | No | No |
| Dashboard | Yes | Yes | Yes | No | No |
| History Tracking | Yes | Yes | Yes | No | No |
| Authentication | Yes | Yes | Yes | No | Yes |

---

## 14. Manual Test Scenarios

- Multiple users simultaneously
- Rapid button clicking
- Interrupted requests
- Invalid inputs
- Large request volumes
- Login/logout edge cases

---

## 15. MVP

Minimum Working Version:

- User accounts
- Random Forest classifier
- MongoDB persistence
- Dashboard
- Calorie recommendation
- Workout generator
- Docker deployment

---

## 16. Stretch Goals

### Smartwatch Integration

- Garmin Connect
- Apple Health
- Google Fit
- Strava

### Additional Features

- Progress graphs
- Exercise video library
- Injury-prevention module
- Personalized progression recommendations

