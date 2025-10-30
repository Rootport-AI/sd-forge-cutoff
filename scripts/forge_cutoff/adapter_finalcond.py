import logging, threading
from typing import List, Tuple, Set

from modules.shared import opts

try:
    from scripts.forge_cutoff import context_volatile as vctx
except Exception:
    from forge_cutoff import context_volatile as vctx

log = logging.getLogger("forge_cutoff")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[ForgeCutoffPoC] %(levelname)s: %(message)s"))
    log.addHandler(h)
log.setLevel(logging.INFO)  # 常時出力する方針に変更（WARNINGからINFOへ）

# ---- Always-on debug (now informational) ----
def _dbg(msg, *args):
    """Always print informational logs (no toggle)"""
    try:
        log.info(msg, *args)
    except Exception:
        pass

# ---------- utils ----------

def _is_tensor(x):
    try:
        import torch
        return isinstance(x, torch.Tensor)
    except Exception:
        return False

def _enc_tag_from_S(S: int) -> str:
    # 既存挙動は維持（将来: より堅牢な識別へ差し替え可）
    return "TE1" if S <= 77 else "TE2"

def _apply_for_enc(enc: str) -> bool:
    try:
        return bool(getattr(opts, "cutoff_forge_apply_te1", False)) if enc == "TE1" \
            else bool(getattr(opts, "cutoff_forge_apply_te2", True))
    except Exception:
        return True

def _select_rows_sanity(S: int) -> List[int]:
    try:
        ratio = int(getattr(opts, "cutoff_forge_cut_ratio", 50))
    except Exception:
        ratio = 50
    ratio = max(0, min(50, ratio))
    k = int(S * ratio / 100.0)
    return list(range(max(0, S - k), S)) if k > 0 else []

def _apply_rows_inplace(series, rows: List[int], method: str, alpha, pad_sel=None):
    """
    rows で指定された行に対して一括適用する。
    alpha は単一値でも行ごとの配列でも良い（[K] / [1,K,1] / 単一値）。
    """
    import torch
    if not (_is_tensor(series) and series.dim() == 3) or not rows:
        return

    with torch.inference_mode():
        B, S, H = int(series.shape[0]), int(series.shape[1]), int(series.shape[2])
        row_idx = torch.as_tensor(rows, device=series.device, dtype=torch.long)
        sel     = series[:, row_idx, :]                    # [B,K,H]

        # フォールバック（従来互換）：pad_selが無い場合のみ平均へ（ここで一度だけ計算）
        if pad_sel is None:
            pad_vec = series.mean(dim=1, keepdim=True)     # [B,1,H]
            pad_sel = pad_vec.expand(-1, row_idx.numel(), -1)

        # alpha を [B,K,1] にブロードキャストできるテンソルへ
        if isinstance(alpha, (list, tuple)):
            a = torch.as_tensor(alpha, device=series.device, dtype=sel.dtype).view(1, -1, 1)
        elif _is_tensor(alpha):
            a = alpha
            if a.dim() == 1:  # [K] → [1,K,1]
                a = a.view(1, -1, 1)
        else:
            # 単一値（互換）：float に正規化
            try:
                aval = float(alpha)
            except Exception:
                aval = 0.6
            aval = max(0.0, min(1.0, aval))
            a = torch.tensor(aval, device=series.device, dtype=sel.dtype).view(1, 1, 1)
        # [B,K,1] に拡張
        a = a.expand(sel.shape[0], sel.shape[1], 1)

        if method == "Slerp":
            eps = 1e-7
            o = sel / torch.clamp(sel.norm(dim=-1, keepdim=True), min=eps)
            p = pad_sel / torch.clamp(pad_sel.norm(dim=-1, keepdim=True), min=eps)
            dot = torch.clamp((o * p).sum(dim=-1, keepdim=True), -1.0, 1.0)
            omega = torch.acos(dot)
            sin_omega = torch.sin(omega).clamp(min=eps)
            near = (sin_omega < 1e-4).float()
            t1 = torch.sin((1 - a) * omega) / sin_omega
            t2 = torch.sin(a * omega) / sin_omega
            mixed = t1 * o + t2 * p
            mixed = mixed * torch.clamp(sel.norm(dim=-1, keepdim=True), min=eps)
            mixed = near * ((1.0 - a) * sel + a * pad_sel) + (1.0 - near) * mixed
        else:
            mixed = (1.0 - a) * sel + a * pad_sel

        series[:, row_idx, :] = mixed

# ---- 再入防止（thread-local） ----
_tls = threading.local()
def _already_inside() -> bool:
    return getattr(_tls, "inside_cutoff", False)
def _enter():
    setattr(_tls, "inside_cutoff", True)
