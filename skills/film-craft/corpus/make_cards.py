#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Build per-book detail cards from the OCR'd corpus:
  out/cards/<slug>.md   -> front matter (mode/pages/chars) + detected chapter list
                            + opening pages + the book's densest keyword hits
Run:  python make_cards.py            (all books present in out/txt)
      python make_cards.py 56 8       (only those book numbers)
"""
import os, re, sys, json

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
TXT, META, CARDS = (os.path.join(OUT, k) for k in ("txt", "meta", "cards"))
os.makedirs(CARDS, exist_ok=True)

PAGE_RE = re.compile(r"<<<Page (\d+)>>>")
CHAP_RE = re.compile(
    r"^\s*(第\s*[0-9一二三四五六七八九十百]+\s*[章节部篇讲]|"
    r"[Cc]hapter\s+\d+|[0-9]{1,2}\.[0-9]{1,2}\s+\S|"
    r"第\s*[0-9一二三四五六七八九十百]+\s*章\s*\S+)"
)

# concept probes used to show "what this book actually covers"
PROBES = [
    "景别", "轴线", "构图", "运动", "剪辑", "声音", "布光", "光比", "色彩", "色温",
    "结构", "人物", "对白", "冲突", "场景", "表演", "调度", "镜头", "曝光", "景深",
    "蒙太奇", "长镜头", "类型", "叙事", "节奏", "理论", "美学", "风格", "录音", "音效",
    "预算", "制片", "发行", "纪录片", "访谈", "特写", "推拉", "摇镜", "母题", "象征",
]


def slug_of(fn):
    for ch in '\\/:*?"<>|':
        fn = fn.replace(ch, "_")
    return fn[:90]


def splits(text):
    parts = PAGE_RE.split(text)
    return [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts), 2)]


def build(slug):
    tp = os.path.join(TXT, slug + ".txt")
    if not os.path.exists(tp):
        return None
    text = open(tp, encoding="utf-8").read()
    meta = {}
    mp = os.path.join(META, slug + ".json")
    if os.path.exists(mp):
        meta = json.load(open(mp, encoding="utf-8"))
    pgs = splits(text)

    chapters = []
    for pg, body in pgs:
        for line in body.split("\n")[:14]:
            line = line.strip()
            if 2 <= len(line) <= 42 and CHAP_RE.match(line):
                chapters.append((pg, line))
                break

    # keyword coverage
    hits = sorted(((k, len(re.findall(re.escape(k), text))) for k in PROBES),
                  key=lambda t: -t[1])
    hits = [(k, n) for k, n in hits if n >= 3][:22]

    L = [f"# {meta.get('file', slug)}", ""]
    L.append(f"- 抽取模式：**{meta.get('mode','?')}**")
    L.append(f"- 页数：{meta.get('pages','?')}  |  字符数：{meta.get('chars',0):,}"
             f"  |  空页：{meta.get('empty_pages','?')}")
    if meta.get("mean_conf") is not None:
        L.append(f"- OCR 平均置信度：**{meta['mean_conf']}**")
    L.append("")

    if chapters:
        L.append(f"## 检出章节（{len(chapters)} 条）")
        L.append("")
        for pg, t in chapters[:60]:
            L.append(f"- p{pg} · {t}")
        L.append("")

    L.append("## 主题词覆盖（出现次数 ≥3）")
    L.append("")
    L.append(" | ".join(f"`{k}`×{n}" for k, n in hits))
    L.append("")

    # opening pages as content preview
    L.append("## 正文开头（前若干页）")
    L.append("")
    body_txt = ""
    for pg, body in pgs[:6]:
        body_txt += body
    body_txt = re.sub(r"[ \t]+", " ", body_txt)
    body_txt = re.sub(r"\n{3,}", "\n\n", body_txt).strip()
    L.append("```")
    L.append(body_txt[:2400])
    L.append("```")
    L.append("")
    L.append("---")
    L.append(f"检索原文：`python tools.py search \"关键词\" --book {meta.get('file','')[:20]}`")
    L.append(f"读取段落：`python tools.py read {slug.split('.')[0]} <起页> <止页>`")

    md = "\n".join(L)
    open(os.path.join(CARDS, slug + ".md"), "w", encoding="utf-8").write(md)
    return len(md)


if __name__ == "__main__":
    want = set(sys.argv[1:])
    n = 0
    for fn in sorted(os.listdir(TXT)):
        if not fn.endswith(".txt"):
            continue
        slug = fn[:-4]
        num = slug.split(".")[0]
        if want and num not in want:
            continue
        r = build(slug)
        if r:
            n += 1
            print(f"card {slug} ({r} bytes)")
    print(f"built {n} cards -> {CARDS}")
