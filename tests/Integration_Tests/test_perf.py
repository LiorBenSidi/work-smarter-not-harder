"""Integration tests for the response-perf layer: gzip + static-asset caching. OWNER: Lior.

These pin the wire-level optimizations (course L7) so a regression is caught in CI: the SPA shell is
gzipped and round-trips intact, gzip self-skips when it shouldn't apply (no Accept-Encoding, tiny bodies,
binary files), and the static assets carry a cacheable header while the service worker stays no-cache.
"""
import gzip

GZIP = {"Accept-Encoding": "gzip"}


def test_index_is_gzipped_and_roundtrips(client):
    plain = client.get("/").get_data()                       # no Accept-Encoding -> uncompressed
    resp = client.get("/", headers=GZIP)
    assert resp.headers.get("Content-Encoding") == "gzip"
    assert "Accept-Encoding" in resp.headers.get("Vary", "")
    assert gzip.decompress(resp.get_data()) == plain         # lossless
    assert len(resp.get_data()) < len(plain)                 # and actually smaller


def test_index_not_gzipped_without_accept_encoding(client):
    resp = client.get("/")                                   # client didn't advertise gzip
    assert "Content-Encoding" not in resp.headers
    assert b"<!doctype html>" in resp.get_data().lower()


def test_small_json_is_not_gzipped(client):
    # /health is well under the header-overhead threshold -> compressing it would waste CPU + bytes.
    resp = client.get("/health", headers=GZIP)
    assert "Content-Encoding" not in resp.headers


def test_static_png_is_not_gzipped_and_intact(client):
    # a binary, streamed (direct_passthrough) file must pass through untouched -> no corruption.
    resp = client.get("/static/icon-192.png", headers=GZIP)
    assert resp.status_code == 200
    assert "Content-Encoding" not in resp.headers
    assert resp.get_data()[:8] == b"\x89PNG\r\n\x1a\n"        # valid PNG magic


def test_static_asset_is_cacheable(client):
    resp = client.get("/static/icon-192.png")
    cc = resp.headers.get("Cache-Control", "")
    assert "max-age=86400" in cc and "public" in cc


def test_service_worker_stays_no_cache(client):
    # the SW must revalidate every load or clients get stuck on a stale app shell.
    assert "no-cache" in client.get("/sw.js").headers.get("Cache-Control", "")


def test_served_shell_is_meaningfully_large(client):
    # sanity: the shell is big enough that gzip is worth it (guards the threshold staying relevant).
    # 100k, not 10k: the served shell is ~285 KB, so a 10k floor needed ~96% of the SPA to vanish
    # before it could fail — a threshold no plausible regression could trip.
    assert len(client.get("/").get_data()) > 100_000
