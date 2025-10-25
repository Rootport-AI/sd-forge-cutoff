# ClassicTextProcessingEngine.__call__ をラップして、
# 与えられた文字列と UI の target tokens を用い、正規の tokenizer で
# 毎回（キャッシュ無し）サブ列一致→行インデックスを抽出し、
# ・Source行（従来の rows） … 互換のため保持
# ・Victim行（= 非ターゲット領域） … 中立化の適用対象
# ・dummy_text（= Target を PAD トークン "_" に置換した文字列）
# を enc_tag ごとに揮発ストアへ保存する。

import logging
from typing import List, Tuple, Set

log = logging.getLogger("forge_cutoff")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[ForgeCutoffPoC] %(levelname)s: %(message)s"))
    log.addHandler(h)
log.setLevel(logging.INFO)

def _dbg(msg, *args):
    """Verbose L2 log only when debug flag is ON"""
    try:
        from modules.shared import opts as _opts
        if bool(getattr(_opts, "cutoff_forge_debug_log", False)):
            log.info(msg, *args)
    except Exception:
        pass

try:
    from scripts.forge_cutoff import context_volatile as vctx
except Exception:
    from forge_cutoff import context_volatile as vctx

def _norm_words_csv(s: str) -> List[str]:
    import re
    return [w.strip() for w in re.split(r"[,，\s]+", s or "") if w.strip()]

def _canon_targets(s: str) -> str:
    return ",".join(_norm_words_csv(s or "")).lower()

def _flat_chunks(chunks) -> Tuple[List[int], int]:
    ids: List[int] = []
    S_total = 0
    for ch in chunks:
        ids.extend(ch.tokens)
        S_total += len(ch.tokens)
    return ids, S_total

def _find_subseq_all(hay: List[int], needle: List[int]) -> List[Tuple[int, int]]:
    hits = []
    if not hay or not needle:
        return hits
    n = len(needle)
    if n > len(hay):
        return hits
    for i in range(0, len(hay) - n + 1):
        if hay[i:i+n] == needle:
            hits.append((i, i+n))
    return hits

def _encode_variants(tokenizer, word: str) -> List[List[int]]:
    variants = [word, " " + word, word.lower(), " " + word.lower()]
    outs: List[List[int]] = []
    for v in variants:
        try:
            ids = tokenizer.encode(v, add_special_tokens=False)
            if hasattr(ids, "tolist"):
                ids = ids.tolist()
            ids = list(ids) if ids else []
        except Exception:
            ids = []
        if ids:
            outs.append(ids)
    # dedup
    uniq, seen = [], set()
    for ids in outs:
        t = tuple(ids)
        if t not in seen:
            seen.add(t)
            uniq.append(ids)
    return uniq

def _build_dummy_text(text: str, words: List[str]) -> str:
    import re
    s = text or ""
    for w in words:
        if not w:
            continue
        pat = r'(?i)\b' + re.escape(w) + r'\b'
        s = re.sub(pat, "_", s)
    return s

def _install():
    try:
        import backend.text_processing.classic_engine as ce
    except Exception as e:
        log.info("classic_engine import failed: %s", e)
        return False

    C = getattr(ce, "ClassicTextProcessingEngine", None)
    if C is None or not hasattr(C, "__call__"):
        log.info("ClassicTextProcessingEngine.__call__ not found")
        return False

    if getattr(C, "__cutoff_tokenmap_wrapped__", False):
        return True

    _orig = C.__call__

    def _wrapped(self, texts):
        out = _orig(self, texts)

        # どのエンコーダか（S から推定 → 後段で enc_tag をキーに整合）
        try:
            series = out[0] if (isinstance(out, tuple) and len(out) >= 1) else out  # Tensor [B,S,H]
            S = int(series.shape[-2])
            enc_tag = "TE1" if S <= 77 else "TE2"
        except Exception:
            enc_tag = "TE1"

        # UI の targets
        try:
            from modules.shared import opts
            targets_raw = str(getattr(opts, "cutoff_forge_targets", "") or "")
        except Exception:
            targets_raw = ""
        canon = _canon_targets(targets_raw)
        words = _norm_words_csv(canon)

        # 入力テキスト（Forge 実測で texts_len=1）
        text0 = ""
        try:
            text0 = (texts[0] if texts else "") or ""
        except Exception:
            pass

        rows_sorted: List[int] = []
        rows_victim_sorted: List[int] = []
        hits_total = 0
        dummy_text = ""

        if canon and text0:
            try:
                chunks, _tc = self.tokenize_line(text0)
                ids_text, S_total = _flat_chunks(chunks)
                tokenizer = getattr(self, "tokenizer", None)
            except Exception as e:
                log.info("[cutoff:L2] tokenize failed enc=%s: %s", enc_tag, e)
                # 失敗時は状態だけクリアして返す
                vctx.set_rows(enc_tag=enc_tag, rows=[], targets_canon=canon)
                vctx.set_rows_victim(enc_tag=enc_tag, rows_victim=[])
                vctx.set_dummy_text(enc_tag=enc_tag, dummy_text="")
                return out

            # Source行（= ターゲット一致区間＋前後1）
            rows: Set[int] = set()
            if tokenizer is not None and ids_text:
                for w in words:
                    needles = _encode_variants(tokenizer, w)
                    hit_local = 0
                    for nd in needles:
                        hs = _find_subseq_all(ids_text, nd)
                        for st, ed in hs:
                            for r in range(st, ed):
                                rows.add(r)
                            rows.add(max(0, st-1))
                            rows.add(min(S_total-1, ed))
                        hit_local += len(hs)
                    hits_total += hit_local

            rows_sorted = sorted(rows)

            # Victim行 = [0..S_total-1] \ Source行
            if S_total > 0:
                all_rows = set(range(S_total))
                rows_victim_sorted = sorted(all_rows - rows)

            # dummy_text の素朴生成（文字列置換）
            dummy_text = _build_dummy_text(text0, words)

            _dbg("[cutoff:L2] enc=%s S_total=%d hits=%d targets=%s -> source_rows=%d victim_rows=%d",
                 enc_tag, S_total, hits_total, canon, len(rows_sorted), len(rows_victim_sorted))

        # 揮発ストアへ保存
        vctx.set_rows(enc_tag=enc_tag, rows=rows_sorted, targets_canon=canon)
        vctx.set_rows_victim(enc_tag=enc_tag, rows_victim=rows_victim_sorted)
        vctx.set_dummy_text(enc_tag=enc_tag, dummy_text=dummy_text)

        return out

    C.__call__ = _wrapped  # type: ignore
    setattr(C, "__cutoff_tokenmap_wrapped__", True)
    log.info("patched ClassicTextProcessingEngine.__call__ for token mapping (victim & dummy)")
    return True

_install()
