# Generation 領域（Txt2img/Img2img）に sd-forge-cutoff の操作パネルを出す
import gradio as gr
from modules import scripts
from modules.shared import opts
try:
    from scripts.forge_cutoff import context_volatile as vctx
except Exception:
    from forge_cutoff import context_volatile as vctx

def _runtime_defaults():
    # セッション既定（永続しない）
    return dict(
        method="Slerp",
        strength=0.5,
        targets="",
        apply_te1=False,
        apply_te2=True,
        exclude_tokens="",
        processing_targets="",
        source_expand_n=1,
        decay_mode="off",
        decay_strength=0.5,
        teaware_mode="off",
        sanity=False,
        cut_ratio=50,
    )

def _push_runtime(cfg):
    """UI側stateから context_volatile に反映（セッション限定）。"""
    try:
        vctx.set_runtime(cfg)
    except Exception:
        pass

class Script(scripts.Script):
    def title(self):
        return "Cutoff (sd-forge-cutoff)"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        with gr.Accordion("forge-Cutoff", open=False):
            # セッション用の初期状態
            st = gr.State(_runtime_defaults())

            # 1) Strength α（最上部）
            strength = gr.Slider(
                label="Strength α",
                minimum=0.0, maximum=1.0, step=0.01,
                value=_runtime_defaults()["strength"],
            )

            # 2) Target tokens（その下）
            tokens = gr.Textbox(
                label="Target tokens (comma separated)",
                value=_runtime_defaults()["targets"],
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
                    value=_runtime_defaults()["exclude_tokens"], 
                    placeholder="indoors, background, etc...",
                    lines=1, label="Exclude from processing (CSV)"
                    )
                ponly = gr.Textbox(
                    value=_runtime_defaults()["processing_targets"], 
                    placeholder="shirt, skirt, etc...",
                    lines=1, label="Processing targets (CSV)"
                    )

                gr.Markdown("<hr style='border:none; border-top:1px solid transparent; margin:8px 0;'>")

                # 5) Source expansion (±N) ---
                with gr.Row():
                    src_n = gr.Slider(minimum=0, maximum=5, step=1,
                                      value=_runtime_defaults()["source_expand_n"],
                                      label="Source expansion (±N)")

                # 6) Distance decay ---
                with gr.Row():
                    decay_mode = gr.Dropdown(choices=["off", "linear", "cosine"],
                                             value=_runtime_defaults()["decay_mode"],
                                             label="Distance decay")
                    decay_strength = gr.Slider(minimum=0.0, maximum=1.0, step=0.05,
                                               value=_runtime_defaults()["decay_strength"],
                                               label="Decay strength")

                # 7) TE-aware ---
                teaware = gr.Dropdown(choices=["off", "safe_and"],
                                      value=_runtime_defaults()["teaware_mode"],
                                      label="TE-aware")

                # 8) Interpolation & Apply TE1/TE2（並べて表示）
                with gr.Row():
                    apply_te1 = gr.Checkbox(
                        label="Apply to TE1 (SD/SDXL)",
                        value=_runtime_defaults()["apply_te1"],
                    )
                    apply_te2 = gr.Checkbox(
                        label="Apply to TE2 (SDXL)",
                        value=_runtime_defaults()["apply_te2"],
                    )
                    method = gr.Radio(
                        label="Interpolation",
                        choices=["Lerp", "Slerp"],
                        value=_runtime_defaults()["method"],
                    )

                gr.Markdown("<hr style='margin:8px 0; border:none; border-top:1px solid rgba(255,255,255,0.15);'>")
                gr.Markdown("**For debug**")
                # 9) Sanity & Cutoff ratio
                with gr.Row():
                    sanity = gr.Checkbox(
                        label="Sanity test (for debug)",
                        value=_runtime_defaults()["sanity"],
                    )
                    # SanityがOFFのときは ratio を操作不可に
                    ratio_interactive = bool(_runtime_defaults()["sanity"])
                    cut_ratio = gr.Slider(
                        label="Test ratio %",
                        minimum=0, maximum=50, step=1,
                        value=_runtime_defaults()["cut_ratio"],
                        interactive=ratio_interactive,
                    )
                
            # --- セッション専用: Stateを更新し vctx へ反映 ---
            def _merge(stv, **kw):
                stv.update(kw); _push_runtime(stv); return stv
            method.change(_merge, inputs=[st], outputs=[st], show_progress=False, _js=None, kwargs={"method": gr.update()})
            strength.change(_merge, inputs=[st], outputs=[st], show_progress=False, _js=None, kwargs={"strength": gr.update()})
            tokens.change(_merge, inputs=[st], outputs=[st], show_progress=False, _js=None, kwargs={"targets": gr.update()})
            apply_te1.change(_merge, inputs=[st], outputs=[st], show_progress=False, _js=None, kwargs={"apply_te1": gr.update()})
            apply_te2.change(_merge, inputs=[st], outputs=[st], show_progress=False, _js=None, kwargs={"apply_te2": gr.update()})

            # Sanityの変更は: 1) オプション更新 2) Ratioの操作可否を更新
            def _toggle_ratio_interactive(s):
                return gr.update(interactive=bool(s))
            sanity.change(_merge, inputs=[st], outputs=[st], show_progress=False, _js=None, kwargs={"sanity": gr.update()})
            sanity.change(_toggle_ratio_interactive, inputs=[sanity], outputs=[cut_ratio])

            cut_ratio.change(_merge, inputs=[st], outputs=[st], show_progress=False, _js=None, kwargs={"cut_ratio": gr.update()})
            excl.change(_merge, inputs=[st], outputs=[st], show_progress=False, _js=None, kwargs={"exclude_tokens": gr.update()})
            ponly.change(_merge, inputs=[st], outputs=[st], show_progress=False, _js=None, kwargs={"processing_targets": gr.update()})
            src_n.change(_merge, inputs=[st], outputs=[st], show_progress=False, _js=None, kwargs={"source_expand_n": gr.update()})
            decay_mode.change(_merge, inputs=[st], outputs=[st], show_progress=False, _js=None, kwargs={"decay_mode": gr.update()})
            decay_strength.change(_merge, inputs=[st], outputs=[st], show_progress=False, _js=None, kwargs={"decay_strength": gr.update()})
            teaware.change(_merge, inputs=[st], outputs=[st], show_progress=False, _js=None, kwargs={"teaware_mode": gr.update()})

        return []