import logging, threading
from typing import List

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
log.setLevel(logging.INFO)

# ---- Debug guard ----
def _dbg(msg, *args):
    """Verbose log only when opts.cutoff_forge_debug_log == True"""
    try:
        from modules.shared import opts as _opts
        if bool(getattr(_opts, "cutoff_forge_debug_log", False)):
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

def _apply_rows_inplace(series, rows: List[int], method: str, alpha: float, pad_sel=None):
    import torch
    if not (_is_tensor(series) and series.dim() == 3) or not rows:
        return
    try:
        alpha = float(alpha)
    except Exception:
        alpha = 0.6
    alpha = max(0.0, min(1.0, alpha))

    with torch.inference_mode():
        B, S, H = int(series.shape[0]), int(series.shape[1]), int(series.shape[2])
        row_idx = torch.as_tensor(rows, device=series.device, dtype=torch.long)
        sel     = series[:, row_idx, :]                    # [B,K,H]

        # フォールバック（従来互換）：pad_selが無い場合のみ平均へ
        if pad_sel is None:
            pad_vec = series.mean(dim=1, keepdim=True)     # [B,1,H]
            pad_sel = pad_vec.expand(-1, row_idx.numel(), -1)

        if method == "Slerp":
            eps = 1e-7
            o = sel / torch.clamp(sel.norm(dim=-1, keepdim=True), min=eps)
            p = pad_sel / torch.clamp(pad_sel.norm(dim=-1, keepdim=True), min=eps)
            dot = torch.clamp((o * p).sum(dim=-1, keepdim=True), -1.0, 1.0)
            omega = torch.acos(dot)
            sin_omega = torch.sin(omega).clamp(min=eps)
            near = (sin_omega < 1e-4).float()
            t1 = torch.sin((1 - alpha) * omega) / sin_omega
            t2 = torch.sin(alpha * omega) / sin_omega
            mixed = t1 * o + t2 * p
            mixed = mixed * torch.clamp(sel.norm(dim=-1, keepdim=True), min=eps)
            mixed = near * ((1.0 - alpha) * sel + alpha * pad_sel) + (1.0 - near) * mixed
        else:
            mixed = (1.0 - alpha) * sel + alpha * pad_sel

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
        # 失敗は最低限ログとして残す
        log.info("[cutoff:L3] dummy encode failed: %s", e)
        return None

# ---------- patch ----------
def try_install():
    try:
        import backend.sampling.condition as condmod
    except Exception as e:
        log.info("failed to import backend.sampling.condition: %s", e)
        return False

    if getattr(condmod.ConditionCrossAttn, "__cutoff_wrapped__", False):
        return True

    # process_cond のみをラップ（concat は削除）
    if hasattr(condmod, "ConditionCrossAttn") and hasattr(condmod.ConditionCrossAttn, "process_cond"):
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

            rows_apply = _select_rows_sanity(S) if sanity else vctx.get_rows_victim(enc)
            if not rows_apply:
                _dbg("[cutoff:pc] enc=%s S=%d victim_rows=0 targets=%s", enc, S, vctx.get_targets_canon() or "<empty>")
                return ret

            # 再入防止
            if _already_inside():
                _dbg("[cutoff:pc] re-entrancy detected; skip")
                return ret

            pad_sel = None
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

                import torch
                if series_pad is not None:
                    if series_pad.device != series.device or series_pad.dtype != series.dtype:
                        series_pad = series_pad.to(device=series.device, dtype=series.dtype, non_blocking=True)
                    row_idx = torch.as_tensor(rows_apply, device=series.device, dtype=torch.long)
                    pad_sel = series_pad[:, row_idx, :]

                # Victim 行にのみ適用（Sourceは触らない）
                _apply_rows_inplace(series, rows=rows_apply, method=method, alpha=alpha, pad_sel=pad_sel)

                _dbg("[cutoff:pc] enc=%s S=%d victim_rows=%d first=%d last=%d method=%s alpha=%.2f targets=%s",
                     enc, S, len(rows_apply), rows_apply[0], rows_apply[-1], method, alpha, vctx.get_targets_canon() or "<empty>")
            finally:
                _leave()
                try:
                    del series_pad
                except Exception:
                    pass

            return ret

        condmod.ConditionCrossAttn.process_cond = _pc_wrapped  # type: ignore
        log.info("patched ConditionCrossAttn.process_cond (victim-only dummy interpolation)")
    else:
        log.info("ConditionCrossAttn.process_cond not found; skip patch")
        return False

    setattr(condmod.ConditionCrossAttn, "__cutoff_wrapped__", True)
    return True
