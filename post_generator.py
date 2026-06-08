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
import tempfile
from datetime import date
from pathlib import Path
from PIL import Image

FB_PAGE_ID           = os.environ["FB_PAGE_ID"]
FB_PAGE_ACCESS_TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
FB_APP_ID            = "1548896920077303"
FB_APP_SECRET        = os.environ["FB_APP_SECRET"]
IG_BUSINESS_ACCOUNT  = os.environ["IG_BUSINESS_ACCOUNT_ID"]
WEBSITE_URL          = "https://huurprijsverlaging.com"

SCRIPT_DIR = Path(__file__).parent


def get_page_token(short_token: str) -> str:
    """
    Zet een korte User token om naar een nooit-verlopende Page token:
    1. Korte User token → lange User token (60 dagen)
    2. Lange User token → Page token (verloopt nooit)
    """
    # Stap 1: wissel in voor een lange User token
    resp = requests.get(
        "https://graph.facebook.com/v19.0/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": FB_APP_ID,
            "client_secret": FB_APP_SECRET,
            "fb_exchange_token": short_token,
        },
    )
    resp.raise_for_status()
    long_token = resp.json()["access_token"]
    print("  Lange User token verkregen.")

    # Stap 2: wissel in voor een Page token (verloopt nooit)
    resp2 = requests.get(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}",
        params={"fields": "access_token", "access_token": long_token},
    )
    resp2.raise_for_status()
    page_token = resp2.json().get("access_token", long_token)
    print("  Permanente Page token verkregen.")
    return page_token


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

def make_story_image(image_path: Path) -> Path:
    """
    Zet een vierkante afbeelding om naar 1080x1920 (9:16) voor Stories.
    De afbeelding staat gecentreerd op een donkere achtergrond met het logo eronder.
    """
    square = Image.open(image_path).convert("RGB")
    story_w, story_h = 1080, 1920
    canvas = Image.new("RGB", (story_w, story_h), (27, 60, 140))  # merkblauw

    # Afbeelding iets verkleinen zodat er ruimte is boven en onder
    max_size = 1050
    square.thumbnail((max_size, max_size), Image.LANCZOS)

    # Centreer de afbeelding verticaal iets boven het midden
    x = (story_w - square.width) // 2
    y = (story_h - square.height) // 2 - 60
    canvas.paste(square, (x, y))

    out_path = Path(tempfile.mktemp(suffix=".jpg"))
    canvas.save(out_path, "JPEG", quality=92)
    return out_path


def upload_story_image_to_cdn(story_image_path: Path) -> str:
    """Upload story-afbeelding naar Facebook en geef de publieke URL terug."""
    image_bytes = story_image_path.read_bytes()
    resp = requests.post(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos",
        data={"access_token": FB_PAGE_ACCESS_TOKEN, "published": "false"},
        files={"source": ("story.jpg", image_bytes, "image/jpeg")},
    )
    resp.raise_for_status()
    photo_id = resp.json()["id"]

    url_resp = requests.get(
        f"https://graph.facebook.com/v19.0/{photo_id}",
        params={"fields": "images", "access_token": FB_PAGE_ACCESS_TOKEN},
    )
    url_resp.raise_for_status()
    images = url_resp.json().get("images", [])
    return images[0]["source"] if images else None


def wait_for_instagram_container(container_id: str, max_attempts: int = 10) -> None:
    """Wacht tot Instagram klaar is met de afbeelding verwerken."""
    import time
    for attempt in range(max_attempts):
        resp = requests.get(
            f"https://graph.facebook.com/v19.0/{container_id}",
            params={"fields": "status_code,status", "access_token": FB_PAGE_ACCESS_TOKEN},
        )
        resp.raise_for_status()
        status = resp.json().get("status_code", "")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Instagram container in ERROR staat: {resp.json()}")
        print(f"  Instagram verwerkt afbeelding ({status})... wacht 5 seconden")
        time.sleep(5)
    raise RuntimeError("Instagram container niet klaar na maximale wachttijd")


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

    # Wacht tot Instagram de afbeelding heeft verwerkt
    wait_for_instagram_container(container_id)

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
        story_path = make_story_image(image_path)
        story_url = upload_story_image_to_cdn(story_path)
        story_path.unlink(missing_ok=True)

        payload = {"image_url": story_url, "media_type": "STORIES", "access_token": FB_PAGE_ACCESS_TOKEN}
        container = requests.post(f"https://graph.facebook.com/v19.0/{IG_BUSINESS_ACCOUNT}/media", data=payload)
        container.raise_for_status()
        container_id = container.json()["id"]
        wait_for_instagram_container(container_id)
        publish = requests.post(
            f"https://graph.facebook.com/v19.0/{IG_BUSINESS_ACCOUNT}/media_publish",
            data={"creation_id": container_id, "access_token": FB_PAGE_ACCESS_TOKEN},
        )
        publish.raise_for_status()
        print(f"  ✓ Instagram Story ID: {publish.json()['id']}")
    except Exception as e:
        print(f"  Instagram Story mislukt (niet kritiek): {e}")

    print("\nKlaar! Gepost op: Facebook feed + Story / Instagram feed + Story")


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    run(dry_run=dry)
