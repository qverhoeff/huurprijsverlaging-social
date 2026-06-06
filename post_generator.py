"""
Huurprijsverlaging.com — Automatische social media poster
Post 3x per week (ma/wo/vr om 09:00) op Facebook en Instagram
inclusief Stories op beide platforms.

Gebruik:
  python post_generator.py          # post vandaag
  python post_generator.py --dry    # preview zonder te posten
"""

import os
import sys
import json
import requests
from datetime import date
from pathlib import Path

FB_PAGE_ID           = os.environ["FB_PAGE_ID"]
FB_PAGE_ACCESS_TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
IG_BUSINESS_ACCOUNT  = os.environ["IG_BUSINESS_ACCOUNT_ID"]
WEBSITE_URL          = "https://huurprijsverlaging.com"

SCRIPT_DIR = Path(__file__).parent


def get_page_token(token: str) -> str:
    """Wissel een User token automatisch in voor een Page token als dat nodig is."""
    resp = requests.get(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}",
        params={"fields": "access_token", "access_token": token},
    )
    data = resp.json()
    if resp.ok and "access_token" in data:
        return data["access_token"]
    # Token was al een Page token of uitwisseling niet mogelijk
    return token


def load_posts() -> list:
    with open(SCRIPT_DIR / "posts.json") as f:
        return json.load(f)


def pick_post(posts: list) -> dict:
    today = date.today()
    day_offset = {0: 0, 2: 1, 4: 2}.get(today.weekday(), 0)
    week_number = int(today.strftime("%Y%V"))
    post_number = week_number * 3 + day_offset
    return posts[post_number % len(posts)]


# ── Upload hulpfunctie ─────────────────────────────────────────────────────────

def upload_photo_unpublished(image_bytes: bytes, filename: str) -> tuple[str, str]:
    """Upload afbeelding naar Facebook. Geeft (photo_id, public_url) terug."""
    resp = requests.post(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos",
        data={"access_token": FB_PAGE_ACCESS_TOKEN, "published": "false"},
        files={"source": (filename, image_bytes, "image/jpeg")},
    )
    resp.raise_for_status()
    photo_id = resp.json()["id"]

    # Haal publieke URL op (nodig voor Instagram en Stories)
    url_resp = requests.get(
        f"https://graph.facebook.com/v19.0/{photo_id}",
        params={"fields": "images", "access_token": FB_PAGE_ACCESS_TOKEN},
    )
    url_resp.raise_for_status()
    images = url_resp.json().get("images", [])
    if not images:
        raise RuntimeError("Kon publieke afbeeldings-URL niet ophalen")
    public_url = images[0]["source"]

    return photo_id, public_url


# ── Facebook feed ──────────────────────────────────────────────────────────────

def post_to_facebook_feed(caption: str, hashtags: str, photo_id: str) -> str:
    full_text = f"{caption}\n\n{hashtags}\n\n{WEBSITE_URL}"
    resp = requests.post(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed",
        data={
            "message": full_text,
            "attached_media[0]": json.dumps({"media_fbid": photo_id}),
            "access_token": FB_PAGE_ACCESS_TOKEN,
        },
    )
    resp.raise_for_status()
    return resp.json()["id"]


# ── Facebook Story ─────────────────────────────────────────────────────────────

def post_to_facebook_story(public_url: str) -> str:
    resp = requests.post(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photo_stories",
        data={
            "url": public_url,
            "access_token": FB_PAGE_ACCESS_TOKEN,
        },
    )
    resp.raise_for_status()
    return resp.json().get("post_id", resp.json().get("id", "ok"))


# ── Instagram feed ─────────────────────────────────────────────────────────────

def post_to_instagram(caption: str, hashtags: str, image_filename: str, media_type: str = "IMAGE") -> str:
    # Gebruik de publieke GitHub raw URL — altijd toegankelijk voor Instagram
    github_url = f"https://raw.githubusercontent.com/qverhoeff/huurprijsverlaging-social/main/images/{image_filename}"
    full_caption = f"{caption}\n\n{hashtags}\n\n{WEBSITE_URL}"

    payload = {
        "image_url": github_url,
        "access_token": FB_PAGE_ACCESS_TOKEN,
    }
    if media_type == "STORIES":
        payload["media_type"] = "STORIES"
    else:
        payload["caption"] = full_caption

    container = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_BUSINESS_ACCOUNT}/media",
        data=payload,
    )
    container.raise_for_status()
    container_id = container.json()["id"]

    publish = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_BUSINESS_ACCOUNT}/media_publish",
        data={"creation_id": container_id, "access_token": FB_PAGE_ACCESS_TOKEN},
    )
    publish.raise_for_status()
    return publish.json()["id"]


# ── Hoofd flow ─────────────────────────────────────────────────────────────────

def run(dry_run: bool = False):
    global FB_PAGE_ACCESS_TOKEN
    from datetime import datetime

    print("Token ophalen...")
    FB_PAGE_ACCESS_TOKEN = get_page_token(FB_PAGE_ACCESS_TOKEN)

    posts = load_posts()
    post = pick_post(posts)

    image_path = SCRIPT_DIR / "images" / post["image"]
    if not image_path.exists():
        raise FileNotFoundError(f"Afbeelding niet gevonden: {image_path}")

    image_bytes = image_path.read_bytes()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
    print(f"  Afbeelding : {post['image']}")
    print(f"  Caption    : {post['caption'][:80]}...")

    if dry_run:
        print(f"\n[DRY RUN] Zou posten:")
        print(f"  Afbeelding : {post['image']}")
        print(f"  Caption    : {post['caption']}")
        print(f"  Hashtags   : {post['hashtags']}")
        print(f"  Link       : {WEBSITE_URL}")
        print(f"  Platforms  : Facebook feed + Story / Instagram feed + Story")
        return

    print("Uploaden afbeelding...")
    photo_id, public_url = upload_photo_unpublished(image_bytes, post["image"])
    print(f"  Photo ID : {photo_id}")

    print("Posten op Facebook feed...")
    fb_id = post_to_facebook_feed(post["caption"], post["hashtags"], photo_id)
    print(f"  Facebook feed ID: {fb_id}")

    print("Posten op Facebook Story...")
    try:
        fb_story_id = post_to_facebook_story(public_url)
        print(f"  Facebook Story ID: {fb_story_id}")
    except Exception as e:
        print(f"  Facebook Story mislukt (niet kritiek): {e}")

    print("Posten op Instagram feed...")
    ig_id = post_to_instagram(post["caption"], post["hashtags"], post["image"])
    print(f"  ✓ Instagram feed ID: {ig_id}")

    print("Posten op Instagram Story...")
    try:
        ig_story_id = post_to_instagram(post["caption"], post["hashtags"], post["image"], media_type="STORIES")
        print(f"  ✓ Instagram Story ID: {ig_story_id}")
    except Exception as e:
        print(f"  Instagram Story mislukt (niet kritiek): {e}")

    print("\nKlaar! Gepost op: Facebook feed + Story / Instagram feed + Story")


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    run(dry_run=dry)
