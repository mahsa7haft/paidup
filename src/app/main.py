"""
PaidUp — Flask application entry point.
"""

import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from flask import Flask, render_template, request, jsonify, send_file
from app.parliament import (
    search_mp, get_interests, get_biography,
    parse_interests, date_range, parse_biography, deduplicate_donors,
)
from app.card import generate_card
from app.ai import analyze, prompt_options, get_prompt_version
from app.theyworkforyou import get_mp_data as get_twfy_data
import app.cache as cache
import io

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")


@app.route("/")
def index():
    return render_template("index.html", prompt_options=prompt_options())


@app.route("/lookup", methods=["POST"])
def lookup():
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "No name provided"}), 400

    # ── cache check ──────────────────────────────────────────────────────────
    ck = cache.make_key("lookup", name)
    cached = cache.get(ck)
    if cached:
        cached["_cached"] = True
        return jsonify(cached)

    # ── fetch ────────────────────────────────────────────────────────────────
    mp = search_mp(name)
    if not mp:
        return jsonify({"error": f"No MP found for '{name}'"}), 404

    member_id = mp["id"]
    mp_name = mp["nameDisplayAs"]

    interests = deduplicate_donors(parse_interests(get_interests(member_id)))
    total = sum(i["value"] for i in interests)
    oldest, newest = date_range(interests)

    bio_data = parse_biography(get_biography(member_id))
    twfy = get_twfy_data(mp_name)

    sources = {
        "parliament_member": f"https://members.parliament.uk/member/{member_id}",
        "interests_register": "https://interests-api.parliament.uk",
        "twfy_profile": twfy["twfy_url"] if twfy else None,
        "appg_register": "https://www.parliament.uk/mps-lords-and-offices/standards-and-financial-interests/all-party-parliamentary-groups/",
    }

    result = {
        "id": member_id,
        "name": mp_name,
        "party": mp["latestParty"]["name"],
        "constituency": mp.get("memberFrom", ""),
        "total": total,
        "count": len(interests),
        "oldest": oldest,
        "newest": newest,
        "committees": bio_data["committees"],
        "govt_posts": bio_data["govt_posts"],
        "opposition_posts": bio_data["opposition_posts"],
        "other_posts": bio_data["other_posts"],
        "party_history": bio_data["party_history"],
        "twfy": twfy,
        "interests": interests,
        "sources": sources,
    }

    cache.set(ck, result, ttl=cache.LOOKUP_TTL)
    return jsonify(result)


@app.route("/analyze", methods=["POST"])
def analyze_mp():
    data = request.get_json()
    if not data.get("name") or "interests" not in data:
        return jsonify({"error": "Missing required fields"}), 400

    prompt_key = data.get("prompt_key", "summary")
    member_id = data.get("id")

    # ── cache check ──────────────────────────────────────────────────────────
    # Include prompt version in key so editing a prompt file busts the cache.
    version = get_prompt_version(prompt_key)
    ck = cache.make_key("analyze", str(member_id or ""), prompt_key, str(version))
    cached = cache.get(ck)
    if cached:
        cached["_cached"] = True
        return jsonify(cached)

    # ── run analysis ─────────────────────────────────────────────────────────
    try:
        text = analyze(
            mp_name=data["name"],
            party=data.get("party", ""),
            constituency=data.get("constituency", ""),
            interests=data["interests"],
            committees=data.get("committees", []),
            twfy=data.get("twfy"),
            bio=data.get("bio", {}),
            prompt_key=prompt_key,
        )
        result = {"result": text}
        if member_id:
            cache.set(ck, result, ttl=cache.ANALYSIS_TTL)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"AI analysis failed: {e}"}), 500


@app.route("/card/<int:member_id>")
def card(member_id):
    mp_name = request.args.get("name", "")
    interests = deduplicate_donors(parse_interests(get_interests(member_id)))
    img = generate_card(member_id, mp_name, interests)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    app.run(host="0.0.0.0", debug=False, port=port)
