"""
Huurprijsverlaging.com — Automatische social media poster
Post 3x per week (ma/wo/vr om 09:00) op Facebook en Instagram

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


def load_posts() -> list:
    with open(SCRIPT_DIR / "posts.json") as f:
        return json.load(f)


def pick_post(posts: list) -> dict:
    """Kies een post op basis van de datum zodat elke post-dag een andere afbeelding krijgt."""
    today = date.today()
    # Bepaal een volgnummer: elke ma/wo/vr telt als 1 post
    # Weekdag index: ma=0, wo=1, vr=2
    day_offset = {0: 0, 2: 1, 4: 2}.get(today.weekday(), 0)
    week_number = int(today.strftime("%Y%V"))
    post_number = week_number * 3 + day_offset
    index = post_number % len(posts)
    return posts[index]


def upload_photo_unpublished(image_bytes: bytes, filename: str) -> str:
    resp = requests.post(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos",
        data={"access_token": FB_PAGE_ACCESS_TOKEN, "published": "false"},
        files={"source": (filename, image_bytes, "image/jpeg")},
    )
    resp.raise_for_status()
    return resp.json()["id"]


def post_to_facebook(caption: str, hashtags: str, image_bytes: bytes, filename: str) -> str:
    photo_id = upload_photo_unpublished(image_bytes, filename)
    full_text = f"{caption}\n\n{hashtags}\n\n🔗 {WEBSITE_URL}"
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


def post_to_instagram(caption: str, hashtags: str, image_bytes: bytes, filename: str) -> str:
    photo_id = upload_photo_unpublished(image_bytes, filename)
    photo_resp = requests.get(
        f"https://graph.facebook.com/v19.0/{photo_id}",
        params={"fields": "images", "access_token": FB_PAGE_ACCESS_TOKEN},
    )
    photo_resp.raise_for_status()
    images = photo_resp.json().get("images", [])
    if not images:
        raise RuntimeError("Kon afbeeldings-URL niet ophalen van Facebook")
    image_url = images[0]["source"]

    full_caption = f"{caption}\n\n{hashtags}\n\n🔗 {WEBSITE_URL}"

    container = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_BUSINESS_ACCOUNT}/media",
        data={"image_url": image_url, "caption": full_caption, "access_token": FB_PAGE_ACCESS_TOKEN},
    )
    container.raise_for_status()
    container_id = container.json()["id"]

    publish = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_BUSINESS_ACCOUNT}/media_publish",
        data={"creation_id": container_id, "access_token": FB_PAGE_ACCESS_TOKEN},
    )
    publish.raise_for_status()
    return publish.json()["id"]


def run(dry_run: bool = False):
    from datetime import datetime
    posts = load_posts()
    post = pick_post(posts)

    image_path = SCRIPT_DIR / "images" / post["image"]
    if not image_path.exists():
        raise FileNotFoundError(f"Afbeelding niet gevonden: {image_path}")

    image_bytes = image_path.read_bytes()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
    print(f"  Afbeelding : {post['image']}")
    print(f"  Caption    : {post['caption'][:80]}...")
    print(f"  Hashtags   : {post['hashtags']}")

    if dry_run:
        print(f"\n[DRY RUN] Zou posten met afbeelding: {post['image']}")
        print(f"[DRY RUN] Volledige caption:\n{post['caption']}\n{post['hashtags']}\n🔗 {WEBSITE_URL}")
        return

    print("Posten op Facebook...")
    fb_id = post_to_facebook(post["caption"], post["hashtags"], image_bytes, post["image"])
    print(f"  ✓ Facebook post ID: {fb_id}")

    print("Posten op Instagram...")
    ig_id = post_to_instagram(post["caption"], post["hashtags"], image_bytes, post["image"])
    print(f"  ✓ Instagram post ID: {ig_id}")

    print("Klaar!")


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    run(dry_run=dry)
