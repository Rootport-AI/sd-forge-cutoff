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
        apply_te1=True,
        apply_te2=True,
        exclude_tokens="",
        processing_targets="",
        source_expand_n=1,
#        decay_mode="off",
#        decay_strength=0.5,
#        teaware_mode="off",
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
                # 4) Source expansion (±N) ---
                with gr.Row():
                    src_n = gr.Slider(minimum=0, maximum=5, step=1,
                                      value=_runtime_defaults()["source_expand_n"],
                                      label="Source expansion (±N)")

                # 5) Exclude/Specify ---
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

#                # 6) Distance decay ---
#                with gr.Row():
#                    decay_mode = gr.Dropdown(choices=["off", "linear", "cosine"],
#                                             value=_runtime_defaults()["decay_mode"],
#                                             label="Distance decay")
#                    decay_strength = gr.Slider(minimum=0.0, maximum=1.0, step=0.05,
#                                               value=_runtime_defaults()["decay_strength"],
#                                               label="Decay strength")

#                # 7) TE-aware ---
#                teaware = gr.Dropdown(choices=["off", "safe_and"],
#                                      value=_runtime_defaults()["teaware_mode"],
#                                      label="TE-aware")

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
                
                gr.Markdown("<hr style='border:none; border-top:1px solid transparent; margin:8px 0;'>")
                with gr.Accordion("❓ Help", open=False):
                    gr.Markdown( 
                        """ <div style="font-size: 0.95em; opacity: .95">
                        
                        > #### ℹ️ Cutoff — Advanced Help
                        > **What this does:** Cutoff “neutralizes” parts of the prompt **other than the specified Target tokens** to reduce color bleed and concept mixing. The options below control **what to protect** and **what to neutralize**.

                        **Source expansion (±N)**  
                        Protects tokens **near the target** (within ±N tokens **in the same phrase**).  
                        Example: When the target token is `blue`: with `blue hair` and N=0, `hair` is also neutralized, so the hair color becomes pale. Setting N=1 protects up to `hair`. With `blue long hair` and N=2, the tokens around `blue` (i.e., `long hair`) are also kept intact.

                        **Exclude from processing (CSV)**  
                        Items listed here are **never neutralized** (always protected).  
                        Example: adding `background, outdoors, skin` keeps background and skin out of the neutralization set.

                        **Processing targets (CSV)**  
                        Neutralizes **only** the parts **listed here** (filters the scope). Leave empty to target the whole prompt.  
                        You **must** enter tokens that are actually affected by the Target tokens. If the listed items aren’t under the Target’s influence, no neutralization will be found and the output will look similar to **Enable=off**.

                        **Apply to TE1 / TE2**  
                        Choose which text encoder to apply to.  
                        - **TE1** — layout / composition–oriented (turning this ON can further suppress pose/layout shifts).  
                        - **TE2** — detail / color–oriented (the main battleground for color bleed; usually recommended ON).

                        **Interpolation (Lerp / Slerp)**  
                        How the neutralization is mixed.  
                        - **Slerp** — more robust for stronger effects (recommended).  
                        - **Lerp** — lighter and linear; use when you want a milder effect.

                        > **Tips**
                        > - If the effect feels weak, try **Strength 0.6–0.7** or list **multiple Processing targets**.  
                        > - If nothing changes, check **compatibility between the Target color and the part** (e.g., if the umbrella has no `pink`, it won’t help).  
                        > - Reminder: with the same prompt, changing **Target tokens only** **will not** trigger re-computation. Refresh by tweaking **Batch size ±1**, or **temporarily switch checkpoints and switch back**.
                        </div>"""
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
                
            # --- セッション専用: Stateを更新し vctx へ反映（positional-only） ---
            def _upd_state(key):
                def _f(stv, val):
                    stv[key] = val
                    _push_runtime(stv)
                    return stv
                return _f

            method.change(_upd_state("method"),           inputs=[st, method],   outputs=[st], show_progress=False)
            strength.change(_upd_state("strength"),       inputs=[st, strength], outputs=[st], show_progress=False)
            tokens.change(_upd_state("targets"),          inputs=[st, tokens],   outputs=[st], show_progress=False)
            apply_te1.change(_upd_state("apply_te1"),     inputs=[st, apply_te1], outputs=[st], show_progress=False)
            apply_te2.change(_upd_state("apply_te2"),     inputs=[st, apply_te2], outputs=[st], show_progress=False)

            # Sanityの変更は: 1) オプション更新 2) Ratioの操作可否を更新
            def _toggle_ratio_interactive(s):
                return gr.update(interactive=bool(s))
            sanity.change(_upd_state("sanity"), inputs=[st, sanity], outputs=[st], show_progress=False)
            sanity.change(_toggle_ratio_interactive, inputs=[sanity], outputs=[cut_ratio])

            cut_ratio.change(     _upd_state("cut_ratio"),        inputs=[st, cut_ratio],    outputs=[st], show_progress=False)
            excl.change(          _upd_state("exclude_tokens"),   inputs=[st, excl],         outputs=[st], show_progress=False)
            ponly.change(         _upd_state("processing_targets"), inputs=[st, ponly],      outputs=[st], show_progress=False)
            src_n.change(         _upd_state("source_expand_n"),  inputs=[st, src_n],        outputs=[st], show_progress=False)
#            decay_mode.change(    _upd_state("decay_mode"),       inputs=[st, decay_mode],   outputs=[st], show_progress=False)
#            decay_strength.change(_upd_state("decay_strength"),   inputs=[st, decay_strength], outputs=[st], show_progress=False)
#            teaware.change(       _upd_state("teaware_mode"),     inputs=[st, teaware],      outputs=[st], show_progress=False)

            # ----------------------------------------------
            # 起動直後ワンショット：UI→runtime 同期（副作用：vctx.runtime_cfg を一度だけ確定）
            # ここで取得する .value は、ui-config.json に保存されている既定があれば
            # それが反映された“現在の表示値”です。
            def _init_sync():
                try:
                    cfg = dict(
                        method            = method.value,
                        strength          = strength.value,
                        targets           = tokens.value,
                        apply_te1         = bool(apply_te1.value),
                        apply_te2         = bool(apply_te2.value),
                        exclude_tokens    = excl.value,
                        processing_targets= ponly.value,
                        source_expand_n   = int(src_n.value),
#                        decay_mode        = decay_mode.value,
#                        decay_strength    = float(decay_strength.value),
#                        teaware_mode      = teaware.value,
                        sanity            = bool(sanity.value),
                        cut_ratio         = int(cut_ratio.value),
                    )
                    _push_runtime(cfg)
                except Exception:
                    # 同期に失敗しても起動は継続（以後の .change で逐次反映される）
                    pass
            _init_sync()

        return []