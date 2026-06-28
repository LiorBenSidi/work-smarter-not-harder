"""Unit tests for Forum validation (posts + comments). OWNER: Lior.

Injection-safe: non-string title/body and non-bool `anonymous` are rejected before any query.
"""
import sys

import pytest


@pytest.fixture
def forum(web_app_module):
    return sys.modules["routes.forum"]


def test_accepts_a_valid_post(forum):
    assert forum.validate_post({"title": "Hi", "body": "Hello world"}) == ("Hi", "Hello world", False)


def test_post_anonymous_flag_is_honored(forum):
    assert forum.validate_post({"title": "Hi", "body": "x", "anonymous": True})[2] is True


@pytest.mark.parametrize("bad", [None, [], "x", {"title": "Hi"}, {"body": "x"}])
def test_rejects_malformed_post(forum, bad):
    with pytest.raises(ValueError):
        forum.validate_post(bad)


@pytest.mark.parametrize("field", ["title", "body"])
def test_rejects_injection_object_in_post_field(forum, field):
    post = {"title": "Hi", "body": "x"}
    post[field] = {"$gt": ""}
    with pytest.raises(ValueError):
        forum.validate_post(post)


def test_rejects_empty_title(forum):
    with pytest.raises(ValueError):
        forum.validate_post({"title": "   ", "body": "x"})


def test_rejects_non_bool_anonymous(forum):
    with pytest.raises(ValueError):
        forum.validate_post({"title": "Hi", "body": "x", "anonymous": "yes"})


def test_accepts_a_valid_comment(forum):
    assert forum.validate_comment({"body": "nice post"}) == "nice post"


@pytest.mark.parametrize("bad", [None, {}, {"body": "  "}, {"body": {"$ne": None}}])
def test_rejects_malformed_comment(forum, bad):
    with pytest.raises(ValueError):
        forum.validate_comment(bad)
