"""Unit tests for Forum validation (posts + comments). OWNER: Lior.

Injection-safe: non-string title/body and non-bool `anonymous` are rejected before any query.
"""
import sys

import pytest


@pytest.fixture
def forum(web_app_module):
    return sys.modules["routes.forum"]


def test_accepts_a_valid_post(forum):
    """An ordinary post passes and comes back as the cleaned triple the route stores, defaulting to attributed rather than anonymous."""
    assert forum.validate_post({"title": "Hi", "body": "Hello world"}) == ("Hi", "Hello world", False)


def test_post_anonymous_flag_is_honored(forum):
    """Asking to post anonymously is actually carried through to the stored value — a request that were silently dropped would attach the author's name to something they chose to hide."""
    assert forum.validate_post({"title": "Hi", "body": "x", "anonymous": True})[2] is True


@pytest.mark.parametrize("bad", [None, [], "x", {"title": "Hi"}, {"body": "x"}])
def test_rejects_malformed_post(forum, bad):
    """A body that is not an object, or that is missing either the title or the body, is rejected before any query is built."""
    with pytest.raises(ValueError):
        forum.validate_post(bad)


@pytest.mark.parametrize("field", ["title", "body"])
def test_rejects_injection_object_in_post_field(forum, field):
    """A Mongo operator object is refused in the title AND the body, so neither text field can carry a query document into the store."""
    post = {"title": "Hi", "body": "x"}
    post[field] = {"$gt": ""}
    with pytest.raises(ValueError):
        forum.validate_post(post)


def test_rejects_empty_title(forum):
    """A whitespace-only title is refused, so the feed cannot fill with entries that render as blank rows."""
    with pytest.raises(ValueError):
        forum.validate_post({"title": "   ", "body": "x"})


def test_rejects_non_bool_anonymous(forum):
    """The anonymity flag must be a real boolean — a truthy string like "yes" is refused rather than being coerced, because guessing wrong here exposes an author who asked not to be named."""
    with pytest.raises(ValueError):
        forum.validate_post({"title": "Hi", "body": "x", "anonymous": "yes"})


def test_accepts_a_valid_comment(forum):
    """An ordinary comment passes and comes back as the cleaned text that gets stored."""
    assert forum.validate_comment({"body": "nice post"}) == "nice post"


@pytest.mark.parametrize("bad", [None, {}, {"body": "  "}, {"body": {"$ne": None}}])
def test_rejects_malformed_comment(forum, bad):
    """A comment that is absent, empty, whitespace-only, or an operator object is refused before it reaches the store."""
    with pytest.raises(ValueError):
        forum.validate_comment(bad)
