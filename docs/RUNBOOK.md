# 运行手册 subbill

## 启动

```bash
docker compose config --quiet
docker compose up -d --build
curl -s http://127.0.0.1:18208/api/health
```

宿主机端口 18208 → 容器 8000。数据库在命名卷 `subbill-data` 的 `subbill.sqlite`。

## 主流程

```bash
# 1 采信自带脏样例（订阅 + 变更），返回 run_id 与四本账
curl -s -X POST http://127.0.0.1:18208/api/subscriptions/import \
  -H 'Content-Type: application/json' -d '{}'

# 2 周期诊断
curl -s http://127.0.0.1:18208/api/calendar | head -c 400

# 3 隔离区与原因码
curl -s http://127.0.0.1:18208/api/quarantine | head -c 400
curl -s -o /tmp/quarantine.csv http://127.0.0.1:18208/api/quarantine.csv

# 4 折算与变更
curl -s http://127.0.0.1:18208/api/proration | head -c 300
curl -s -X POST http://127.0.0.1:18208/api/changes | head -c 300

# 5 账单与对账
curl -s http://127.0.0.1:18208/api/invoices | head -c 400
curl -s http://127.0.0.1:18208/api/reconcile

# 6 导出
curl -s -o /tmp/invoices.csv http://127.0.0.1:18208/api/export/invoices.csv
curl -s -o /tmp/manifest.json http://127.0.0.1:18208/api/export/manifest.json
```

## 换成自己的数据

样例目录挂载在容器 `/app/sample_data`，采信时传文件名即可（只接受纯文件名）：

```bash
curl -s -X POST http://127.0.0.1:18208/api/subscriptions/import \
  -H 'Content-Type: application/json' \
  -d '{"subscriptions":"subscriptions_gbk.csv","changes":"changes_dirty.csv"}'
```

两份文件的列名会被映射到规范字段：订阅表需要 `订阅号`、`月价(元)`、`期间起`、`期间止`、`状态`；变更表需要 `变更号`、`订阅号`、`生效时间`、`类型`。缺必需列会整体隔离并给出 `R_HEADER_MISSING`。

## 重算与幂等

- 同一份输入再采信一次：命中 `batch_key`，直接返回原批次，行数与合计不变。
- 只重算金额：`POST /api/proration`；重算分段与抵扣：`POST /api/changes`。两者都会重新出账并刷新四本账。
- 想强制新建批次：改任一输入文件的内容（`batch_key` 由输入 sha256 决定）。

## 更正补入（M8）

```bash
# JSON：指定样例目录里的更正文件
curl -s -X POST http://127.0.0.1:18208/api/corrections \
  -H 'Content-Type: application/json' \
  -d '{"file":"subscriptions_correction.csv"}'

# multipart：直接上传更正文件
curl -s -X POST http://127.0.0.1:18208/api/corrections \
  -F 'mode=patch' -F 'file=@/path/to/correction.csv'

# 版本链与三态对照、发布记录、条目导出
curl -s 'http://127.0.0.1:18208/api/corrections?run_id=<SC-...>'
curl -s http://127.0.0.1:18208/api/corrections/releases
curl -s -o /tmp/corrections.csv 'http://127.0.0.1:18208/api/corrections/entries.csv?run_id=<SC-...>'
```

- 只支持 `mode=patch`（定向补入）；`mode=replace` 返回 422 `E_CORRECTION_MODE`，不允许改写已确认结果。
- 幂等键 = 基线 run + 更正文件 sha256；同文件重跑返回 `reused=true`，不新增版本、不重复补入。
- 更正行必须命中隔离区未结案的 error 级订阅记录，否则 422 `E_CORRECTION_INVALID`，`detail.rejected` 逐条给原因。
- 发布失败：临时 run（`running`）被清理，`correction_releases` 留一条 `failed`，当前版本仍是上一份完整旧版。
- 页面 `/corrections` 看版本链、发布记录与「原结果 / 补入行 / 最终版本」三态对照。

## 重建数据库

```bash
docker compose down -v          # 删掉命名卷，下次启动会重建空库
docker compose up -d --build
```

## 排错

| 现象 | 检查 |
|---|---|
| 首页 200 但表格为空 | 还没有批次，点「采信」；或 `/api/runs` 看是否有 `done` 批次 |
| 采信返回 400 `E_FILE_MISSING` | 文件名不在 `sample_data/`；只接受纯文件名 |
| 采信返回 400 `E_BAD_FILE_NAME` | 传了路径分隔符或空串 |
| 账单为 0 | 期间内全是暂停/试用，或月价为 0；看账单标记 `R_INVOICE_ZERO` |
| 对账不平 | 看 `/api/reconcile` 哪一本账 `status=mismatch`，再看对应明细 |
| 导出 404 `E_NO_RUN` | 还没批次；先采信 |
| 更正 422 `E_CORRECTION_INVALID` | 更正行没命中未结案 error 隔离记录，或字段仍非法；看 `detail.rejected`，整份拒绝、基线不变 |
| 更正 422 `E_CORRECTION_MODE` | 用了 `replace`；系统只支持定向补入 `patch` |
| 更正 422 `E_CORRECTION_LEDGER` | 补入后四账不平，已自动回滚；看 `/api/corrections/releases` 的 failed 留痕 |
| 容器内 pytest 失败 | `docker compose exec -T app python -m pytest -q`，先看第一个失败 |

## 测试

```bash
docker compose exec -T app python -m pytest -q
docker compose exec -T app python -m pytest tests/test_invariants.py -q
```

## 日志

```bash
docker compose logs -f app
docker compose exec -T app ls -l /data
```
