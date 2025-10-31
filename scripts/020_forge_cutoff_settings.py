# Settingsタブに sd-forge-cutoff のグローバル設定を追加（Quicksettingsからも参照可能）
import gradio as gr
from modules import shared

def on_ui_settings():
    section = ("sd-forge-cutoff", "sd-forge-cutoff")

    # Enable: 既定 OFF（Quicksettingsに残す唯一の永続設定）
    shared.opts.add_option("cutoff_forge_enable", shared.OptionInfo(
        default=False, label="Enable (sd-forge-cutoff)", section=section))

    return []

try:
    import modules.script_callbacks as script_callbacks
    script_callbacks.on_ui_settings(on_ui_settings)
except Exception:
    pass
