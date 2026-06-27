"""Client for the internal AI container (`POST {AI_URL}/predict`). OWNER: web side (Shiri/Elad).

Wraps the call so routes don't speak HTTP directly. Use `requests` (in requirements.txt).
Fault tolerance (mandatory — docs/DESIGN.md §5): on AI failure, degrade gracefully — never crash.
"""


def predict(ai_url, features, timeout=5):
    """POST `features` to `{ai_url}/predict` and return the parsed result. OWNER: implement."""
    raise NotImplementedError("ai_client.predict — call the ai container and return its JSON")
