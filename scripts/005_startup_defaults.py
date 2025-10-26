# 005_startup_defaults.py
# 起動ごとに Enable を明示的に OFF に戻す。
# ユーザー保護の意図：意図せぬ適用を避けるための保守的デフォルト。
from modules import script_callbacks
from modules.shared import opts

def _force_enable_off(_app=None, *_args, **_kwargs):
    try:
        # 起動時に毎回 OFF スタート
        opts.cutoff_forge_enable = False
        opts.cutoff_forge_source_expand_n = 0
        opts.cutoff_forge_decay_mode = "off"
        opts.cutoff_forge_decay_strength = 0.5
        opts.cutoff_forge_exclude_tokens = ""
        opts.cutoff_forge_processing_targets = ""
        opts.cutoff_forge_teaware_mode = "off"
    except Exception:
        pass

# WebUI起動後、一度だけ実行
script_callbacks.on_app_started(_force_enable_off)