# ClassicTextProcessingEngine.__call__ をラップして、
# 与えられた文字列と UI の target tokens を用い、正規の tokenizer で
# 毎回（キャッシュ無し）サブ列一致→行インデックスを抽出し、
# ・Source行（従来の rows） … 互換のため保持
# ・Victim行（= 非ターゲット領域） … 中立化の適用対象（Exclude/Processing targets を反映）
# ・dummy_text（= Target を PAD トークン "_" に置換した文字列）
# を enc_tag ごとに揮発ストアへ保存する。

import logging
from typing import List, Tuple, Set

log = logging.getLogger("forge_cutoff")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[ForgeCutoffPoC] %(levelname)s: %(message)s"))
    log.addHandler(h)
log.setLevel(logging.WARNING)  # デフォルトは抑制（DebugチェックON時のみ _dbg で出す）

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

def _collect_segment_bounds(tokenizer, ids_text: List[int]) -> List[Tuple[int, int]]:
    """
    句境界のヒューリスティック検出。BPE列上で ',', ';', ' and ', ' with ', ' of ' に一致する位置を境界として
    セグメント [beg, end) のリストを返す。見つからない場合は全体を単一セグメントにする。
    """
    bounds = [0]
    seps = [",", " ,", ";", " ;", " and", " with", " of"]
    for sep in seps:
        try:
            ids_sep_vars = _encode_variants(tokenizer, sep)
        except Exception:
            ids_sep_vars = []
        for ids_sep in ids_sep_vars:
            for st, ed in _find_subseq_all(ids_text, ids_sep):
                bounds.append(ed)  # セパレータの直後から新セグメント
    bounds = sorted(set([b for b in bounds if 0 <= b <= len(ids_text)]))
    segs: List[Tuple[int, int]] = []
    if not bounds or bounds[0] != 0:
        bounds = [0] + bounds
    for i in range(len(bounds)):
        a = bounds[i]
        b = bounds[i+1] if i+1 < len(bounds) else len(ids_text)
        if a < b:
            segs.append((a, b))
    return segs

def _expand_source_hits_with_segments(hits: List[Tuple[int,int]], N: int, segs: List[Tuple[int,int]]) -> Set[int]:
    """
    ヒット範囲を±Nだけ拡張。ただし所属セグメントを越えない。
    """
    out: Set[int] = set()
    if N <= 0:
        for a, b in hits:
            out.update(range(a, b))
        return out
    for (a, b) in hits:
        sa, sb = None, None
        for (x, y) in segs:
            if a >= x and b <= y:
                sa, sb = x, y
                break
        if sa is None:
            sa, sb = 0, len(segs) and segs[-1][1] or (b + N)
        la = max(sa, a - N)
        rb = min(sb, b + N)
        out.update(range(la, rb))
    return out

def _match_words_rows(tokenizer, ids_text: List[int], words: List[str]) -> Set[int]:
    out: Set[int] = set()
    if not words:
        return out
    for w in words:
        needles = _encode_variants(tokenizer, w)
        for nd in needles:
            for st, ed in _find_subseq_all(ids_text, nd):
                out.update(range(st, ed))
    return out

def _install():
    try:
        import backend.text_processing.classic_engine as ce
    except Exception as e:
        _dbg("classic_engine import failed: %s", e)
        return False

    C = getattr(ce, "ClassicTextProcessingEngine", None)
    if C is None or not hasattr(C, "__call__"):
        _dbg("ClassicTextProcessingEngine.__call__ not found")
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

        # UI の targets / Exclude / Processing targets / Source拡張
        try:
            from modules.shared import opts
            targets_raw = str(getattr(opts, "cutoff_forge_targets", "") or "")
            excl_raw    = str(getattr(opts, "cutoff_forge_exclude_tokens", "") or "")
            ponly_raw   = str(getattr(opts, "cutoff_forge_processing_targets", "") or "")
            expand_n    = int(getattr(opts, "cutoff_forge_source_expand_n", 0) or 0)
        except Exception:
            targets_raw, excl_raw, ponly_raw, expand_n = "", "", "", 0

        canon = _canon_targets(targets_raw)
        words_targets = _norm_words_csv(canon)
        words_excl    = _norm_words_csv(excl_raw.lower())
        words_ponly   = _norm_words_csv(ponly_raw.lower())

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
                _dbg("[cutoff:L2] tokenize failed enc=%s: %s", enc_tag, e)
                # 失敗時は状態だけクリアして返す
                vctx.set_rows(enc_tag=enc_tag, rows=[], targets_canon=canon)
                vctx.set_rows_victim(enc_tag=enc_tag, rows_victim=[])
                vctx.set_dummy_text(enc_tag=enc_tag, dummy_text="")
                return out

            # ターゲット一致（BPE部分列一致）
            hits: List[Tuple[int,int]] = []
            rows_source: Set[int] = set()
            if tokenizer is not None and ids_text:
                for w in words_targets:
                    needles = _encode_variants(tokenizer, w)
                    hit_local = 0
                    for nd in needles:
                        hs = _find_subseq_all(ids_text, nd)
                        if hs:
                            hits.extend(hs)
                        for st, ed in hs:
                            for r in range(st, ed):
                                rows_source.add(r)
                        hit_local += len(hs)
                    hits_total += hit_local

            # 句境界ヒューリスティック ＋ Source拡張（±N; セグメント越境禁止）
            if expand_n > 0 and ids_text and tokenizer is not None and hits:
                segs = _collect_segment_bounds(tokenizer, ids_text)
                rows_source = _expand_source_hits_with_segments(hits, expand_n, segs)

            rows_sorted = sorted(rows_source)

            # Victim行（初期） = [0..S_total-1] \ Source行
            if S_total > 0:
                all_rows = set(range(S_total))
                rows_victim = set(all_rows - rows_source)
            else:
                rows_victim = set()

            # Exclude / Processing targets を反映（BPE一致）
            if tokenizer is not None and ids_text:
                rows_excl  = _match_words_rows(tokenizer, ids_text, words_excl) if words_excl else set()
                rows_pt    = _match_words_rows(tokenizer, ids_text, words_ponly) if words_ponly else set()
                if rows_pt:
                    rows_victim = rows_victim.intersection(rows_pt)
                if rows_excl:
                    rows_victim = rows_victim - rows_excl

            rows_victim_sorted = sorted(rows_victim)

            # dummy_text の素朴生成（文字列置換）
            dummy_text = _build_dummy_text(text0, words_targets)

            _dbg("[cutoff:L2] enc=%s S_total=%d hits=%d targets=%s -> source_rows=%d victim_rows=%d",
                 enc_tag, S_total, hits_total, canon, len(rows_sorted), len(rows_victim_sorted))

        # 揮発ストアへ保存
        vctx.set_rows(enc_tag=enc_tag, rows=rows_sorted, targets_canon=canon)
        vctx.set_rows_victim(enc_tag=enc_tag, rows_victim=rows_victim_sorted)
        vctx.set_dummy_text(enc_tag=enc_tag, dummy_text=dummy_text)

        return out

    C.__call__ = _wrapped  # type: ignore
    setattr(C, "__cutoff_tokenmap_wrapped__", True)
    _dbg("patched ClassicTextProcessingEngine.__call__ for token mapping (victim & dummy)")
    return True

_install()
