# 005_startup_defaults.py
# 起動ごとに Enable を明示的に OFF に戻す。
# ユーザー保護の意図：意図せぬ適用を避けるための保守的デフォルト。
from modules import script_callbacks
from modules.shared import opts

def _force_enable_off(_app=None, *_args, **_kwargs):
    try:
        # 起動時に毎回 OFF スタート
        setattr(opts, "cutoff_forge_enable", False)
    except Exception:
        pass

# WebUI起動後、一度だけ実行
script_callbacks.on_app_started(_force_enable_off)
