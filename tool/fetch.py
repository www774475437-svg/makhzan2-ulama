"""Runs on GitHub: keeps a full, compressed copy of the books of the scholars
named in scholars.txt, and publishes it as this store's site.

Each book is fetched from «تراث» once only (kept in bookcache/ between runs).
Nothing is lost by the compression: every file is plain gzip.

Output, in out/:
  hosted.json            [book ids]
  <id>/i.json.gz         {"headings", "page_map", "volumes", "count", "chunk", "pdf"}
  <id>/p<k>.json.gz      pages k*CHUNK+1 .. (k+1)*CHUNK as [[vol, page, text], ...]
  <id>/s.txt.gz          light text for searching, one page per line
"""
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CATALOG = "https://www774475437-svg.github.io/salafi-library/assets/assets/data/catalog.json"
CHUNK = 40
CACHE = Path("bookcache")
OUT = Path("out")
UA = {"User-Agent": "salafi-library-books/1.0"}
TIME_LIMIT = 4 * 60 * 60  # stop fetching after this; the rest come in the next run


def fetch(url, tries=8):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if i == tries - 1 or e.code not in (429, 500, 502, 503, 504):
                raise
            wait = int(e.headers.get("Retry-After") or 0) or (10 + i * 10)
            print("  wait", wait, "s for", url)
            time.sleep(min(wait, 90))
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(5 + i * 5)


HARAKAT = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
TAGS = re.compile(r"<[^>]+>")
SPACES = re.compile(r"\s+")
FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})


def norm(text):
    """Search form of a page, the same as norm() in the app."""
    t = TAGS.sub(" ", text).replace("&nbsp;", " ")
    t = HARAKAT.sub("", t).translate(FOLD)
    return SPACES.sub(" ", t).strip()


def put(path, text):
    # mtime=0 keeps the file the same from run to run when the book has not changed
    with open(path, "wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", compresslevel=9, mtime=0) as g:
            g.write(text.encode("utf-8"))


def main():
    start = time.time()
    want = [x.strip() for x in Path("scholars.txt").read_text(encoding="utf-8").split() if x.strip()]
    cat = json.loads(fetch(CATALOG))
    CACHE.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    hosted, missing = [], 0
    for s in cat["scholars"]:
        if s["key"] not in want:
            continue
        got = 0
        for b in s["books"]:
            bid = b["id"]
            raw_f, idx_f = CACHE / f"{bid}.json.gz", CACHE / f"{bid}.idx.json"
            if not (raw_f.exists() and idx_f.exists()):
                if time.time() - start > TIME_LIMIT:
                    missing += 1
                    continue
                try:
                    idx = fetch(f"https://api.turath.io/book?id={bid}&include=indexes&ver=3")
                    time.sleep(1)
                    raw = fetch(f"https://files.turath.io/books-v3/{bid}.json")
                    json.loads(raw)  # must be a whole book
                    idx_f.write_bytes(idx)
                    raw_f.write_bytes(gzip.compress(raw, 6))
                    time.sleep(1.5)
                except Exception as e:  # noqa: BLE001
                    print("skip", bid, e)
                    missing += 1
                    continue
            try:
                idx_all = json.loads(idx_f.read_text(encoding="utf-8"))
                ix = idx_all.get("indexes") or {}
                pdf = (idx_all.get("meta") or {}).get("pdf_links") or None
                pages = json.loads(gzip.decompress(raw_f.read_bytes())).get("pages") or []
            except Exception as e:  # noqa: BLE001
                print("bad cache", bid, e)
                raw_f.unlink(missing_ok=True)
                missing += 1
                continue
            d = OUT / str(bid)
            d.mkdir(exist_ok=True)
            put(d / "i.json.gz", json.dumps({
                "headings": ix.get("headings") or [],
                "page_map": ix.get("page_map") or [],
                "volumes": ix.get("volumes") or [],
                "count": len(pages),
                "chunk": CHUNK,
                "pdf": pdf,
            }, ensure_ascii=False, separators=(",", ":")))
            rows = [[str(p.get("vol") or ""), int(p.get("page") or 0), p.get("text") or ""] for p in pages]
            for k in range(0, len(rows), CHUNK):
                put(d / f"p{k // CHUNK}.json.gz", json.dumps(rows[k:k + CHUNK], ensure_ascii=False, separators=(",", ":")))
            put(d / "s.txt.gz", "\n".join(norm(r[2]).replace("\n", " ") for r in rows))
            hosted.append(bid)
            got += 1
        print(s["short"], got, "of", len(s["books"]), "books")
    (OUT / "hosted.json").write_text(json.dumps(hosted), encoding="utf-8")
    (OUT / "index.html").write_text("<!doctype html><meta charset=utf-8><title>مخزن كتب العلماء</title><p dir=rtl>مخزن نصوص كتب «مكتبة العلماء السلفية».</p>", encoding="utf-8")
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(len(hosted), "books kept,", size // (1024 * 1024), "MB,", missing, "still missing")


if __name__ == "__main__":
    sys.exit(main())
