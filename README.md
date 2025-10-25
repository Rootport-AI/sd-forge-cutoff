# sd-webui-cutoff for StabilityMatrix Forge (cacheless PoC)

- CTPE (__call__) で **毎回** target tokens を正規の tokenizer でサブ列一致 → 行インデックス抽出。
- 行は **揮発ストア（TE1/TE2）へ上書き**。キー・epoch なし。
- ConditionCrossAttn.process_cond / concat 直前で行を読み、**Lerp/Slerp** で PAD 近似へ補間上書き。

## UI
- Enable / Sanity / Interpolation / α / Cut ratio / Target tokens / Apply TE1&TE2 / Apply on concat