def _leave():
    setattr(_tls, "inside_cutoff", False)

# ---------- helper: 既存の CTPE を使って dummy_text をエンコード ----------
def _encode_dummy_same_engine(dummy_text: str, enc_tag: str, expect_H: int):
    """
    Forge の既存 CTPE を用いて dummy_text をエンコード。
    SDXL の場合は CLIP-L と CLIP-G を dim=2 で連結し、H 次元 (expect_H) を一致させる。
    """
    if not dummy_text:
        return None
    try:
        from modules import shared
        if not hasattr(shared, "sd_model") or shared.sd_model is None:
            return None

        eng_l = getattr(shared.sd_model, "text_processing_engine_l", None)
        eng_g = getattr(shared.sd_model, "text_processing_engine_g", None)

        def _series(o):
            return o[0] if (isinstance(o, tuple) and len(o) >= 1) else o

        ser_l = _series(eng_l([dummy_text])) if eng_l is not None else None
        ser_g = _series(eng_g([dummy_text])) if eng_g is not None else None

        # まず L/G 連結（SDXL 通常ケース）
        if ser_l is not None and ser_g is not None:
            import torch
            cat = torch.cat([ser_l, ser_g], dim=2)  # H 次元で連結
            if int(cat.shape[2]) == expect_H:
                return cat

        # 片翼だけで H が一致するならそれを使用（保険）
        if ser_l is not None and int(ser_l.shape[2]) == expect_H:
            return ser_l
        if ser_g is not None and int(ser_g.shape[2]) == expect_H:
            return ser_g

        # どれも一致しなければ None（→ 平均フォールバックへ）
        return None
    except Exception as e:
        # 失敗はデバッグ時のみ表示（WARNINGで統一）
        _dbg("[cutoff:L3] dummy encode failed: %s", e)
        return None

