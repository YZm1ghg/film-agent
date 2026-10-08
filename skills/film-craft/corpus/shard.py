#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OCR one shard of a book: every page where (page % n_shards) == shard_id.

Runs as its own OS process (see run_all.py). Appends one JSON line per
finished page to <out_jsonl> and flushes immediately, so a kill at any
moment loses at most the page in flight. No shared state, no process pool,
nothing to corrupt.

usage: python shard.py <pdf> <shard_id> <n_shards> <out_jsonl> [dpi]
"""
import sys, os, json, time

def _enable_cuda_dlls():
    """Make the nvidia-wheel CUDA/cuDNN DLLs visible to onnxruntime.

    Must run before onnxruntime is imported. Only meaningful inside the
    dedicated gpu_ocr_env venv; harmless elsewhere.
    """
    try:
        import nvidia
    except ImportError:
        return False
    base = os.path.dirname(nvidia.__file__)
    for sub in os.listdir(base):
        for leaf in ("bin", "lib"):
            d = os.path.join(base, sub, leaf)
            if os.path.isdir(d):
                try:
                    os.add_dll_directory(d)
                except OSError:
                    pass
                os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
    return True


def main():
    pdf, sid, nsh, outp = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    dpi = int(sys.argv[5]) if len(sys.argv) > 5 else 110
    use_cuda = os.environ.get("OCR_USE_CUDA", "0") == "1"
    if use_cuda:
        _enable_cuda_dlls()

    import fitz, numpy as np
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR

    if use_cuda:
        eng = RapidOCR(det_use_cuda=True, rec_use_cuda=True)
    else:
        eng = RapidOCR()
    doc = fitz.open(pdf)
    n = len(doc)

    done = set()
    if os.path.exists(outp):
        for line in open(outp, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    done.add(int(json.loads(line)[0]))
                except Exception:
                    pass

    t0 = time.time()
    fh = open(outp, "a", encoding="utf-8")
    count = 0
    for i in range(n):
        if i % nsh != sid or i in done:
            continue
        try:
            pm = doc[i].get_pixmap(dpi=dpi)
            img = np.array(Image.frombytes("RGB", [pm.width, pm.height], pm.samples))
            res, _ = eng(img)
            txt = "\n".join(r[1] for r in res) if res else ""
            conf = (sum(r[2] for r in res) / len(res)) if res else 0.0
        except Exception as e:
            txt, conf = "", 0.0
            print(f"shard{sid} page{i+1} ERR {type(e).__name__}:{str(e)[:80]}",
                  file=sys.stderr, flush=True)
        fh.write(json.dumps([i, txt, conf], ensure_ascii=False) + "\n")
        fh.flush()
        count += 1
        if count % 10 == 0:
            el = time.time() - t0
            print(f"shard{sid}: {count} pages, {el/count:.1f}s/page", flush=True)
    fh.close()
    print(f"shard{sid}: DONE {count} pages in {(time.time()-t0)/60:.1f}m", flush=True)


if __name__ == "__main__":
    main()
