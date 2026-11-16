# 深度登记 subbill 订阅变更按日折算与账单核对

- 规模：中型（7 个功能模块，74–80 个文件，测试 ≥53）
- 核心规则：期间 `[start, end)` 的实际天数做分母，变更切段后「预缴整期 − 未用额度抵扣 + 新价补收」，尾差按最大余额法分到 0.01
- 使用者与工作流：SaaS 计费运营每月把订阅与变更两份导出文件拖进系统，先看隔离区确认哪些行不可用，再逐张核账单，最后导出账单与运行清单归档

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 订阅采信 | 选两份样例文件采信，看编码与列数诊断 | POST /api/subscriptions/import | `app/modules/m1_ingest/reader.py` `app/modules/m1_ingest/columns.py` `app/modules/m1_ingest/service.py` | `tests/test_ingest.py` `tests/test_ingest_columns.py` |
| M2 期间日历 | 查每个订阅的期间天数、闰日与半开区间 | GET /api/calendar | `app/modules/m2_calendar/days.py` `app/modules/m2_calendar/halfopen.py` | `tests/test_calendar.py` `tests/test_calendar_dst.py` |
| M3 质量隔离 | 看原因码分布、原始行号与原值，导出隔离 CSV | GET /api/quarantine | `app/modules/m3_quality/rules.py` `app/modules/m3_quality/quarantine.py` | `tests/test_quality.py` `tests/test_quality_money.py` |
| M4 按日折算 | 看每段日价与金额，必要时重算 | GET /api/proration | `app/modules/m4_proration/prorate.py` `app/modules/m4_proration/rounding.py` | `tests/test_proration.py` `tests/test_rounding.py` |
| M5 变更抵扣 | 看变更序列、被替代关系与抵扣行 | GET /api/changes | `app/modules/m5_changes/segments.py` `app/modules/m5_changes/credit.py` | `tests/test_changes.py` `tests/test_credit.py` |
| M6 账单对账 | 出账、点行看明细、核对四本账 | GET /api/invoices | `app/modules/m6_invoices/invoice.py` `app/modules/m6_invoices/reconcile.py` | `tests/test_invoices.py` `tests/test_reconcile.py` |
| M7 导出 | 导出账单 CSV、分段 CSV、运行清单 JSON | GET /api/export/invoices.csv | `app/modules/m7_export/csv_out.py` `app/modules/m7_export/manifest_out.py` | `tests/test_export.py` `tests/test_export_manifest.py` |

