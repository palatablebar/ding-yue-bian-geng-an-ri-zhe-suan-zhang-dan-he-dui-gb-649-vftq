"""M3 字段归一：千分位、全角、三位小数、空值哨兵、期间端点的原因码。"""
from __future__ import annotations

from decimal import Decimal

from app.modules.m3_quality import rules


def test_fullwidth_digits_normalized():
    # TRAP-06：全角数字不能靠 float() 硬转
    parsed = rules.normalize_money("２４００．００")
    assert parsed.value == Decimal("2400.00")
    assert "R_PRICE_FULLWIDTH" in parsed.flags
    assert parsed.code is None


def test_thousands_separator_normalized():
    # TRAP-06：千分位先剥再转 Decimal，不截断也不报错
    parsed = rules.normalize_money("1,200.00")
    assert parsed.value == Decimal("1200.00")
    assert "R_PRICE_THOUSANDS" in parsed.flags
    assert rules.normalize_money("￥1,200.00 元").value == Decimal("1200.00")


def test_three_decimal_price_kept_and_flagged(run_id, store):
    # TRAP-24 的前置：三位小数价保留全精度，只在记账时按分四舍五入
    subs = {row["sub_id"]: row for row in store.list_subscriptions(run_id)}
    assert Decimal(subs["SUB-1009"]["monthly"]) == Decimal("1200.005")
    assert "R_PRICE_PRECISION" in subs["SUB-1009"]["flags"]
    invoices = {row["sub_id"]: row for row in store.list_invoices(run_id)}
    assert invoices["SUB-1009"]["total_cents"] == 120001


def test_sentinel_price_missing():
    for text in ("", "-", "N/A", "未知", "—"):
        parsed = rules.normalize_money(text)
        assert parsed.value is None
        assert parsed.code == "R_PRICE_MISSING"
    assert rules.normalize_money("12O0.00").code == "R_PRICE_FORMAT"


def test_reversed_and_zero_period_codes(run_id, store):
    # TRAP-23 的反例：区间倒置或零长度都必须给原因码，不能算出负数天
    codes = {row["code"] for row in store.list_quarantine(run_id)}
    assert "R_PERIOD_REVERSED" in codes
    assert rules.normalize_date("2026-02-30").code == "R_DATE_FORMAT"
    assert rules.normalize_date("2026/2/1").value.isoformat() == "2026-02-01"
    assert rules.normalize_date("", ).value is None


def test_state_and_kind_normalized():
    assert rules.normalize_state("试用期").value == "trial"
    assert rules.normalize_state("待激活").code == "R_STATE_UNKNOWN"
    assert rules.normalize_kind("降级").value == "downgrade"
    assert rules.normalize_kind("续费").code == "R_CHANGE_KIND"
    # 暂停与取消一律按 0 计价，恢复允许沿用旧价
    assert rules.change_price("pause", "2400.00").value == Decimal("0")
    assert rules.change_price("resume", "").value is None
