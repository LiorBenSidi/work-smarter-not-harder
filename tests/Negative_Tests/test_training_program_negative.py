"""Negative tests — the Advanced-tier training-programme wall (#566). OWNER: Lior.

`validate_profile`'s new `training_program` field from the WRONG side, over HTTP rather than in
isolation: injection objects, wrong container types, wrong value types, both range ends, and an
oversized payload. The unit tests in `Unit_Tests/test_profile_validation.py` prove the validator
rejects these; these prove the ROUTE does — that nothing between the request and the store lets one
through, and that a rejected payload leaves no partial write behind.

Bounds mirror `routes/profile.py`'s `TRAINING_PROGRAM_GROUPS` / `MAX_SETS_PER_GROUP` — if one moves
there, the matching case here moves with it.
"""
import pytest

GOOD_PROFILE = {"age": 25, "gender": "other", "height": 175.0, "weight": 72.5,
                "goal": "maintain", "training_frequency": 4}


@pytest.fixture
def user_client(profile_client):
    profile_client.post("/register", json={"username": "negtp", "password": "s3cretpw!", "email": "tp@ex.com"})
    profile_client.post("/login", json={"username": "negtp", "password": "s3cretpw!"})
    return profile_client


@pytest.mark.parametrize("bad", [
    {"$gt": ""},                                   # Mongo operator injection as a GROUP name
    {"chest": {"$ne": None}},                      # ...and as a VALUE
    {"chest": [12]}, {"chest": {"sets": 12}},      # nested containers where a number belongs
    {"chest": "12"}, {"chest": None},              # stringly-typed / null set counts
    {"chest": True},                               # bool is an int subclass — must not store as 1
    {"chest": 12.5},                               # sets are whole units of work
    {"chest": -1}, {"chest": 61},                  # one step outside each end of 0-60
    {"forearms": 8}, {"CHEST": 8}, {"": 8},        # outside ai/'s 10-group taxonomy (case-sensitive)
    [], "chest", 42, [("chest", 3)],               # not a mapping at all
])
def test_route_rejects_a_malformed_training_program(user_client, bad):
    """Each malformed shape is refused with a 400 at the route, never quietly coerced or dropped.

    Silent dropping is the dangerous failure here, not a crash: the athlete would see a saved profile
    while the balance analysis received nothing, which is indistinguishable from the feature working.
    """
    resp = user_client.post("/profile", json={**GOOD_PROFILE, "training_program": bad})
    assert resp.status_code == 400


def test_an_oversized_programme_is_rejected(user_client):
    """More entries than the taxonomy has groups is malformed by construction — bound it before iterating."""
    program = {f"group{i}": 5 for i in range(50)}
    resp = user_client.post("/profile", json={**GOOD_PROFILE, "training_program": program})
    assert resp.status_code == 400


def test_a_rejected_programme_leaves_the_previous_profile_intact(user_client):
    """A 400 must not be a partial write: the athlete's existing programme survives a bad submit
    rather than being half-replaced by the payload that was refused."""
    good = {**GOOD_PROFILE, "training_program": {"chest": 12}}
    assert user_client.post("/profile", json=good).status_code == 200
    assert user_client.post("/profile", json={**GOOD_PROFILE,
                                              "training_program": {"chest": 12, "forearms": 9}}).status_code == 400
    assert user_client.get("/profile").get_json()["profile"]["training_program"] == {"chest": 12}