# ---------- patch ----------
def try_install():
    try:
        import backend.sampling.condition as condmod
    except Exception as e:
        _dbg("failed to import backend.sampling.condition: %s", e)
        return False

    if getattr(condmod.ConditionCrossAttn, "__cutoff_wrapped__", False):
        return True

    # process_cond のみをラップ（concat は削除）
    if hasattr(condmod, "ConditionCrossAttn") and hasattr(condmod, "ConditionCrossAttn") and hasattr(condmod.ConditionCrossAttn, "process_cond"):
        _orig_pc = condmod.ConditionCrossAttn.process_cond

        def _pc_wrapped(self, batch_size, device, **kwargs):
            ret = _orig_pc(self, batch_size=batch_size, device=device, **kwargs)

            try:
                enabled = bool(getattr(opts, "cutoff_forge_enable", False))
            except Exception:
                enabled = False
            if not enabled:
                return ret

            series = getattr(ret, "cond", None)
            if not (_is_tensor(series) and series.dim() == 3):
                _dbg("[cutoff:pc] cond is not 3D tensor; skip")
                return ret

            try:
                method = str(getattr(opts, "cutoff_forge_method", "Slerp"))
                alpha  = float(getattr(opts, "cutoff_forge_strength", 0.6))
                sanity = bool(getattr(opts, "cutoff_forge_sanity", False))
            except Exception:
                method, alpha, sanity = "Lerp", 0.6, False

            S = int(series.shape[1])
            H = int(series.shape[2])
            enc = _enc_tag_from_S(S)
            if not _apply_for_enc(enc):
                return ret

            # UIとvctxのtargets一致確認
            try:
                current_targets = str(getattr(opts, "cutoff_forge_targets", "") or "").lower().replace("，", ",")
                current_canon = ",".join([w.strip() for w in current_targets.split(",") if w.strip()])
                vctx_canon = vctx.get_targets_canon() or ""
                if vctx_canon != current_canon:
                    _dbg("[cutoff:pc] targets mismatch (vctx=%s, opts=%s); skip once",
                         (vctx_canon or "<empty>"), (current_canon or "<empty>"))
                    return ret
            except Exception:
                pass

            # Victim（初期）
            rows_victim_enc = _select_rows_sanity(S) if sanity else vctx.get_rows_victim(enc)
            if not rows_victim_enc:
                _dbg("[cutoff:pc] enc=%s S=%d victim_rows=0 targets=%s", enc, S, vctx.get_targets_canon() or "<empty>")
                return ret

            # 再入防止
            if _already_inside():
                _dbg("[cutoff:pc] re-entrancy detected; skip")
                return ret

            # TE-aware mode
            try:
                teaware = str(getattr(opts, "cutoff_forge_teaware_mode", "off") or "off")
            except Exception:
                teaware = "off"

            # Distance decay 設定
            try:
                decay_mode = str(getattr(opts, "cutoff_forge_decay_mode", "off") or "off")
                decay_strength = float(getattr(opts, "cutoff_forge_decay_strength", 0.5) or 0.5)
            except Exception:
                decay_mode, decay_strength = "off", 0.5

            # Source行（距離計算に使用）— vctx が未実装ならフォールバック
            try:
                rows_source_enc = set(vctx.get_rows(enc) or [])
            except Exception:
                rows_source_enc = set()

            # TE-aware Safe(AND) の場合、両TEの Victim 交差を採用
            if teaware == "safe_and":
                try:
                    v1 = set(vctx.get_rows_victim("TE1") or [])
                    v2 = set(vctx.get_rows_victim("TE2") or [])
                    rows_victim = sorted(v1.intersection(v2))
                except Exception:
                    rows_victim = rows_victim_enc  # 取得失敗時はそのまま
            else:
                # 現状どおり：この enc に対して適用
                rows_victim = rows_victim_enc

            if not rows_victim:
                _dbg("[cutoff:pc] victim_rows empty after TE-aware filtering; skip")
                return ret

            # ダミー（pad）を用意
            pad_sel_all = None
            dummy_text = vctx.get_dummy_text(enc)

            try:
                _enter()
                # Forgeの既存CTPEでダミーをエンコード（H次元を期待形に合わせる）
                series_pad = _encode_dummy_same_engine(dummy_text, enc_tag=enc, expect_H=H) if (not sanity) else None

                # 長さ不一致は安全にフォールバック
                if series_pad is not None:
                    try:
                        if int(series_pad.shape[1]) != S:
                            _dbg("[cutoff:pc] dummy S mismatch (%d != %d); fallback to mean", int(series_pad.shape[1]), S)
                            series_pad = None
                    except Exception:
                        series_pad = None

                import math
                import torch
                if series_pad is not None:
                    if series_pad.device != series.device or series_pad.dtype != series.dtype:
                        series_pad = series_pad.to(device=series.device, dtype=series.dtype, non_blocking=True)
                    # 全 Victim 行の pad を一括抽出
                    row_idx_all = torch.as_tensor(rows_victim, device=series.device, dtype=torch.long)
                    pad_sel_all = series_pad[:, row_idx_all, :]
                else:
                    pad_sel_all = None  # 平均は _apply_rows_inplace 内で一度だけ計算

                # 行ごとの α_i を準備（距離減衰 Off の場合は単一αにする）
                use_vector_alpha = False
                if decay_mode == "off" or (not rows_source_enc):
                    # 以前どおり：単一αで一括適用（ブロードキャスト不要）
                    alpha_arg = float(alpha)
                else:
                    use_vector_alpha = True
                    # Dmax を簡便に：Source 行の最小～最大の広がり
                    Smin = min(rows_source_enc) if rows_source_enc else 0
                    Smax = max(rows_source_enc) if rows_source_enc else (S - 1)
                    Dmax = max(1, (Smax - Smin) or 1)
                    alphas_rows: List[float] = []
                    for i in rows_victim:
                        d = min((abs(i - j) for j in rows_source_enc)) if rows_source_enc else Dmax
                        t = max(0.0, min(1.0, d / Dmax))
                        if decay_mode == "linear":
                            scale = (1.0 - t)
                        else:
                            # cosine
                            scale = 0.5 * (1.0 + math.cos(math.pi * t))
                        a_i = float(alpha) * float(decay_strength) * float(scale)
                        a_i = max(0.15, min(1.0, a_i))
                        alphas_rows.append(a_i)

                # ---- まとめて一発適用（順序非依存）----
                if use_vector_alpha:
                    _apply_rows_inplace(series, rows=rows_victim, method=method, alpha=alphas_rows, pad_sel=pad_sel_all)
                else:
                    _apply_rows_inplace(series, rows=rows_victim, method=method, alpha=alpha_arg, pad_sel=pad_sel_all)

                _dbg("[cutoff:pc] enc=%s S=%d victim_rows=%d method=%s alpha_base=%.2f decay=%s targets=%s",
                     enc, S, len(rows_victim), method, float(alpha), decay_mode, vctx.get_targets_canon() or "<empty>")
            finally:
                _leave()
                try:
                    del series_pad
                except Exception:
                    pass

            return ret

        condmod.ConditionCrossAttn.process_cond = _pc_wrapped  # type: ignore
        _dbg("patched ConditionCrossAttn.process_cond (victim-only dummy interpolation)")
    else:
        _dbg("ConditionCrossAttn.process_cond not found; skip patch")
        return False

    setattr(condmod.ConditionCrossAttn, "__cutoff_wrapped__", True)
    return True
