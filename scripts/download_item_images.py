from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
TARGET_DIR = ROOT_DIR / "assets" / "uploads" / "items"

IMAGE_SOURCES = {
    "ps5-cover.jpg": "https://images.pexels.com/photos/10997583/pexels-photo-10997583.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=1200&w=1600",
    "ps5-gallery-1.jpg": "https://images.pexels.com/photos/10997580/pexels-photo-10997580.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=1200&w=1600",
    "switch-cover.jpg": "https://images.pexels.com/photos/5801558/pexels-photo-5801558.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=1200&w=1600",
    "switch-gallery-1.jpg": "https://images.pexels.com/photos/5801559/pexels-photo-5801559.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=1200&w=1600",
    "projector-cover.jpg": "https://images.pexels.com/photos/31726722/pexels-photo-31726722.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=1200&w=1600",
    "projector-gallery-1.jpg": "https://images.pexels.com/photos/31726758/pexels-photo-31726758.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=1200&w=1600",
    "vacuum-cover.jpg": "https://images.pexels.com/photos/12167650/pexels-photo-12167650.jpeg?cs=srgb&dl=pexels-vedat-oncelik-154216015-12167650.jpg&fm=jpg",
    "vacuum-gallery-1.jpg": "https://images.pexels.com/photos/4401538/pexels-photo-4401538.jpeg?cs=srgb&dl=pexels-alonssus-4401538.jpg&fm=jpg",
    "drill-cover.jpg": "https://images.pexels.com/photos/3877525/pexels-photo-3877525.jpeg?cs=srgb&dl=pexels-caleboquendo-3877525.jpg&fm=jpg",
    "drill-gallery-1.jpg": "https://images.pexels.com/photos/5974382/pexels-photo-5974382.jpeg?cs=srgb&dl=pexels-ono-kosuki-5974382.jpg&fm=jpg",
    "home-cover.jpg": "https://images.unsplash.com/photo-1731360049272-d1439bace595?fm=jpg&ixid=M3wxMjA3fDB8MHxzZWFyY2h8M3x8ZHlzb24lMjBmYW58ZW58MHx8MHx8fDA%3D&ixlib=rb-4.1.0&q=80&w=1600",
    "home-gallery-1.jpg": "https://images.unsplash.com/photo-1731360049272-d1439bace595?fm=jpg&ixid=M3wxMjA3fDB8MHxzZWFyY2h8M3x8ZHlzb24lMjBmYW58ZW58MHx8MHx8fDA%3D&ixlib=rb-4.1.0&q=80&w=1600",
}


def download_file(file_name: str, url: str) -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    destination = TARGET_DIR / file_name
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; CodexDevSeeder/1.0)",
        },
    )
    with urlopen(request, timeout=30) as response:
        destination.write_bytes(response.read())


def main() -> None:
    for file_name, url in IMAGE_SOURCES.items():
        download_file(file_name, url)
        print(f"Downloaded {file_name}")

    print(f"Saved {len(IMAGE_SOURCES)} files to {TARGET_DIR}")


if __name__ == "__main__":
    main()
