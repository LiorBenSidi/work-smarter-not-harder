"""Resolve an internal user HANDLE to the (non-unique) display name shown to people. OWNER: Lior.

Every collection keys on a stable, unique per-account handle; the display name is a separate,
non-unique field (two people can both be "Alex"). Routes store/compare handles for identity and
ownership, and call ``display_name`` only at the presentation edge so a handle never leaks to a
person. Best-effort: an unknown handle, a legacy account without a display name, or any store error
degrades to the handle itself, and it never raises.
"""
from flask import current_app


def display_name(handle):
    """The shown name for `handle` (falls back to the handle itself)."""
    if not handle:
        return handle
    try:
        user = current_app.config["USERS"].get(handle)
    except Exception:
        return handle
    return (user or {}).get("display_name") or handle


def display_names(handles):
    """Batch variant: ``{handle: shown name}`` for a set of handles (dedups; per-handle fallback).

    A convenience for list projections (a forum page, a conversation list) so a caller resolves a whole
    page of authors/peers in one comprehension instead of scattering lookups. Still one store ``get`` per
    distinct handle — fine at this app's scale; a true bulk fetch can replace it behind this same seam.
    """
    return {h: display_name(h) for h in set(handles) if h}
