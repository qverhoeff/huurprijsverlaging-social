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
import time
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


# ── Token ophalen ──────────────────────────────────────────────────────────────

def get_page_token(token: str) -> str:
    """
    Haal een geldige Page token op.
    Probeert eerst de token direct te gebruiken als Page token.
    Als dat mislukt, wisselt het een korte User token in voor een lange,
    en haalt daar een permanente Page token uit.
    """
    # Probeer direct een Page token te halen (werkt als het een (lange) User token is)
    resp = requests.get(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}",
        params={"fields": "access_token", "access_token": token},
    )
    if resp.ok and "access_token" in resp.json():
        print("  Page token verkregen (direct).")
        return resp.json()["access_token"]

    # Fallback: wissel korte User token in voor lange, dan Page token
    print("  Directe uitwisseling mislukt, probeer via lange token...")
    exchange = requests.get(
        "https://graph.facebook.com/v19.0/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": FB_APP_ID,
            "client_secret": FB_APP_SECRET,
            "fb_exchange_token": token,
        },
    )
    exchange.raise_for_status()
    long_token = exchange.json()["access_token"]

    resp2 = requests.get(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}",
        params={"fields": "access_token", "access_token": long_token},
    )
    resp2.raise_for_status()
    page_token = resp2.json().get("access_token", long_token)
    print("  Permanente Page token verkregen.")
    return page_token


# ── Post selectie ──────────────────────────────────────────────────────────────

def load_posts() -> list:
    with open(SCRIPT_DIR / "posts.json") as f:
        return json.load(f)


def pick_post(posts: list) -> dict:
    """
    Kies een post op basis van het GitHub run-nummer (GITHUB_RUN_NUMBER).
    Elke run krijgt zo automatisch een andere post, nooit dubbel.
    Fallback op datum als het script lokaal wordt gedraaid.
    """
    run_number = int(os.environ.get("GITHUB_RUN_NUMBER", 0))
    if run_number > 0:
        index = run_number % len(posts)
        print(f"  Post #{run_number} → afbeelding {index + 1}/{len(posts)}")
        return posts[index]

    # Lokale fallback op datum
    today = date.today()
    day_offset = {0: 0, 2: 1, 4: 2}.get(today.weekday(), 0)
    week_number = int(today.strftime("%Y%V"))
    index = (week_number * 3 + day_offset) % len(posts)
    return posts[index]


# ── Afbeelding helpers ─────────────────────────────────────────────────────────

def make_feed_image(image_path: Path) -> Path:
    """Zet vierkante afbeelding om naar 4:5 (1080x1350) voor Instagram feed."""
    img = Image.open(image_path).convert("RGB")
    canvas = Image.new("RGB", (1080, 1350), (27, 60, 140))  # merkblauw onderaan
    # Afbeelding past precies breed, centreer verticaal iets naar boven
    img = img.resize((1080, 1080), Image.LANCZOS)
    canvas.paste(img, (0, 0))
    out = Path(tempfile.mktemp(suffix=".jpg"))
    canvas.save(out, "JPEG", quality=92)
    return out


def make_story_image(image_path: Path) -> Path:
    """Zet vierkante afbeelding om naar 9:16 (1080x1920) voor Stories."""
    img = Image.open(image_path).convert("RGB")
    img.thumbnail((1050, 1050), Image.LANCZOS)
    canvas = Image.new("RGB", (1080, 1920), (27, 60, 140))
    x = (1080 - img.width) // 2
    y = (1920 - img.height) // 2 - 60
    canvas.paste(img, (x, y))
    out = Path(tempfile.mktemp(suffix=".jpg"))
    canvas.save(out, "JPEG", quality=92)
    return out


