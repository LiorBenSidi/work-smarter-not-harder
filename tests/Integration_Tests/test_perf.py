"""Integration tests for the response-perf layer: gzip + static-asset caching. OWNER: Lior.

These pin the wire-level optimizations so a regression is caught in CI: the SPA shell is
gzipped and round-trips intact, gzip self-skips when it shouldn't apply (no Accept-Encoding, tiny bodies,
binary files), and the static assets carry a cacheable header while the service worker stays no-cache.
"""
import gzip

GZIP = {"Accept-Encoding": "gzip"}


def test_index_is_gzipped_and_roundtrips(client):
    """The app shell is compressed for clients that accept it, decompresses back to exactly the original bytes, and is genuinely smaller — compression that is not lossless would corrupt the page, and compression that does not shrink is pure cost."""
    plain = client.get("/").get_data()                       # no Accept-Encoding -> uncompressed
    resp = client.get("/", headers=GZIP)
    assert resp.headers.get("Content-Encoding") == "gzip"
    assert "Accept-Encoding" in resp.headers.get("Vary", "")
    assert gzip.decompress(resp.get_data()) == plain         # lossless
    assert len(resp.get_data()) < len(plain)                 # and actually smaller


def test_index_not_gzipped_without_accept_encoding(client):
    """A client that did not advertise compression gets plain HTML, so an old or unusual browser is not handed bytes it cannot read."""
    resp = client.get("/")                                   # client didn't advertise gzip
    assert "Content-Encoding" not in resp.headers
    assert b"<!doctype html>" in resp.get_data().lower()


def test_small_json_is_not_gzipped(client):
    """A tiny response is left alone, because the compression headers would cost more bytes than they save and the CPU spent is pure waste."""
    resp = client.get("/health", headers=GZIP)
    assert "Content-Encoding" not in resp.headers


def test_static_png_is_not_gzipped_and_intact(client):
    """An already-compressed binary passes through untouched and still carries valid image magic bytes — re-compressing a streamed file is where corruption creeps in."""
    resp = client.get("/static/icon-192.png", headers=GZIP)
    assert resp.status_code == 200
    assert "Content-Encoding" not in resp.headers
    assert resp.get_data()[:8] == b"\x89PNG\r\n\x1a\n"        # valid PNG magic


def test_static_asset_is_cacheable(client):
    """Static assets carry a cache header, so a returning visitor does not re-download the icons and images on every page load."""
    resp = client.get("/static/icon-192.png")
    cc = resp.headers.get("Cache-Control", "")
    assert "max-age=86400" in cc and "public" in cc


def test_service_worker_stays_no_cache(client):
    """The service worker must revalidate on every load, or clients get permanently stuck on a stale app shell with no way to receive an update."""
    assert "no-cache" in client.get("/sw.js").headers.get("Cache-Control", "")


def test_served_shell_is_meaningfully_large(client):
    """The shell is large enough that compressing it is worth doing, which keeps the size threshold above meaningful.

    The floor is set at a level a real regression could actually cross — an earlier, far lower one would have needed almost the entire page to vanish before it could fail.
    """
    assert len(client.get("/").get_data()) > 100_000
