"""规则包读轨审计：只留甲路切流账册（物化包凭证）一侧引用，乙路双写已拆。"""
from __future__ import annotations

from app.services.rule_pack import list_events
from app.services.rule_pack_cutover import board as cutover_board


def audit_summary(db_path: str | None = None) -> dict:
    return {
        "title": "规则包审计",
        "events": list_events(db_path),
        "cutover": cutover_board(db_path),
        "fate": "cutover_book",
    }
