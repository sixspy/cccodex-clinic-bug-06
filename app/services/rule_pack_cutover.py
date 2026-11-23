"""规则包切流账册（甲路）：把当刻物化包凭证钉入账册，锁指纹并拒回刷。"""
from __future__ import annotations

from app.db import get_db
from app.services import audit as audit_svc
from app.services.errors import ServiceError
from app.services.rule_pack import (
    _K_ACTIVE,
    _K_FP,
    _K_REJECT,
    _K_VERSION,
    _CUTOVER,
    _landing_row,
    _meta_get,
    _meta_set,
    dashboard,
)

_SLUG = "rule_pack"
_TITLE = "规则包"


def append_cutover(ref_id: int, note: str, db_path: str | None = None) -> dict:
    """钉定一条账册：必须已有落点入库的物化包凭证，空钉驳回。"""
    ref_id = int(ref_id or 0)
    note = (note or _TITLE)[:120]
    with get_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        fp = _meta_get(conn, _K_FP, "")
        version = _meta_get(conn, _K_VERSION, "")
        if fp in ("", "stale-fp") or not _landing_row(conn, fp):
            raise ServiceError(f"{_TITLE}尚未落点入库，不能钉定切流账册", 409)
        _meta_set(
            conn,
            f"{_SLUG}_cutover_note_{ref_id}",
            f"{note}|version={version}|fp={fp}",
        )
        _meta_set(conn, _K_ACTIVE, _CUTOVER)
        _meta_set(conn, _K_REJECT, "1")
    audit_svc.write_event(
        "规则包切流钉定",
        "rule_pack",
        ref_id,
        f"version={version} fp={fp} {note}",
        db_path=db_path,
    )
    snap = dashboard(db_path)
    return {
        "ref_id": ref_id,
        "note": note,
        "version": version,
        "panel": snap["chip"],
        "truth": snap["truth"],
        "active_read": snap["active_read"],
        "cutover_fp": fp,
        "reject_refresh": snap["reject_refresh"],
        "aligned": snap["aligned"],
    }


def cutover_rows(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_cutover_note_%",),
        ).fetchall()
        return [{"key": r["key"], "value": r["value"]} for r in rows]


def board(db_path: str | None = None) -> dict:
    dash = dashboard(db_path)
    dash["cutover"] = cutover_rows(db_path)
    dash["fate"] = _CUTOVER
    return dash
