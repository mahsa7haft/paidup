"""
fake_upstream.py — a fake stand-in for EVERY external service PaidUp calls.

Run this, point PaidUp's base-URL env vars at it, and the app talks only to
localhost: no real Claude (no cost), no real Parliament/TWFY traffic.

One Flask app serves all of them because the paths don't collide:
  Parliament Members  →  /Members/Search,  /Members/<id>/Biography
  Parliament Interests→  /Interests
  TheyWorkForYou      →  /getMP,  /getMPInfo
  Anthropic (SDK)     →  /v1/messages

Two chaos knobs (env vars) let you make it misbehave so you can watch PaidUp's
resilience react — especially the Anthropic circuit breaker:

  FAKE_LATENCY_MS   delay every response by this many ms     (default 0)
  FAKE_FAIL_RATE    fraction of requests to fail with HTTP 500 (default 0.0)

Start it (port 9100):
  FAKE_FAIL_RATE=0.5 uv run python loadtest/fake_upstream.py

Then run PaidUp pointed at it (see loadtest/README once we add it):
  MEMBERS_API=http://localhost:9100 \
  INTERESTS_API=http://localhost:9100 \
  TWFY_API_URL=http://localhost:9100 \
  ANTHROPIC_BASE_URL=http://localhost:9100 \
  THEYWORKFORYOU_API_KEY=fake ANTHROPIC_API_KEY=fake \
  PYTHONPATH=src uv run python -m app.main
"""

import os
import time
import random

from flask import Flask, jsonify

app = Flask(__name__)

LATENCY_MS = int(os.environ.get("FAKE_LATENCY_MS", "0"))
FAIL_RATE = float(os.environ.get("FAKE_FAIL_RATE", "0.0"))


def _maybe_chaos():
    """
    YOUR PART — the heart of the load test.

    Inject the two chaos behaviours before an endpoint returns its real data:

      1. Latency — sleep for LATENCY_MS milliseconds (simulate a SLOW dependency).
      2. Failure — with probability FAIL_RATE, fail the request with HTTP 500
                   (simulate a BROKEN dependency).

    Contract (how the endpoints below use it):
      - return a Flask response tuple  ->  the endpoint returns THAT (the failure)
      - return None                    ->  the endpoint proceeds with real data

    So the shape is:
        - do the latency sleep
        - roll the dice; on a "fail", return something like
              (jsonify({"error": "fake upstream failure"}), 500)
        - otherwise return None

    Hints:
      - time.sleep() takes SECONDS, but LATENCY_MS is in milliseconds.
      - random.random() returns a float in [0.0, 1.0); compare it against FAIL_RATE.
    """

    time.sleep(LATENCY_MS / 1000.0)  # Convert milliseconds to seconds
    if random.random() < FAIL_RATE:
        return jsonify({"error": "fake upstream failure"}), 500
    else:
        return None


# ── Parliament Members API ────────────────────────────────────────────────────

@app.route("/Members/Search")
def members_search():
    chaos = _maybe_chaos()
    if chaos:
        return chaos
    # search_mp() reads items[0]["value"]; main.py then reads id / nameDisplayAs /
    # latestParty.name / memberFrom.
    return jsonify({
        "items": [{
            "value": {
                "id": 9999,
                "nameDisplayAs": "Test MP",
                "latestParty": {"name": "Test Party"},
                "memberFrom": "Testville",
            }
        }]
    })


@app.route("/Members/<int:member_id>/Biography")
def members_biography(member_id):
    chaos = _maybe_chaos()
    if chaos:
        return chaos
    # parse_biography() tolerates an empty value dict.
    return jsonify({"value": {"committeeMemberships": [], "governmentPosts": [], "oppositionPosts": []}})


@app.route("/Members/<int:member_id>/Thumbnail")
def members_thumbnail(member_id):
    chaos = _maybe_chaos()
    if chaos:
        return chaos
    # 1x1 transparent GIF — enough to satisfy the card route; not used by /lookup.
    gif = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")
    return app.response_class(gif, mimetype="image/gif")


# ── Parliament Interests API ──────────────────────────────────────────────────

@app.route("/Interests")
def interests():
    chaos = _maybe_chaos()
    if chaos:
        return chaos
    # get_interests() reads items[]; parse_interests() reads fields[], category, etc.
    return jsonify({
        "items": [
            {
                "category": {"name": "Donations"},
                "summary": "Fake donation",
                "registrationDate": "2025-01-15T00:00:00",
                "fields": [
                    {"name": "DonorName", "value": "Fake Donor Ltd"},
                    {"name": "Value", "value": "12500"},
                ],
            },
            {
                "category": {"name": "Gifts"},
                "summary": "Fake hospitality",
                "registrationDate": "2025-02-20T00:00:00",
                "fields": [
                    {"name": "DonorName", "value": "Another Fake Donor"},
                    {"name": "Value", "value": "3000"},
                ],
            },
        ]
    })


# ── TheyWorkForYou API ────────────────────────────────────────────────────────

@app.route("/getMP")
def twfy_get_mp():
    chaos = _maybe_chaos()
    if chaos:
        return chaos
    return jsonify([{"person_id": "12345"}])


@app.route("/getMPInfo")
def twfy_get_mp_info():
    chaos = _maybe_chaos()
    if chaos:
        return chaos
    return jsonify({
        "votes_with_party_pct": "95.5",
        "rebellions": "3",
        "debates_count": "42",
        "office": [],
    })


# ── Anthropic Messages API ────────────────────────────────────────────────────

@app.route("/v1/messages", methods=["POST"])
def anthropic_messages():
    chaos = _maybe_chaos()
    if chaos:
        return chaos
    # Shape the Anthropic SDK expects from messages.create (non-streaming).
    return jsonify({
        "id": "msg_fake",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "content": [{"type": "text", "text": "## Fake analysis\n\nCanned text from the fake upstream."}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 60},
    })


@app.route("/health")
def health():
    return jsonify({"ok": True, "latency_ms": LATENCY_MS, "fail_rate": FAIL_RATE})


if __name__ == "__main__":
    print(f"fake_upstream on :9100  (latency={LATENCY_MS}ms, fail_rate={FAIL_RATE})")
    app.run(port=9100, threaded=True)
