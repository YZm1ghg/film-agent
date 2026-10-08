#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Drive the whole library through N independent OCR shard subprocesses.

For each pending book:
  1. split its pages into NSHARDS interleaved slices
  2. launch one subprocess per slice (shard.py)
  3. wait; any shard that dies is simply relaunched for its missing pages
  4. assemble the JSONL slices into out/txt/<slug>.txt and write metadata

Everything is on disk as it goes, so an external kill (logoff, reboot,
Ctrl-C) resumes with zero rework. Safe to run repeatedly.
"""
import fitz, os, sys, json, time, io, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
# Source library of PDFs. NOT bundled with the plugin: point this at your own
# legally obtained copies (or set the OCR_SRC environment variable).
SRC = os.environ.get("OCR_SRC", os.path.join(HERE, "pdf"))
OUT = os.path.join(HERE, "out")
TXT, META, DONE, SHARDS = (os.path.join(OUT, k) for k in ("txt", "meta", "done", "shards"))
for d in (TXT, META, DONE, SHARDS):
    os.makedirs(d, exist_ok=True)

LOCK = os.path.join(OUT, ".run_all.lock")


def _pid_alive(pid):
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True, timeout=20).stdout
        return str(pid) in out
    except Exception:
        return False


def acquire_lock():
    """Refuse to start if another run_all is already working on this corpus.

    Two concurrent runs write the same shard files and thrash each other --
    that happened once and silently stalled progress for 20+ minutes.
    """
    if os.path.exists(LOCK):
        try:
            other = int(open(LOCK).read().strip())
        except Exception:
            other = None
        if other and other != os.getpid() and _pid_alive(other):
            log(f"another run_all is already running (pid {other}); exiting")
            sys.exit(0)
        log(f"clearing stale lock (pid {other} not running)")
    with open(LOCK, "w") as fh:
        fh.write(str(os.getpid()))


def release_lock():
    try:
        if os.path.exists(LOCK) and open(LOCK).read().strip() == str(os.getpid()):
            os.remove(LOCK)
    except OSError:
        pass


PY = os.environ.get("OCR_PY", sys.executable)
SHARD = os.path.join(HERE, "shard.py")
NSHARDS = int(os.environ.get("OCR_SHARDS", "10"))
DPI = int(os.environ.get("OCR_DPI", "110"))
USE_CUDA = os.environ.get("OCR_USE_CUDA", "0") == "1"
PROBE = [8, 12, 16, 22]


def log(*a):
    print(*a, flush=True)


def slug(name):
    s = name.rsplit(".", 1)[0]
    for ch in '\\/:*?"<>|':
        s = s.replace(ch, "_")
    return s[:90]


def native_quality(doc):
    n = len(doc)
    return sum(len(doc[i].get_text().strip()) for i in PROBE if i < n) / len(PROBE)


def atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def load_shards(slugname):
    got = {}
    d = os.path.join(SHARDS, slugname)
    if not os.path.isdir(d):
        return got
    for fn in os.listdir(d):
        if not fn.endswith(".jsonl"):
            continue
        for line in open(os.path.join(d, fn), encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    i, t, c = json.loads(line)
                    got[int(i)] = (t, c)
                except Exception:
                    pass
    return got


def ocr_book(path, fn, pages, name):
    sdir = os.path.join(SHARDS, name)
    os.makedirs(sdir, exist_ok=True)
    t0 = time.time()

    for attempt in range(4):
        got = load_shards(name)
        missing = [i for i in range(pages) if i not in got]
        if not missing:
            break
        # shards that still have work
        live = NSHARDS if attempt == 0 else min(NSHARDS, max(1, len(missing) // 4))
        log(f"    {fn[:26]} attempt{attempt+1}: {len(got)}/{pages} done, "
            f"{len(missing)} to go, {live} shards")
        procs = []
        for sid in range(live):
            outp = os.path.join(sdir, f"s{sid}.jsonl")
            env = dict(os.environ)
            env["OCR_USE_CUDA"] = "1" if USE_CUDA else "0"
            procs.append(subprocess.Popen(
                [PY, "-u", SHARD, path, str(sid), str(live), outp, str(DPI)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env))
        for p in procs:
            p.wait()
        el = (time.time() - t0) / 60
        log(f"    {fn[:26]} round{attempt+1} finished, elapsed {el:.1f}m")

    got = load_shards(name)
    buf = io.StringIO()
    buf.write(f"# {fn}\n# pages={pages} mode=ocr\n\n")
    confs, empty = [], 0
    for i in range(pages):
        t, c = got.get(i, ("", 0.0))
        if t.strip():
            buf.write(f"\n<<<Page {i+1}>>>\n{t}\n")
            confs.append(c)
        else:
            empty += 1
    mean = round(sum(confs) / len(confs), 4) if confs else None
    return buf.getvalue(), empty, mean


def native_book(path, fn):
    doc = fitz.open(path)
    buf = io.StringIO()
    buf.write(f"# {fn}\n# pages={len(doc)} mode=native\n\n")
    empty = 0
    for i in range(len(doc)):
        t = doc[i].get_text()
        if t.strip():
            buf.write(f"\n<<<Page {i+1}>>>\n{t}\n")
        else:
            empty += 1
    n = len(doc)
    doc.close()
    return buf.getvalue(), n, empty, None


def main():
    acquire_lock()
    try:
        _main()
    finally:
        release_lock()


def _main():
    pdfs = sorted(f for f in os.listdir(SRC) if f.lower().endswith(".pdf"))
    todo = [f for f in pdfs if not os.path.exists(os.path.join(DONE, slug(f)))]
    log(f"[run_all] {len(pdfs)} pdfs, {len(todo)} remaining, "
        f"{NSHARDS} shards, dpi={DPI}, cuda={USE_CUDA}")

    t_start = time.time()
    for idx, fn in enumerate(pdfs, 1):
        s = slug(fn)
        if os.path.exists(os.path.join(DONE, s)):
            continue
        path = os.path.join(SRC, fn)
        t0 = time.time()
        try:
            doc = fitz.open(path)
            pages = len(doc)
            q = native_quality(doc)
            doc.close()
        except Exception as e:
            log(f"[{idx}/{len(pdfs)}] FAIL open {fn}: {e}")
            open(os.path.join(DONE, s), "w").write("open-fail")
            continue

        try:
            if q >= 60:
                text, pages, empty, conf = native_book(path, fn)
            else:
                text, empty, conf = ocr_book(path, fn, pages, s)
        except KeyboardInterrupt:
            log("interrupted; shard progress is on disk under out/shards")
            raise

        atomic_write(os.path.join(TXT, s + ".txt"), text)
        meta = dict(file=fn, pages=pages, mode="native" if q >= 60 else "ocr",
                    chars=len(text), empty_pages=empty, mean_conf=conf,
                    secs=round(time.time() - t0, 1))
        atomic_write(os.path.join(META, s + ".json"),
                     json.dumps(meta, ensure_ascii=False, indent=2))
        open(os.path.join(DONE, s), "w").write("ok")
        log(f"[{idx}/{len(pdfs)}] {meta['mode']} {pages}p conf={conf} "
            f"chars={meta['chars']} {meta['secs']}s :: {fn}")
        log(f"    elapsed {(time.time()-t_start)/60:.1f} min")

    log("[run_all] ALL DONE")
    _finalize()


def _finalize():
    """Generate per-book cards and the chapter index once the corpus is whole."""
    log("[run_all] finalizing: cards + index")
    for script in ("make_cards.py", "tools.py"):
        path = os.path.join(HERE, script)
        if not os.path.exists(path):
            continue
        args = [PY, "-u", path] + (["index"] if script == "tools.py" else [])
        try:
            r = subprocess.run(args, cwd=HERE, capture_output=True, text=True,
                               timeout=1800)
            tail = (r.stdout or "").strip().splitlines()
            log(f"  {script}: rc={r.returncode} {tail[-1] if tail else ''}")
        except Exception as e:
            log(f"  {script}: failed {type(e).__name__} {e}")
    log("[run_all] finalize complete")


if __name__ == "__main__":
    main()
