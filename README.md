# subbill 订阅变更按日折算与账单核对

面向 SaaS 计费运营：每月拿到订阅与变更两份导出文件，按实际天数折算、把降配未用额度抵扣掉、
逐张核出账单并导出可复算的运行清单。

## 能力

- 采信脏 CSV：编码回退链（UTF-8/BOM/GB18030）、重复表头、列数不齐、引号内换行、截断尾行、空白行。
- 期间日历：半开区间 `[start, end)`、闰年 2 月 29 天、跨月跨年天数。
- 质量隔离：稳定原因码 + 原始行号 + 原值，可导出 CSV 交人工复核。
- 按日折算：日价 = 月价 ÷ 期间实际天数，全程 Decimal，只在记账时量化到分。
- 变更抵扣：预缴整期，变更日抵扣旧套餐未用额度并按新价补收剩余天数。
- 账单对账：行数账 / 期间天数账 / 金额账 / 出账账四本账，差异逐条说明。
- 导出：账单 CSV、分段 CSV（含原值与标记）、运行清单 JSON（run_id + 输入 sha256 + 校验位）。

## 核心规则

期间 `[start, end)` 的实际天数做分母：

```
日价      = 月价 / 期间天数
分段金额  = 月价 × 段天数 / 期间天数
账单      = 预缴整期 − Σ(旧价 × 剩余天数) + Σ(新价 × 剩余天数)
          = Σ(各段费率 × 段天数)
```

尾差按最大余额法分到 0.01，保证 Σ分段（分）= Σ抵扣（分）+ 账单额（分）逐张成立。
夏令时重叠取较早一次、跳过顺延；同一本地日多次变更只让 `(生效时刻, 变更号)` 最小的一条生效。

## 功能模块

| 模块 | 动作 | 入口 |
|---|---|---|
| M1 订阅采信 | 采信两份 CSV、看编码与列数诊断 | `POST /api/subscriptions/import` |
| M2 期间日历 | 期间天数、闰日、半开区间 | `GET /api/calendar` |
| M3 质量隔离 | 原因码分布、隔离行、CSV 导出 | `GET /api/quarantine` |
| M4 按日折算 | 日价与分段金额、重算 | `GET /api/proration` |
| M5 变更抵扣 | 变更序列、替代关系、抵扣行 | `GET /api/changes` |
| M6 账单对账 | 出账、账单明细、四本账 | `GET /api/invoices` |
| M7 导出 | 账单 CSV、分段 CSV、清单 JSON | `GET /api/export/invoices.csv` |

## 页面

| 路径 | 内容 |
|---|---|
| `/` | 批次清单、采信入口、阶段计数、四本账 |
| `/subscriptions` | 输入摘要、列契约、订阅清单、隔离区 |
| `/calendar` | 期间日历与天数核算 |
| `/proration` | 分段折算与日价 |
| `/changes` | 变更序列与抵扣行 |
| `/invoices` | 账单、对账、导出入口、点行看明细 |

## 启动

```bash
docker compose up -d --build
# 打开 http://127.0.0.1:18208/ 点「采信」，样例数据随仓库自带
```

宿主机端口 18208 → 容器 8000；数据库在命名卷 `subbill-data`。

## 演示步骤

1. 首页点「采信」，看到批次号 + 校验位与四本账全平。
2. 订阅清单页看列契约与隔离区（列数不符、期间倒置、未知时区、未知状态、缺价、重复键冲突）。
3. 期间日历页切换 2028-02 起点日期，核算出 29 天。
4. 折算页看日价与分段金额；变更页看被替代的变更与抵扣行。
5. 账单页点任意账单行看分段与抵扣行明细；底部导出账单 CSV、分段 CSV、清单 JSON。

## 定义与已知不覆盖

定义见 `docs/DATA-DICTIONARY.md`，深度登记与陷阱表见 `docs/DEPTH.md`，运维命令见 `docs/RUNBOOK.md`。

已知不覆盖：只读 CSV（不解析 xlsx）、单币种、变更按整日生效、账期只支持自然月、单实例 SQLite。

## 目录

```text
app/
  main.py config.py errors.py reasons.py manifest.py store.py web.py
  modules/m1_ingest … m7_export/   handler.py service.py + 2 个规则/读写文件
  templates/  base + 6 页
  static/     theme.css layout.css components.css app.js table.js invoices.js
docs/         DEPTH.md DATA-DICTIONARY.md RUNBOOK.md
sample_data/  7 个脏样例（含 GB18030、截断、空态）
tests/        conftest + 每模块 2 个测试文件 + e2e + invariants + fixtures
```

## 测试

```bash
docker compose exec -T app python -m pytest -q
```
