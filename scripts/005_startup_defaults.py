# 005_startup_defaults.py
# 起動ごとに Enable を明示的に OFF に戻す。
# ユーザー保護の意図：意図せぬ適用を避けるための保守的デフォルト。
from modules import script_callbacks
from modules.shared import opts

def _force_enable_off(_app=None, *_args, **_kwargs):
    try:
        # 起動時に毎回 OFF スタート
        opts.cutoff_forge_enable = False

        # --- NEW: 本拡張の追加オプション既定値を明示 ---
        opts.cutoff_forge_source_expand_n = 1
        opts.cutoff_forge_decay_mode = "off"
        opts.cutoff_forge_decay_strength = 0.5
        opts.cutoff_forge_exclude_tokens = ""
        opts.cutoff_forge_processing_targets = ""
        opts.cutoff_forge_teaware_mode = "off"
    except Exception:
        # 既定値の設定に失敗しても起動自体は継続
        pass

# UIを作る前に値を入れておく（初期表示に間に合わせる）
script_callbacks.on_before_ui(_force_enable_off)
