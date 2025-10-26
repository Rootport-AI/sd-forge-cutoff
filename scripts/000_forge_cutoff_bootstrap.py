# 最優先で読み込ませるブートストラップ（キャッシュレス版）
import sys
import types
import logging
from importlib import import_module

log = logging.getLogger("forge_cutoff_boot")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[ForgeCutoffPoC] %(levelname)s: %(message)s"))
    log.addHandler(h)
log.setLevel(logging.INFO)


def _detect_forge():
    try:
        import backend.text_processing.classic_engine as _  # noqa: F401
        return True
    except Exception:
        return False


def _install_dummy_hijack_modules():
    needs = {
        "modules.sd_hijack_clip": [
            "CLIPTextEmbedder", "FrozenCLIPEmbedder",
            "FrozenCLIPEmbedderWithCustomWords",
            "FrozenCLIPEmbedderWithCustomWordsBase",
        ],
        "modules.sd_hijack_clip_old": [
            "CLIPTextEmbedder", "FrozenCLIPEmbedder",
            "FrozenCLIPEmbedderWithCustomWords",
            "FrozenCLIPEmbedderWithCustomWordsBase",
        ],
    }
    for modname, classes in needs.items():
        m = sys.modules.get(modname)
        if m is None:
            m = types.ModuleType(modname)
            sys.modules[modname] = m
        for cls in classes:
            if not hasattr(m, cls):
                setattr(m, cls, type(cls, (), {}))


def _disable_a1111_unet_hook():
    candidates = [
        "scripts.cutofflib.sdhook",
        "cutofflib.sdhook",
        "extensions.sd-webui-cutoff.scripts.cutofflib.sdhook",
    ]
    for modname in candidates:
        try:
            m = import_module(modname)
        except Exception:
            continue

        if hasattr(m, "setup"):
            def _noop_setup(p, _modname=modname):  # noqa: ARG001
                log.info("[ForgeCutoffPoC] disable %s.setup()", _modname); return
            m.setup = _noop_setup

        if hasattr(m, "restore"):
            def _noop_restore(_modname=modname):
                log.info("[ForgeCutoffPoC] disable %s.restore()", _modname); return
            m.restore = _noop_restore

        if hasattr(m, "Hooker"):
            K = m.Hooker
            if hasattr(K, "setup"):
                def _noop_cls_setup(self, p, _modname=modname):  # noqa: ARG001
                    log.info("[ForgeCutoffPoC] disable %s.Hooker.setup()", _modname); return
                K.setup = _noop_cls_setup
            if hasattr(K, "restore"):
                def _noop_cls_restore(self, _modname=modname):
                    log.info("[ForgeCutoffPoC] disable %s.Hooker.restore()", _modname); return
                K.restore = _noop_cls_restore


def _hide_legacy_cutoff_ui():
    try:
        m = import_module("scripts.cutoff")
    except Exception:
        return
    try:
        from modules import scripts as _scripts
        if hasattr(m, "Script"):
            orig = m.Script
            if hasattr(orig, "show"):
                def _hide(self, is_img2img):  # noqa: ARG001
                    return _scripts.AlwaysHidden
                orig.show = _hide
                log.info("[ForgeCutoffPoC] legacy cutoff UI hidden")
    except Exception:
        pass


def _install_adapter_and_tokenmap():
    try:
        m = import_module("scripts.forge_cutoff.adapter_finalcond")
    except ModuleNotFoundError:
        m = import_module("forge_cutoff.adapter_finalcond")
    m.try_install()

    try:
        import_module("scripts.030_forge_cutoff_tokenmap")
    except ModuleNotFoundError:
        import_module("030_forge_cutoff_tokenmap")


if _detect_forge():
    _install_dummy_hijack_modules()
    _disable_a1111_unet_hook()
    _hide_legacy_cutoff_ui()
    try:
        _install_adapter_and_tokenmap()
        # ※ get_conds_with_caching 前座リフレッシュは完全削除（ユーザー手動リフレッシュ方針）
    except Exception as e:
        log.exception("bootstrap install failed: %s", e)
else:
    log.info("Forge backend not detected; bootstrap did nothing.")
