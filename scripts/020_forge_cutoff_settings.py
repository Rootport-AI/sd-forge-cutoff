# Settingsタブに sd-forge-cutoff のグローバル設定を追加（Quicksettingsからも参照可能）
import gradio as gr
from modules import shared

def on_ui_settings():
    section = ("sd-forge-cutoff", "sd-forge-cutoff")

    # Enable: 既定 OFF（起動時にも 005 で毎回 OFF に戻す）
    shared.opts.add_option("cutoff_forge_enable", shared.OptionInfo(
        default=False, label="Enable (sd-forge-cutoff)", section=section))

    # Sanity: デフォルト OFF
    shared.opts.add_option("cutoff_forge_sanity", shared.OptionInfo(
        default=False, label="Sanity demo (tail rows neutralization; OFF by default)", section=section))

    # Interpolation（Slerp を既定）
    shared.opts.add_option("cutoff_forge_method", shared.OptionInfo(
        default="Slerp", label="Interpolation", component=gr.Radio,
        component_args={"choices": ["Lerp", "Slerp"]}, section=section))

    # Strength α（既定 0.5・step 0.01）
    shared.opts.add_option("cutoff_forge_strength", shared.OptionInfo(
        default=0.5, label="Strength α (0.0–1.0)", component=gr.Slider,
        component_args={"minimum": 0.0, "maximum": 1.0, "step": 0.01}, section=section))

    # Target tokens
    shared.opts.add_option("cutoff_forge_targets", shared.OptionInfo(
        default="", label="Target tokens (comma separated)", section=section))

    # Cutoff ratio（Sanity用）
    shared.opts.add_option("cutoff_forge_cut_ratio", shared.OptionInfo(
        default=50, label="Cutoff ratio % (tail rows; Sanity only)", component=gr.Slider,
        component_args={"minimum": 0, "maximum": 50, "step": 1}, section=section))

    # TE適用
    shared.opts.add_option("cutoff_forge_apply_te1", shared.OptionInfo(
        default=False, label="Apply to TE1 (SD/SDXL)", section=section))
    shared.opts.add_option("cutoff_forge_apply_te2", shared.OptionInfo(
        default=True, label="Apply to TE2 (SDXL)", section=section))

    # Debug log（既定OFF）
    shared.opts.add_option("cutoff_forge_debug_log", shared.OptionInfo(
        default=False, label="Debug log (verbose internal logs; OFF by default)", section=section))

    # --- NEW: Source 拡張（±N） ---
    shared.opts.add_option("cutoff_forge_source_expand_n", shared.OptionInfo(
        default=1, label="Source expansion (±N tokens)", component=gr.Slider,
        component_args={"minimum": 0, "maximum": 5, "step": 1}, section=section))

    # --- NEW: 距離減衰（Off/Linear/Cosine）＋強度 ---
    shared.opts.add_option("cutoff_forge_decay_mode", shared.OptionInfo(
        default="off", label="Distance decay mode", component=gr.Radio,
        component_args={"choices": ["off", "linear", "cosine"]}, section=section))
    shared.opts.add_option("cutoff_forge_decay_strength", shared.OptionInfo(
        default=0.5, label="Decay strength (0..1)", component=gr.Slider,
        component_args={"minimum": 0.0, "maximum": 1.0, "step": 0.05}, section=section))

    # --- NEW: Exclude/Specify（明示指定） ---
    shared.opts.add_option("cutoff_forge_exclude_tokens", shared.OptionInfo(
        default="", label="Exclude from processing (CSV)", section=section))
    shared.opts.add_option("cutoff_forge_processing_targets", shared.OptionInfo(
        default="", label="Processing targets (CSV)", section=section))

    # --- NEW: TE-aware ---
    shared.opts.add_option("cutoff_forge_teaware_mode", shared.OptionInfo(
        default="off", label="TE-aware mode", component=gr.Radio,
        component_args={"choices": ["off", "safe_and"]}, section=section))

    return []

try:
    import modules.script_callbacks as script_callbacks
    script_callbacks.on_ui_settings(on_ui_settings)
except Exception:
    pass
