"""
PaidUp — Flask application entry point.
"""

import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template, request, jsonify, send_file, redirect
from app.parliament import (
    search_mp, get_interests, get_biography,
    parse_interests, date_range, parse_biography, deduplicate_donors,
)
from app.card import generate_card, generate_mobile_card, get_badge_layout
import app.r2 as r2
from app.ai import analyze, prompt_options, get_prompt_version
from app.theyworkforyou import get_mp_data as get_twfy_data
import app.cache as cache
import app.database as db
import io

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")

# Create DB tables on startup (no-op if DATABASE_URL not set)
db.ensure_tables()


_mp_list_cache: list[dict] | None = None


def _get_deduped_interests(member_id: int) -> list[dict]:
    """Return deduplicated parsed interests, using Redis cache if available."""
    ck = cache.make_key("interests", str(member_id))
    hit = cache.get(ck)
    if hit is not None:
        return hit
    result = deduplicate_donors(parse_interests(get_interests(member_id)))
    cache.set(ck, result, ttl=cache.LOOKUP_TTL)
    return result


def _get_mp_list() -> list[dict]:
    global _mp_list_cache
    if _mp_list_cache is not None:
        return _mp_list_cache
    import requests as _req
    mps, skip = [], 0
    while True:
        data = _req.get(
            "https://members-api.parliament.uk/api/Members/Search",
            params={"House": 1, "IsCurrentMember": "true", "take": 100, "skip": skip},
            timeout=10,
        ).json()
        items = data.get("items", [])
        if not items:
            break
        for m in items:
            v = m["value"]
            mps.append({"id": v["id"], "name": v["nameDisplayAs"], "party": v["latestParty"]["name"]})
        skip += len(items)
        if skip >= data.get("totalResults", 0):
            break
    _mp_list_cache = mps
    return mps


@app.route("/members")
def members():
    return jsonify(_get_mp_list())


@app.route("/")
def index():
    return render_template("index.html", prompt_options=prompt_options())


@app.route("/lookup", methods=["POST"])
def lookup():
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "No name provided"}), 400

    # L1: Redis
    ck = cache.make_key("lookup", name)
    cached = cache.get(ck)
    if cached:
        cached["_cached"] = "redis"
        return jsonify(cached)

    # Fetch from Parliament APIs
    mp = search_mp(name)
    if not mp:
        return jsonify({"error": f"No MP found for '{name}'"}), 404

    member_id = mp["id"]
    mp_name = mp["nameDisplayAs"]

    # Fetch interests, biography, and TWFY data in parallel — all only need member_id / mp_name
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_interests = pool.submit(get_interests, member_id)
        f_bio = pool.submit(get_biography, member_id)
        f_twfy = pool.submit(get_twfy_data, mp_name)
        raw_interests = f_interests.result()
        bio_raw = f_bio.result()
        twfy = f_twfy.result()

    deduped = deduplicate_donors(parse_interests(raw_interests))
    cache.set(cache.make_key("interests", str(member_id)), deduped, ttl=cache.LOOKUP_TTL)
    interests = db.apply_donor_tags(deduped)
    total = sum(i["value"] for i in interests)
    oldest, newest = date_range(interests)

    bio_data = parse_biography(bio_raw)

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
    version = get_prompt_version(prompt_key)

    # L1: Redis (hot, short-lived)
    ck = cache.make_key("analyze", str(member_id or ""), prompt_key, str(version))
    cached = cache.get(ck)
    if cached:
        cached["_cached"] = "redis"
        return jsonify(cached)

    # L2: PostgreSQL (persistent, 28-day TTL)
    if member_id:
        stored = db.get_analysis(member_id, prompt_key, version)
        if stored:
            result = {"result": stored, "_cached": "db"}
            # Repopulate Redis so the next request doesn't hit Postgres
            cache.set(ck, {"result": stored}, ttl=cache.ANALYSIS_TTL)
            return jsonify(result)

    # Origin: Claude API
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
            db.save_analysis(member_id, prompt_key, version, text)
            cache.set(ck, result, ttl=cache.ANALYSIS_TTL)

        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        msg = str(e)
        if "401" in msg or "authentication" in msg.lower() or "invalid x-api-key" in msg.lower():
            return jsonify({"error": "AI analysis is unavailable — API key not configured correctly."}), 503
        return jsonify({"error": "AI analysis is temporarily unavailable. Please try again shortly."}), 500


@app.route("/card/<int:member_id>")
def card(member_id):
    mp_name = request.args.get("name", "")
    mp_party = request.args.get("party", "")
    mp_title = request.args.get("title", "")

    cached_url = r2.get_card_url(member_id)
    if cached_url:
        return redirect(cached_url)

    interests = _get_deduped_interests(member_id)
    oldest, newest = date_range(interests)
    img = generate_card(member_id, mp_name, interests, party=mp_party,
                        title=mp_title, date_from=oldest, date_to=newest)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    cdn_url = r2.upload_card(member_id, png_bytes)
    if cdn_url:
        return redirect(cdn_url)

    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/card/<int:member_id>/mobile")
def card_mobile(member_id):
    mp_name  = request.args.get("name", "")
    mp_party = request.args.get("party", "")
    mp_title = request.args.get("title", "")

    cached_url = r2.get_card_url(member_id, variant="mobile")
    if cached_url:
        return redirect(cached_url)

    interests = _get_deduped_interests(member_id)
    oldest, newest = date_range(interests)
    img = generate_mobile_card(member_id, mp_name, interests, party=mp_party,
                               title=mp_title, date_from=oldest, date_to=newest)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    cdn_url = r2.upload_card(member_id, png_bytes, variant="mobile")
    if cdn_url:
        return redirect(cdn_url)

    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/card/<int:member_id>/badges")
def card_badges(member_id):
    interests = _get_deduped_interests(member_id)
    return jsonify(get_badge_layout(interests, member_id))


@app.route("/health")
def health():
    redis_ok = cache._get() is not None
    db_ok = db._get_pool() is not None
    return jsonify({
        "status": "ok",
        "redis": redis_ok,
        "db": db_ok,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    app.run(host="0.0.0.0", debug=False, port=port)
