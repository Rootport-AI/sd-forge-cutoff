# 揮発ストア：都度検出した行インデックスを TE ごとに上書き保存するだけ
# 永続化・キー・epoch なし

from typing import Dict, List, Optional

_state: Dict[str, object] = {
    # rows_by_enc: {"TE1": [int...], "TE2": [int...] }  ※従来の「ターゲット行（Source近傍）」は互換のため保持
    "rows_by_enc": {"TE1": [], "TE2": []},

    # Victim 行（= 中立化の適用対象）を別に保持
    "rows_victim_by_enc": {"TE1": [], "TE2": []},

    # 現在の targets（正規化済み CSV 文字列；観測用）
    "targets_canon": "",

    # ダミープロンプト（string）。エンコードは L3 でオンデマンド
    "dummy_text_by_enc": {"TE1": "", "TE2": ""},

    # 直近の enc_tag を控える（安全のため）
    "last_enc_tag": "",
}

def set_rows(enc_tag: str, rows: List[int], targets_canon: str):
    enc = "TE1" if str(enc_tag or "") == "TE1" else "TE2"
    _state["rows_by_enc"][enc] = list(rows or [])
    _state["targets_canon"] = str(targets_canon or "")
    _state["last_enc_tag"] = enc

def set_rows_victim(enc_tag: str, rows_victim: List[int]):
    enc = "TE1" if str(enc_tag or "") == "TE1" else "TE2"
    _state["rows_victim_by_enc"][enc] = list(rows_victim or [])

def set_dummy_text(enc_tag: str, dummy_text: str):
    enc = "TE1" if str(enc_tag or "") == "TE1" else "TE2"
    _state["dummy_text_by_enc"][enc] = str(dummy_text or "")

def get_rows(enc_tag: str) -> List[int]:
    enc = "TE1" if str(enc_tag or "") == "TE1" else "TE2"
    return list(_state["rows_by_enc"].get(enc, []) or [])

def get_rows_victim(enc_tag: str) -> List[int]:
    enc = "TE1" if str(enc_tag or "") == "TE1" else "TE2"
    return list(_state["rows_victim_by_enc"].get(enc, []) or [])

def get_dummy_text(enc_tag: str) -> str:
    enc = "TE1" if str(enc_tag or "") == "TE1" else "TE2"
    return str(_state["dummy_text_by_enc"].get(enc, "") or "")

def get_targets_canon() -> str:
    return str(_state.get("targets_canon", "") or "")

def get_last_enc_tag() -> str:
    return str(_state.get("last_enc_tag", "") or "")

def clear():
    _state["rows_by_enc"] = {"TE1": [], "TE2": []}
    _state["rows_victim_by_enc"] = {"TE1": [], "TE2": []}
    _state["targets_canon"] = ""
    _state["dummy_text_by_enc"] = {"TE1": "", "TE2": ""}
    _state["last_enc_tag"] = ""
