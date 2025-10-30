# Generation 領域（Txt2img/Img2img）に sd-forge-cutoff の操作パネルを出す
import gradio as gr
from modules import scripts
from modules.shared import opts

def _set_opt(key, value):
    try:
        setattr(opts, key, value)
    except Exception:
        pass

def _get_opt(key, default=None):
    try:
        return getattr(opts, key)
    except Exception:
        return default

class Script(scripts.Script):
    def title(self):
        return "Cutoff (sd-forge-cutoff)"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        with gr.Accordion("forge-Cutoff", open=False):

            # 1) Strength α（最上部）
            strength = gr.Slider(
                label="Strength α",
                minimum=0.0, maximum=1.0, step=0.01,
                value=_get_opt("cutoff_forge_strength", 0.5),
            )

            # 2) Target tokens（その下）
            tokens = gr.Textbox(
                label="Target tokens (comma separated)",
                value=_get_opt("cutoff_forge_targets", ""),
                placeholder="red, blue, green, etc...",
            )

            # 3) WARNING（その下）
            gr.Markdown(
                "**⚠️WARNING!!⚠️:** Changing **Target tokens** without modifying the prompt **will not** take effect because of the conditioning cache in Forge. "
                "To refresh, **adjust the batch size** or **briefly switch checkpoints and switch back**."
            )

            # --- Advanced options (4〜9) をアコーディオンに格納 ---
            with gr.Accordion("Advanced", open=False):
                # 4) Exclude/Specify ---
                excl = gr.Textbox(
                    value=_get_opt("cutoff_forge_exclude_tokens", ""), 
                    placeholder="indoors, background, etc...",
                    lines=1, label="Exclude from processing (CSV)"
                    )
                ponly = gr.Textbox(
                    value=_get_opt("cutoff_forge_processing_targets", ""), 
                    placeholder="shirt, skirt, etc...",
                    lines=1, label="Processing targets (CSV)"
                    )
                excl.change(_set_opt, inputs=[gr.Textbox(value="cutoff_forge_exclude_tokens", visible=False), excl], outputs=[])
                ponly.change(_set_opt, inputs=[gr.Textbox(value="cutoff_forge_processing_targets", visible=False), ponly], outputs=[])

                gr.Markdown("<hr style='border:none; border-top:1px solid transparent; margin:8px 0;'>")

                # 5) Source expansion (±N) ---
                with gr.Row():
                    src_n = gr.Slider(minimum=0, maximum=5, step=1,
                                      value=_get_opt("cutoff_forge_source_expand_n", 1),
                                      label="Source expansion (±N)")
                src_n.change(_set_opt, inputs=[gr.Textbox(value="cutoff_forge_source_expand_n", visible=False), src_n], outputs=[])

                # 6) Distance decay ---
                with gr.Row():
                    decay_mode = gr.Dropdown(choices=["off", "linear", "cosine"],
                                             value=_get_opt("cutoff_forge_decay_mode", "off"),
                                             label="Distance decay")
                    decay_strength = gr.Slider(minimum=0.0, maximum=1.0, step=0.05,
                                               value=_get_opt("cutoff_forge_decay_strength", 0.5),
                                               label="Decay strength")
                decay_mode.change(_set_opt, inputs=[gr.Textbox(value="cutoff_forge_decay_mode", visible=False), decay_mode], outputs=[])
                decay_strength.change(_set_opt, inputs=[gr.Textbox(value="cutoff_forge_decay_strength", visible=False), decay_strength], outputs=[])

                # 7) TE-aware ---
                teaware = gr.Dropdown(choices=["off", "safe_and"],
                                      value=_get_opt("cutoff_forge_teaware_mode", "off"),
                                      label="TE-aware")
                teaware.change(_set_opt, inputs=[gr.Textbox(value="cutoff_forge_teaware_mode", visible=False), teaware], outputs=[])

                # 8) Interpolation & Apply TE1/TE2（並べて表示）
                with gr.Row():
                    apply_te1 = gr.Checkbox(
                        label="Apply to TE1 (SD/SDXL)",
                        value=_get_opt("cutoff_forge_apply_te1", False),
                    )
                    apply_te2 = gr.Checkbox(
                        label="Apply to TE2 (SDXL)",
                        value=_get_opt("cutoff_forge_apply_te2", True),
                    )
                    method = gr.Radio(
                        label="Interpolation",
                        choices=["Lerp", "Slerp"],
                        value=_get_opt("cutoff_forge_method", "Slerp"),
                    )

                gr.Markdown("<hr style='margin:8px 0; border:none; border-top:1px solid rgba(255,255,255,0.15);'>")
                gr.Markdown("**For debug**")
                # 9) Sanity & Cutoff ratio
                with gr.Row():
                    sanity = gr.Checkbox(
                        label="Sanity test (for debug)",
                        value=_get_opt("cutoff_forge_sanity", False),  # 既定 False
                    )
                    # SanityがOFFのときは ratio を操作不可に
                    ratio_interactive = bool(_get_opt("cutoff_forge_sanity", False))
                    cut_ratio = gr.Slider(
                        label="Test ratio %",
                        minimum=0, maximum=50, step=1,
                        value=_get_opt("cutoff_forge_cut_ratio", 50),
                        interactive=ratio_interactive,
                    )
                
            # --- オプション即時反映 ---
            method.change(_set_opt, inputs=[gr.Textbox(value="cutoff_forge_method", visible=False), method], outputs=[])
            strength.change(_set_opt, inputs=[gr.Textbox(value="cutoff_forge_strength", visible=False), strength], outputs=[])
            tokens.change(_set_opt, inputs=[gr.Textbox(value="cutoff_forge_targets", visible=False), tokens], outputs=[])
            apply_te1.change(_set_opt, inputs=[gr.Textbox(value="cutoff_forge_apply_te1", visible=False), apply_te1], outputs=[])
            apply_te2.change(_set_opt, inputs=[gr.Textbox(value="cutoff_forge_apply_te2", visible=False), apply_te2], outputs=[])

            # Sanityの変更は: 1) オプション更新 2) Ratioの操作可否を更新
            def _toggle_ratio_interactive(s):
                return gr.update(interactive=bool(s))
            sanity.change(_set_opt, inputs=[gr.Textbox(value="cutoff_forge_sanity", visible=False), sanity], outputs=[])
            sanity.change(_toggle_ratio_interactive, inputs=[sanity], outputs=[cut_ratio])

            cut_ratio.change(_set_opt, inputs=[gr.Textbox(value="cutoff_forge_cut_ratio", visible=False), cut_ratio], outputs=[])

        return []