def upload_to_facebook_cdn(image_path: Path, filename: str) -> tuple[str, str]:
    """Upload afbeelding naar Facebook (unpublished). Geeft (photo_id, public_url)."""
    image_bytes = image_path.read_bytes()
    resp = requests.post(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos",
        data={"access_token": FB_PAGE_ACCESS_TOKEN, "published": "false"},
        files={"source": (filename, image_bytes, "image/jpeg")},
    )
    resp.raise_for_status()
    photo_id = resp.json()["id"]

    url_resp = requests.get(
        f"https://graph.facebook.com/v19.0/{photo_id}",
        params={"fields": "images", "access_token": FB_PAGE_ACCESS_TOKEN},
    )
    url_resp.raise_for_status()
    images = url_resp.json().get("images", [])
    if not images:
        raise RuntimeError("Kon publieke afbeeldings-URL niet ophalen")
    return photo_id, images[0]["source"]


# ── Facebook ───────────────────────────────────────────────────────────────────

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


def post_to_facebook_story(public_url: str) -> str:
    resp = requests.post(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photo_stories",
        data={"url": public_url, "access_token": FB_PAGE_ACCESS_TOKEN},
    )
    resp.raise_for_status()
    return resp.json().get("post_id", resp.json().get("id", "ok"))


# ── Instagram ──────────────────────────────────────────────────────────────────

def wait_for_container(container_id: str, max_attempts: int = 12) -> None:
    for _ in range(max_attempts):
        resp = requests.get(
            f"https://graph.facebook.com/v19.0/{container_id}",
            params={"fields": "status_code", "access_token": FB_PAGE_ACCESS_TOKEN},
        )
        resp.raise_for_status()
        status = resp.json().get("status_code", "")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Instagram container fout: {resp.json()}")
        print(f"  Verwerken ({status})... wacht 5s")
        time.sleep(5)
    raise RuntimeError("Instagram container niet klaar na maximale wachttijd")


def post_to_instagram(image_url: str, caption: str, hashtags: str, media_type: str = "IMAGE") -> str:
    full_caption = f"{caption}\n\n{hashtags}\n\n{WEBSITE_URL}"
    payload = {"image_url": image_url, "access_token": FB_PAGE_ACCESS_TOKEN}
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
    wait_for_container(container_id)

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

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
    print(f"  Afbeelding : {post['image']}")
    print(f"  Caption    : {post['caption'][:80]}...")

    if dry_run:
        print(f"\n[DRY RUN] Zou posten: {post['image']}")
        print(f"  Caption  : {post['caption']}")
        print(f"  Hashtags : {post['hashtags']}")
        return

    # Maak formaat-varianten
    feed_path  = make_feed_image(image_path)   # 1080x1350 (4:5) voor Instagram feed
    story_path = make_story_image(image_path)  # 1080x1920 (9:16) voor Stories

    # Upload origineel voor Facebook feed
    print("Uploaden voor Facebook...")
    fb_photo_id, fb_public_url = upload_to_facebook_cdn(image_path, post["image"])

    # Upload feed-versie voor Instagram feed
    print("Uploaden voor Instagram feed (4:5)...")
    _, feed_url = upload_to_facebook_cdn(feed_path, "feed.jpg")
    feed_path.unlink(missing_ok=True)

    # Upload story-versie voor Stories
    print("Uploaden voor Stories (9:16)...")
    _, story_url = upload_to_facebook_cdn(story_path, "story.jpg")
    story_path.unlink(missing_ok=True)

    # Facebook feed
    print("Posten op Facebook feed...")
    fb_id = post_to_facebook_feed(post["caption"], post["hashtags"], fb_photo_id)
    print(f"  Facebook feed: {fb_id}")

    # Facebook Story
    print("Posten op Facebook Story...")
    try:
        post_to_facebook_story(fb_public_url)
        print("  Facebook Story: gelukt")
    except Exception as e:
        print(f"  Facebook Story mislukt (niet kritiek): {e}")

    # Instagram feed (4:5)
    print("Posten op Instagram feed...")
    ig_id = post_to_instagram(feed_url, post["caption"], post["hashtags"])
    print(f"  Instagram feed: {ig_id}")

    # Instagram Story (9:16)
    print("Posten op Instagram Story...")
    try:
        ig_story_id = post_to_instagram(story_url, post["caption"], post["hashtags"], media_type="STORIES")
        print(f"  Instagram Story: {ig_story_id}")
    except Exception as e:
        print(f"  Instagram Story mislukt (niet kritiek): {e}")

    print("\nKlaar!")


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    run(dry_run=dry)