端到端与不变量分别由 `tests/test_e2e.py`、`tests/test_invariants.py` 固定。

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-05 | 订阅行多出一列（导出时手工加了备注） | 静默补空或错列，把备注当状态 | 列数与表头严格等长，不等即隔离并记列数事实 | `app/modules/m1_ingest/columns.py` | `tests/test_ingest_columns.py::test_column_count_mismatch_quarantined` |
| TRAP-06 | 月价出现 `1,200.00` 与 `２４００．００` | `float()` 抛错或把全角当 0 | 先剥千分位与全角，再转 Decimal，归一事实留 info 标记 | `app/modules/m3_quality/rules.py` | `tests/test_quality_money.py::test_thousands_separator_normalized`、`tests/test_quality_money.py::test_fullwidth_digits_normalized` |
| TRAP-10 | 1200 元分 28 天逐日累加 | float 累加出现 1199.9999999 | 全程 Decimal（34 位上下文），只在记账时量化到分 | `app/modules/m4_proration/prorate.py` | `tests/test_proration.py::test_invoice_totals_match_expected`、`tests/test_invariants.py::test_rerun_same_rows_and_totals` |
| TRAP-11 | 同一瞬间写成 `Z` 与 `+08:00` | 两个写法落进不同本地日，切段错位 | 先归一 UTC，再按订阅时区取本地日 | `app/modules/m3_quality/rules.py`、`app/modules/m2_calendar/halfopen.py` | `tests/test_calendar_dst.py::test_same_instant_two_spellings` |
| TRAP-12 | 海外账户的本地时刻落在夏令时重叠段或跳过段 | 直接 `replace(tzinfo=…)` 得到错瞬间，或抛异常 | 重叠取较早一次并标 `R_DST_AMBIGUOUS`，跳过顺延并标 `R_DST_GAP` | `app/modules/m2_calendar/halfopen.py` | `tests/test_calendar_dst.py::test_dst_ambiguous_takes_earlier_offset`、`tests/test_calendar_dst.py::test_dst_gap_shifts_forward` |
| TRAP-13 | 变更行乱序到达（后生效的行先出现） | 按文件顺序切段，段边界错乱 | 按 (生效时刻, 变更号) 排序，迟到行仍生效并标 `R_LATE_CHANGE` | `app/modules/m3_quality/service.py` | `tests/test_changes.py::test_late_change_applied_and_flagged` |
| TRAP-14 | 同一订阅号两行月价不同 | 后写覆盖，账单金额随文件顺序变 | 保留行号最小的一条，另一条进隔离区，保留事实写进 detail | `app/modules/m3_quality/service.py` | `tests/test_quality.py::test_duplicate_key_conflict_keeps_first_row`、`tests/test_ingest_columns.py::test_duplicate_identical_row_dropped` |
| TRAP-18 | 0 字节文件、只有表头、全是空行 | 一律「成功导入 0 行」，对账看不出来 | 三种空态三个原因码，数据行全部计入行数账 | `app/modules/m1_ingest/reader.py` | `tests/test_ingest.py::test_empty_states_distinct`、`tests/test_reconcile.py::test_rows_ledger_identity` |
| TRAP-23 | 期间端点归属与相邻段接缝 | 两端都算，重复计一天 | 半开 `[start, end)`，相邻段 end 等于下段 start | `app/modules/m5_changes/segments.py`、`app/modules/m2_calendar/days.py` | `tests/test_calendar.py::test_adjacent_segments_cover_period`、`tests/test_changes.py::test_change_on_period_start_zero_day_segment` |
| TRAP-24 | 抵扣行、补收行各自四舍五入 | 分完合计比总额多 1 分 | 最大余额法把差额补到小数余额最大的分量，负数抵扣同样成立 | `app/modules/m4_proration/rounding.py` | `tests/test_rounding.py::test_largest_remainder_keeps_total`、`tests/test_credit.py::test_component_cents_sum_to_invoice` |
| TRAP-25 | 同一订阅同一时刻两条变更 | 取到哪条看文件顺序，重跑结果会变 | 同日只让 (生效时刻, 变更号) 最小的一条生效，其余标 `R_CHANGE_OVERLAP` 并记替代关系 | `app/modules/m3_quality/service.py`、`app/modules/m5_changes/segments.py` | `tests/test_changes.py::test_same_instant_overlap_deterministic`、`tests/test_invariants.py::test_change_order_independence` |

## 对账规则

- 行数账：输入数据行 = 可用订阅 + 可用变更 + 隔离行 + 丢弃重复行 + 空白行 + 重复表头
- 期间天数账：账单期间天数 = 计费天数 + 免费/暂停天数
- 金额账：分段合计（分） = 抵扣合计（分） + 账单额合计（分）
- 出账账：账单行数 = 有分段的账单数
- 恒等式：预缴整期 − Σ抵扣 + Σ补收 = Σ(各段费率 × 段天数)

## 已知不覆盖

- 只读 CSV 导出文件，不解析 xlsx；浏览器下载的表格需先另存为 CSV。
- 汇率与多币种未做：样例统一人民币，币种列固定 `CNY`。
- 变更只支持整日生效：生效时刻按本地日 0 点取整并标记，不做小时级折算。
- 账期只支持自然月：跨月、跨年区间可算天数，但界面上不提供自定义账期模板。
- 未做并发写保护：单实例 SQLite，写入串行；多实例部署需要改为外部数据库。
