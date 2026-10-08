#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase 2 toolkit: parse the extracted corpus.
  python tools.py list                 -> extraction status table
  python tools.py index                -> build out/index.json (chapter map per book)
  python tools.py search <kw> [--top N] [--book KEY]
  python tools.py chapter <bookIdx> <lo> <hi>
  python tools.py read <bookIdx> <startPage> <endPage>
Book numbers are the leading number in the filename (1..62) or a substring match.
"""
import os, re, sys, json, glob

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
TXT, META, DONE = (os.path.join(OUT, k) for k in ("txt", "meta", "done"))

PAGE_RE = re.compile(r"<<<Page (\d+)>>>")
# Chinese chapter headings: 第X章 / 第X节 / 第X部 / 第一章 / 一、 / 1.2 titles
CHAP_RE = re.compile(
    r"^\s*(第\s*[0-9一二三四五六七八九十百]+\s*[章节部篇讲]|"
    r"[Cc]hapter\s+\d+|"
    r"[0-9]{1,2}\.[0-9]{1,2}\s+\S)"
)


def books():
    """All books that have a text file, sorted by leading number."""
    out = []
    for p in glob.glob(os.path.join(TXT, "*.txt")):
        s = os.path.basename(p)[:-4]
        m = re.match(r"^(\d+)[\.\s]", s)
        num = int(m.group(1)) if m else 999
        out.append((num, s, p))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def load(slug):
    with open(os.path.join(TXT, slug + ".txt"), encoding="utf-8") as fh:
        return fh.read()


def splits(text):
    """[(page, text)]"""
    parts = PAGE_RE.split(text)
    res = []
    for i in range(1, len(parts), 2):
        res.append((int(parts[i]), parts[i + 1]))
    return res


def resolve(key):
    """Resolve a user key (number or substring) to a slug."""
    bs = books()
    if key.isdigit():
        n = int(key)
        for num, slug, _ in bs:
            if num == n:
                return slug
    hits = [s for _, s, _ in bs if key in s]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"no book matches {key!r}")
    print("multiple matches:", file=sys.stderr)
    for h in hits:
        print("  ", h, file=sys.stderr)
    return hits[0]


def cmd_list():
    for num, slug, path in books():
        mp = os.path.join(META, slug + ".json")
        m = json.load(open(mp, encoding="utf-8")) if os.path.exists(mp) else {}
        print(f"{num:>3} | {m.get('mode','?'):>6} | {m.get('pages','?'):>4}p | "
              f"{m.get('chars',0):>8}ch | conf={m.get('mean_conf')} | {slug[:52]}")
    print(f"\ntotal books extracted: {len(books())}")


def cmd_index():
    idx = {}
    for num, slug, path in books():
        text = load(slug)
        pgs = splits(text)
        chapters = []
        for pg, body in pgs:
            for line in body.split("\n")[:14]:
                line = line.strip()
                if 2 <= len(line) <= 42 and CHAP_RE.match(line):
                    chapters.append({"page": pg, "title": line})
                    break
        idx[slug] = {
            "num": num,
            "pages": len(pgs),
            "chars": len(text),
            "chapters": chapters,
            "page1_hint": (pgs[0][1][:300] if pgs else ""),
        }
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(idx, fh, ensure_ascii=False, indent=2)
    tot = sum(v["chars"] for v in idx.values())
    print(f"indexed {len(idx)} books, {tot:,} chars")


def iter_pages(book_filter=None):
    for num, slug, path in books():
        if book_filter and book_filter not in slug:
            continue
        for pg, body in splits(load(slug)):
            yield slug, pg, body


def cmd_search(kw, top=40, book=None):
    pat = re.compile(re.escape(kw), re.I)
    rows = []
    for slug, pg, body in iter_pages(book):
        for m in pat.finditer(body):
            a, b = max(0, m.start() - 60), m.end() + 90
            snippet = re.sub(r"\s+", " ", body[a:b]).strip()
            rows.append((slug, pg, snippet))
    rows.sort(key=lambda r: r[0])
    print(f"{len(rows)} hits for {kw!r}\n")
    for slug, pg, sn in rows[:top]:
        print(f"[{slug[:40]} p{pg}] …{sn}…")


def cmd_range(book, lo, hi, mode="read"):
    slug = resolve(book)
    for pg, body in splits(load(slug)):
        if lo <= pg <= hi:
            body = re.sub(r"\n{3,}", "\n\n", body).strip()
            print(f"\n===== {slug}  p{pg} =====\n{body}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "list":
        cmd_list()
    elif a[0] == "index":
        cmd_index()
    elif a[0] == "search":
        kw = a[1]
        top = 40
        book = None
        if "--top" in a:
            top = int(a[a.index("--top") + 1])
        if "--book" in a:
            book = a[a.index("--book") + 1]
        cmd_search(kw, top, book)
    elif a[0] in ("read", "chapter"):
        cmd_range(a[1], int(a[2]), int(a[3]))
    else:
        print(__doc__)
