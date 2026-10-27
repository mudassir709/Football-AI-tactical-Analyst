"""Crop the raw 1440x900 screenshots to their content for the document.

    python crop_screenshots.py   (writes figures/ss_*.png)
"""

from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
# name: (left, top, right, bottom) in screenshot pixels; None = keep whole image
CROPS = {
    "01_login": (470, 200, 970, 700),
    "02_login_error": (470, 200, 970, 700),
    "03_register": (470, 150, 970, 760),
    "04_matches": (140, 70, 1300, 700),
    "05_upload_empty": (360, 80, 1080, 640),
    "06_upload_invalid_file": (360, 80, 1080, 720),
    "07_upload_ready": (360, 80, 1080, 640),
    "08_match_in_progress": (140, 80, 1300, 345),
    "09_matches_live_progress": (140, 70, 1300, 700),
    "10_match_page": None,
    "16_player_selected": None,
    "20_match_failed": (140, 80, 1300, 260),
    "21_matches_failed_and_delete_confirm": (140, 70, 1300, 700),
}

for source in sorted((HERE / "screenshots").glob("*.png")):
    image = Image.open(source)
    box = CROPS.get(source.stem)
    if box:
        image = image.crop(box)
    image.save(HERE / "figures" / f"ss_{source.stem}.png")
    print(source.stem, image.size)
