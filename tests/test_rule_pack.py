"""规则包假绿治理：徽标/包版本号/落点行三面一致才放行旧包扫描。

拍板甲路：规则包固化成物化包凭证（cutover_book），读侧改认物化包行并拒回刷；
乙路双写两轨不并存。
"""
from __future__ import annotations

import threading

import pytest

from app.db import get_db
from app.services import qc, reconcile, visits
from app.services import rule_pack, rule_pack_cutover
from app.services.errors import ServiceError


def _meta(db_path: str, key: str) -> str | None:
    with get_db(db_path) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def test_seeded_pack_not_aligned_and_gate_closed(db_path):
    snap = rule_pack.snapshot(db_path)
    assert snap["aligned"] is False
    # 徽标不得假绿：未钉定时必须亮“包版本旧”
    assert snap["panel_chip"] == "包版本旧"
    assert rule_pack.gate_allows_pipeline(db_path) is False
    with pytest.raises(ServiceError) as exc:
        rule_pack.require_pack_or_raise(db_path)
    assert exc.value.status_code == 409


def test_commit_lands_row_and_aligns(db_path):
    res = rule_pack.commit_action({"note": "首钉"}, db_path=db_path)
    assert res["aligned"] is True
    assert res["version"] == "RP-0001"
    assert res["cutover_fp"] not in ("", "stale-fp")
    # 落点入表：物化包凭证行必须能在本地库查到
    landing = _meta(db_path, f"rule_pack_pack_{res['cutover_fp']}")
    assert landing is not None
    assert "RP-0001" in landing
    snap = rule_pack.snapshot(db_path)
    assert snap["aligned"] is True
    assert snap["panel_chip"] == "规则包已亮"
    assert snap["version"] == "RP-0001"
    assert snap["active_read"] == "cutover_book"
    assert snap["reject_refresh"] is True
    assert rule_pack.gate_allows_pipeline(db_path) is True


def test_snapshot_read_does_not_reset_state(db_path):
    rule_pack.commit_action({"note": "钉定"}, db_path=db_path)
    for _ in range(3):
        rule_pack.dashboard(db_path)
        reconcile.dashboard(db_path)
        rule_pack.snapshot(db_path)
    snap = rule_pack.snapshot(db_path)
    assert snap["aligned"] is True
    assert snap["version"] == "RP-0001"


def test_badge_lit_without_landing_row_is_rejected(db_path):
    # 徽标独亮却缺规则包落点行 → 仍算驳回
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('rule_pack_panel_chip', '规则包已亮')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('rule_pack_truth', '规则包已亮')"
        )
    snap = rule_pack.snapshot(db_path)
    assert snap["aligned"] is False
    assert snap["panel_chip"] == "包版本旧"
    assert snap["panel_pack_mismatch"] is True
    assert rule_pack.gate_allows_pipeline(db_path) is False
    with pytest.raises(ServiceError):
        rule_pack.require_pack_or_raise(db_path)


def test_version_mismatch_blocks_old_scan(db_path):
    res = rule_pack.commit_action({"note": "钉定"}, db_path=db_path)
    assert rule_pack.gate_allows_pipeline(db_path) is True
    # 拧花：徽标/版本号还在，落点行被抹掉 → 立刻挡旧包扫描
    with get_db(db_path) as conn:
        conn.execute(
            "DELETE FROM meta WHERE key=?", (f"rule_pack_pack_{res['cutover_fp']}",)
        )
    assert rule_pack.gate_allows_pipeline(db_path) is False
    batch = next(b for b in visits.list_batches(db_path) if b["status"] == "采集中")
    with pytest.raises(ServiceError) as exc:
        visits.mock_crawl(batch["id"], count=1, db_path=db_path)
    assert exc.value.status_code == 409


def test_scans_blocked_until_pack_committed(db_path):
    batch = next(b for b in visits.list_batches(db_path) if b["status"] == "采集中")
    with pytest.raises(ServiceError) as exc:
        visits.mock_crawl(batch["id"], count=2, db_path=db_path)
    assert exc.value.status_code == 409
    with pytest.raises(ServiceError):
        qc.scan_batch(batch["id"], db_path=db_path)
    with pytest.raises(ServiceError):
        qc.scan_all_open(db_path=db_path)
    rule_pack.commit_action({"note": "钉定"}, db_path=db_path)
    crawled = visits.mock_crawl(batch["id"], count=2, db_path=db_path)
    assert crawled["created"] == 2
    scanned = qc.scan_batch(batch["id"], db_path=db_path)
    assert scanned["created"] >= 0


def test_reconcile_and_dashboard_do_not_paint_badge(db_path):
    reconcile.run_reconcile(db_path)
    reconcile.dashboard(db_path)
    snap = rule_pack.snapshot(db_path)
    assert snap["aligned"] is False
    assert snap["truth"] == "包版本旧"
    assert snap["panel_chip"] == "包版本旧"


def test_concurrent_commits_do_not_trample_pins(db_path):
    results: list[dict] = []
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            results.append(
                rule_pack.commit_action({"note": f"并发钉{i}"}, db_path=db_path)
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == 2
    # 两侧仓管争写也必须各自落钉，钉点不得互相踩掉
    assert sorted(r["version"] for r in results) == ["RP-0001", "RP-0002"]
    assert len({r["cutover_fp"] for r in results}) == 2
    snap = rule_pack.snapshot(db_path)
    assert snap["pack_count"] == 2
    assert snap["aligned"] is True
    assert snap["version"] == "RP-0002"


def test_commit_failure_is_explained(db_path):
    with get_db(db_path) as conn:
        conn.execute("DROP TABLE meta")
    with pytest.raises(ServiceError) as exc:
        rule_pack.commit_action({"note": "x"}, db_path=db_path)
    assert "入库失败" in exc.value.message


def test_cutover_book_requires_landing_then_records_pin(db_path):
    with pytest.raises(ServiceError):
        rule_pack_cutover.append_cutover(1, "空钉", db_path=db_path)
    res = rule_pack.commit_action({"note": "钉定"}, db_path=db_path)
    cut = rule_pack_cutover.append_cutover(7, "首钉入账", db_path=db_path)
    assert cut["cutover_fp"] == res["cutover_fp"]
    assert cut["active_read"] == "cutover_book"
    note = _meta(db_path, "rule_pack_cutover_note_7")
    assert note is not None
    assert res["cutover_fp"] in note
    assert "RP-0001" in note


def test_dashboard_reports_version_and_landing_count(db_path):
    dash = rule_pack.dashboard(db_path)
    assert dash["chip"] == "包版本旧"
    assert dash["version"] == ""
    assert dash["pack_count"] == 0
    rule_pack.commit_action({"note": "钉定"}, db_path=db_path)
    dash = rule_pack.dashboard(db_path)
    assert dash["chip"] == "规则包已亮"
    assert dash["version"] == "RP-0001"
    assert dash["pack_count"] == 1
    assert dash["aligned"] is True
    assert dash["fate"] == "cutover_book"
