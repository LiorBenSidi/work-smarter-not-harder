# AI Decision Engine

The `ai` service predicts the user's current readiness state and returns personalized training and recovery recommendations.

The main prediction contract is:

`POST /predict {"features": {...}} -> {"state": ..., "proba": {...}, "recommendations": [...]}`

When enough valid profile information is available, the response also includes a daily calorie target.

## Dataset and preprocessing

The model is trained on the PMData sports-logging dataset, available on Kaggle:

https://www.kaggle.com/datasets/vlbthambawita/pmdata-a-sports-logging-dataset

The dataset contains wellness and training information from 16 participants over approximately five months.

The training dataset is built by merging daily wellness data with sRPE training data by participant and date. The model uses four features:

- `sleep_hours`
- `fatigue`
- `soreness`
- `training_load`

The PMData readiness score is converted into three classes: `Rest`, `Moderate`, and `Ready`.

Participant IDs are preserved during preprocessing so validation can be grouped by participant. This avoids placing records from the same person in both training and validation data.

The raw dataset is not committed to the repository.

## Model

The final model is a Random Forest classifier. It was chosen because the dataset is relatively small and tabular, and because the relationships between recovery metrics and readiness may be nonlinear.

Several Random Forest configurations were compared during training. The selected candidate is `leaf6_depth_none__balanced`, and the current `Ready` probability threshold is `0.58`.

Class imbalance is handled using `class_weight="balanced"`, which gives more importance during training to classes with fewer examples.

The model uses sleep hours, fatigue, soreness, and training load as input features. User inputs are converted when needed to match the scales used during model training.

The trained model is stored in `ai/model/model.pkl`, and the training results are stored in `ai/model/training_report.json`.

The model is baked into the Docker image and loaded locally at runtime. No model download or training occurs while the service is running.

## Recommendations and calories

After predicting the readiness state, the recommendation engine uses the current recovery metrics and available user information to generate actionable recommendations.

The recommendation engine can use:

- readiness state and current recovery metrics
- the user's goal
- optional recent history
- optional weekly program information

When history is available, the engine can detect repeated low-readiness states and trends such as declining sleep or increasing fatigue.

When weekly program information is available, it can identify simple training-volume imbalances between muscle groups.

The engine does not invent missing measurements. If optional information is unavailable or invalid, it uses only the valid information that was actually provided.

Daily calorie targets are calculated using the Mifflin-St Jeor equation when enough valid profile information is available. Invalid or incomplete profile data does not cause prediction to fail; the calorie field is simply omitted.

## Validation and testing

The model is validated by participant rather than by randomly splitting individual rows. This provides a more realistic test of generalization to users who were not seen during training.

The AI tests cover:

- readiness binning
- model inference and probabilities
- recommendation generation
- partial and invalid inputs
- trend analysis
- program balance
- calorie calculation
- queue and API compatibility

The recommendation-engine test suite currently passes all 14 tests. The full AI prediction path was also tested successfully both locally and inside the Docker container.

## Performance and parallel programming

The measured average `predict_one` latency over 1,000 predictions was approximately **33.6 ms**.

Inside the Docker container, total process memory after loading the inference code and trained model was approximately **159.24 MB**. The estimated memory increase from importing the inference stack and loading the model was approximately **151.11 MB**.

Single-row prediction is not artificially parallelized. CPU-bound prediction requests are handled through the bounded process pool in front of `predict_one`, while NumPy and Pandas vectorized operations are used where appropriate in the data pipeline.

## Reproducibility

Training produces:

- `ai/model/model.pkl`
- `ai/model/training_report.json`

At runtime, the service only loads the trained model and does not retrain it. Model dependencies are pinned in `ai/requirements.txt`, and the raw dataset remains outside the repository.