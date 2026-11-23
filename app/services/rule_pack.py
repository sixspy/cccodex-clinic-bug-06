"""规则包钉定（甲路）：提交即物化包凭证落点入库，读侧改认物化包行并拒回刷。

徽标/包版本号/落点行三面一致才算对齐；任何一面拧花都挡旧包扫描。
"""
from __future__ import annotations

import hashlib
import json

from app.db import get_db
from app.services import audit as audit_svc
from app.services.errors import ServiceError

_SLUG = "rule_pack"
_OK = "规则包已亮"
_BAD = "包版本旧"
_TITLE = "规则包"
_OLD = "old_track"
_CUTOVER = "cutover_book"

_K_CHIP = f"{_SLUG}_panel_chip"
_K_TRUTH = f"{_SLUG}_truth"
_K_VERSION = f"{_SLUG}_version"
_K_COUNTER = f"{_SLUG}_counter"
_K_ACTIVE = f"{_SLUG}_active_read"
_K_FP = f"{_SLUG}_cutover_fp"
_K_REJECT = f"{_SLUG}_reject_refresh"


def _meta_get(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _meta_set(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (key, value),
    )


def _landing_key(fp: str) -> str:
    return f"{_SLUG}_pack_{fp}"


def _landing_row(conn, fp: str) -> dict | None:
    if not fp:
        return None
    raw = _meta_get(conn, _landing_key(fp), "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _aligned(conn) -> bool:
    """徽标、包版本号、落点行三面互相对得上才算对齐。"""
    if _meta_get(conn, _K_TRUTH, _BAD) != _OK:
        return False
    version = _meta_get(conn, _K_VERSION, "")
    if not version:
        return False
    if _meta_get(conn, _K_ACTIVE, _OLD) != _CUTOVER:
        return False
    if _meta_get(conn, _K_REJECT, "0") != "1":
        return False
    fp = _meta_get(conn, _K_FP, "")
    if fp in ("", "stale-fp"):
        return False
    landing = _landing_row(conn, fp)
    if not landing:
        return False
    return landing.get("version") == version and landing.get("fp") == fp


def panel_chip(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _OK if _aligned(conn) else _BAD


def truth_flag(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, _K_TRUTH, _BAD)


def pack_version(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, _K_VERSION, "")


def active_read_ref(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, _K_ACTIVE, _OLD)


def cutover_fp(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, _K_FP, "")


def reject_refresh(db_path: str | None = None) -> bool:
    with get_db(db_path) as conn:
        return _meta_get(conn, _K_REJECT, "0") == "1"


def pack_rows(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_pack_%",),
        ).fetchall()
        return [{"key": r["key"], "value": r["value"]} for r in rows]


def seed_skew(db_path: str | None = None) -> None:
    """初始台账：规则包尚未钉定，徽标如实亮旧版，绝不假绿。"""
    with get_db(db_path) as conn:
        _meta_set(conn, _K_CHIP, _BAD)
        _meta_set(conn, _K_TRUTH, _BAD)
        _meta_set(conn, _K_VERSION, "")
        _meta_set(conn, _K_COUNTER, "0")
        _meta_set(conn, _K_ACTIVE, _OLD)
        _meta_set(conn, _K_FP, "")
        _meta_set(conn, _K_REJECT, "0")


def snapshot(db_path: str | None = None) -> dict:
    """纯读快照：任何读取都不得回写、不得重置钉定状态。"""
    with get_db(db_path) as conn:
        stored_chip = _meta_get(conn, _K_CHIP, _BAD)
        truth = _meta_get(conn, _K_TRUTH, _BAD)
        version = _meta_get(conn, _K_VERSION, "")
        active = _meta_get(conn, _K_ACTIVE, _OLD)
        fp = _meta_get(conn, _K_FP, "")
        reject = _meta_get(conn, _K_REJECT, "0") == "1"
        rows = conn.execute(
            "SELECT COUNT(*) AS c FROM meta WHERE key LIKE ?",
            (f"{_SLUG}_pack_%",),
        ).fetchone()["c"]
        aligned = _aligned(conn)
    return {
        "title": _TITLE,
        "panel_chip": _OK if aligned else _BAD,
        "stored_chip": stored_chip,
        "truth": truth,
        "version": version,
        "pack_count": rows,
        "active_read": active,
        "cutover_fp": fp,
        "reject_refresh": reject,
        "aligned": aligned,
        "panel_pack_mismatch": stored_chip == _OK and not aligned,
    }


def dashboard(db_path: str | None = None) -> dict:
    snap = snapshot(db_path)
    return {
        "title": _TITLE,
        "chip": snap["panel_chip"],
        "truth": snap["truth"],
        "version": snap["version"],
        "aligned": snap["aligned"],
        "panel_pack_mismatch": snap["panel_pack_mismatch"],
        "pack_count": snap["pack_count"],
        "rows": pack_rows(db_path),
        "active_read": snap["active_read"],
        "cutover_fp": snap["cutover_fp"],
        "reject_refresh": snap["reject_refresh"],
        "label": "规则包钉定",
        "fate": _CUTOVER,
        "ok_chip": _OK,
        "bad_chip": _BAD,
    }


def commit_action(payload: dict | None = None, db_path: str | None = None) -> dict:
    """提交落台：马上写完入库，物化包凭证落点行与读轨切换同事务落库。

    争写加 BEGIN IMMEDIATE 锁，钉点各自落位不互踩；入库失败讲明白。
    """
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ServiceError("规则包提交载荷无效", 400)
    note = str(payload.get("note") or payload.get("ref") or "规则包钉定")[:80]
    try:
        with get_db(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            counter = int(_meta_get(conn, _K_COUNTER, "0") or "0") + 1
            version = f"RP-{counter:04d}"
            fp = hashlib.sha1(
                f"{version}|{counter}|{note}".encode("utf-8")
            ).hexdigest()[:12]
            landing = json.dumps(
                {"version": version, "fp": fp, "note": note, "counter": counter},
                ensure_ascii=False,
            )
            _meta_set(conn, _landing_key(fp), landing)
            _meta_set(conn, _K_COUNTER, str(counter))
            _meta_set(conn, _K_VERSION, version)
            _meta_set(conn, _K_TRUTH, _OK)
            _meta_set(conn, _K_CHIP, _OK)
            _meta_set(conn, _K_ACTIVE, _CUTOVER)
            _meta_set(conn, _K_FP, fp)
            _meta_set(conn, _K_REJECT, "1")
            _meta_set(conn, f"{_SLUG}_evt_{counter}", f"commit {version} fp={fp} {note}")
    except ServiceError:
        raise
    except Exception as exc:  # noqa: BLE001 — 入库失败要讲明白
        raise ServiceError(f"规则包入库失败: {exc}", 500) from exc
    audit_svc.write_event(
        "规则包提交", "rule_pack", counter, f"{version} fp={fp}", db_path=db_path
    )
    snap = snapshot(db_path)
    return {
        "ok": True,
        "chip": snap["panel_chip"],
        "title": _TITLE,
        "counter": counter,
        "version": version,
        "cutover_fp": fp,
        "active_read": snap["active_read"],
        "reject_refresh": snap["reject_refresh"],
        "pack_count": snap["pack_count"],
        "aligned": snap["aligned"],
        "message": f"{_TITLE}已落台入库：{version} 指纹 {fp}",
    }


def gate_allows_pipeline(db_path: str | None = None) -> bool:
    """旧包扫描闸门：只对齐才放行，没有旁路。"""
    with get_db(db_path) as conn:
        return _aligned(conn)


def require_pack_or_raise(db_path: str | None = None) -> None:
    with get_db(db_path) as conn:
        aligned = _aligned(conn)
    if not aligned:
        raise ServiceError(
            f"{_TITLE}未钉定对齐（徽标/包版本号/落点行对不上），已挡旧包扫描",
            409,
        )


def list_events(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_evt_%",),
        ).fetchall()
        return [{"key": r["key"], "note": r["value"]} for r in rows]


def record_event(note: str, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        counter = int(_meta_get(conn, _K_COUNTER, "0") or "0")
        _meta_set(conn, f"{_SLUG}_evt_{counter}_note", note or _TITLE)
    return dashboard(db_path)
