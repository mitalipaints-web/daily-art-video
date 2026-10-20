"""
Daily DIY miniature craft video generator.

Step 1: Claude invents a fresh craft idea (hook + ready-to-use video prompt),
        avoiding anything used before.
Step 2: A text-to-video model on Replicate turns the prompt into a video.

Output goes to ./output/YYYY-MM-DD/ with:
  - video.mp4     (the generated video)
  - prompt.json   (hook, title, description, tags, prompt: handy for uploading)

Setup:
  pip install anthropic replicate requests
  export ANTHROPIC_API_KEY=...
  export REPLICATE_API_TOKEN=...

Optional env vars:
  CLAUDE_MODEL        default: claude-sonnet-5-5
  VIDEO_MODEL         default: minimax/video-01 (any Replicate text-to-video model)
  VIDEO_EXTRA_INPUT   JSON of extra model inputs, e.g. '{"aspect_ratio": "9:16"}'
                      (input names differ per model; check the model's page)
  TELEGRAM_BOT_TOKEN  } if both are set, the video + hook/title/description/tags
  TELEGRAM_CHAT_ID    } are sent to your Telegram chat (so it lands on your phone)

Run daily with cron, e.g.:
  0 8 * * * cd /path/to/folder && /usr/bin/python3 daily_art_video.py
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

import anthropic
import replicate
import requests

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
VIDEO_MODEL = os.getenv("VIDEO_MODEL", "minimax/video-01")
VIDEO_EXTRA_INPUT = json.loads(os.getenv("VIDEO_EXTRA_INPUT") or "{}")

HISTORY_FILE = Path("history.json")
OUTPUT_DIR = Path("output")

STYLE_EXAMPLE = """Hook: "A tiny fairy home for your favorite rings."
Prompt: Create a whimsical yet realistic miniature DIY film of hands making a mushroom-inspired trinket dish. Sculpt a shallow mushroom-cap bowl with a short decorative stem, using a pale cream casting material. Smooth the rounded cap and paint it dusty rose with tiny ivory spots; add a cream stem and miniature sculpted moss details around the base. Keep the bowl functional and shallow enough for rings. Show close-ups of shaping, painting, dotting and finishing. Place the final piece in a miniature woodland-inspired setting with moss, tiny dried flowers and soft sunlight. Handmade cottagecore aesthetic, believable scale, detailed textures, vertical 9:16, no face, text or watermark."""

IDEA_SPACE = (
    "trinket dishes, mini food and bakery miniatures, tiny furniture and rooms, "
    "resin and clay charms, candles and wax melts, paper and book crafts, "
    "terrariums and mini gardens, embroidery and textile minis, jewelry and "
    "keepsakes, ceramics and pottery, woodworking minis, glass and light "
    "catchers, stationery and desk accessories, seasonal decor, "
    "pet-themed minis, cozy dioramas inside jars, bottles, boxes or eggshells"
)


def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return []


def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def generate_concept(history):
    """Ask Claude for today's craft video concept as JSON."""
    client = anthropic.Anthropic()
    recent = [
        {"theme": h["theme"], "craft": h.get("craft_type", ""), "material": h.get("material", "")}
        for h in history[-60:]
    ]

    system = (
        "You are the creative director of a YouTube Shorts channel of satisfying, "
        "whimsical, realistic miniature DIY craft films (hands making tiny, "
        "beautiful handmade objects). You invent original, specific, "
        "visually irresistible ideas. Respond with ONLY a JSON object: no "
        "preamble, no markdown fences."
    )
    user = f"""Today's date: {date.today().isoformat()} (lightly nod to the season or an upcoming occasion only when it feels natural).

Here is an example of the exact style and format of idea I want:
{STYLE_EXAMPLE}

Invent ONE brand-new idea in this style. Draw from areas like: {IDEA_SPACE}. Pick a craft type and material combination that differs from the recent ones below, and surprise me: unexpected objects, color palettes, settings and finishing touches. Each idea should have a clear, useful or charming end product and a "wow" final reveal in a miniature setting.

Recent ideas (do NOT repeat or closely resemble these themes, craft types or material combos):
{json.dumps(recent)}

Return JSON with these keys:
- "theme": short name of the idea (2-5 words, e.g. "Fairy Mushroom Dish")
- "craft_type": the category (e.g. "trinket dish")
- "material": main material (e.g. "casting resin")
- "hook": one punchy, curiosity-driven line for viewers, under 12 words
- "title": catchy YouTube title under 70 characters
- "description": 2-3 sentence YouTube description
- "tags": list of 8-12 relevant tags
- "video_prompt": a ready-to-use prompt in the same structure and tone as the example: what is being made, materials and colors, key process close-ups (shaping, painting, detailing, finishing), the final reveal in a miniature setting, aesthetic, believable scale, detailed textures, and ending with "vertical 9:16, no face, text or watermark". Under 170 words."""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def save_video(output, path):
    """Replicate returns a FileOutput, a URL string, or a list of either."""
    if isinstance(output, (list, tuple)):
        output = output[0]
    if hasattr(output, "read"):
        path.write_bytes(output.read())
    else:
        resp = requests.get(str(output), timeout=300)
        resp.raise_for_status()
        path.write_bytes(resp.content)


def send_to_telegram(video_path, concept):
    """Send the video, then the upload details, to your Telegram chat."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram not configured; skipping delivery.")
        return
    base = f"https://api.telegram.org/bot{token}"

    with open(video_path, "rb") as f:
        r = requests.post(
            f"{base}/sendVideo",
            data={"chat_id": chat_id, "caption": concept["theme"][:1000], "supports_streaming": True},
            files={"video": f},
            timeout=300,
        )
    r.raise_for_status()

    details = (
        f"Hook: {concept['hook']}\n\n"
        f"Title: {concept['title']}\n\n"
        f"Description: {concept['description']}\n\n"
        f"Tags: {', '.join(concept['tags'])}"
    )
    r = requests.post(f"{base}/sendMessage", data={"chat_id": chat_id, "text": details[:4000]}, timeout=60)
    r.raise_for_status()
    print("Sent to Telegram.")


def main():
    history = load_history()

    print("Generating today's idea...")
    concept = generate_concept(history)
    print(f"Theme: {concept['theme']}\nHook: {concept['hook']}\nTitle: {concept['title']}")

    out_dir = OUTPUT_DIR / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompt.json").write_text(json.dumps(concept, indent=2))

    print(f"Generating video with {VIDEO_MODEL} (this can take a few minutes)...")
    model_input = {"prompt": concept["video_prompt"], **VIDEO_EXTRA_INPUT}
    output = replicate.run(VIDEO_MODEL, input=model_input)
    save_video(output, out_dir / "video.mp4")
    send_to_telegram(out_dir / "video.mp4", concept)

    history.append({
        "date": date.today().isoformat(),
        "theme": concept["theme"],
        "craft_type": concept.get("craft_type", ""),
        "material": concept.get("material", ""),
    })
    save_history(history)
    print(f"Done. Saved to {out_dir}/")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Failed: {e}", file=sys.stderr)
        sys.exit(1)
