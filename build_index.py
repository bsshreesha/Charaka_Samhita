"""Build/cache the repository JSON index before starting the Flask service."""
from charaka_backend.repository import build_index

if __name__ == "__main__":
    manifest = build_index(force=True)
    print(f"Indexed chapters: {manifest['chapter_count']}")
    print(f"Indexed passages: {manifest['passage_count']}")
    print(f"Failed chapters: {len(manifest['failed_chapters'])}")
    if manifest["failed_chapters"]:
        for item in manifest["failed_chapters"]:
            print(f"FAILED: {item['path']} :: {item['error']}")
