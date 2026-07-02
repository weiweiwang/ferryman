# Stock Research Valuation Screen

## Status

Current Status: Ready For Development
Owner: wangweiwei
Last Updated: 2026-07-02
Source: 用户要求评估 `../growing/radar/stock/crawler.py` 是否可移植，并参考 `/Users/wangweiwei/PycharmProjects/PassiveMoney` 与 `/Users/wangweiwei/PycharmProjects/insights` 增加低估值股票筛选能力到 `skills/stock-research`

Notes:
- 当前 `stock-research` 已有单票深度研究、同币种无风险利率、5 年 FCF 约束和 90% 安全边际门槛，但没有批量候选筛选器。
- `radar` 的东方财富 crawler 可以移植数据抓取思路；不应移植 Django Admin、Celery、数据库模型或日报快照系统。
- V1 默认同时筛选 `SH,SZ,HK`；阈值采用“固定质量护栏 + 同币种无风险利率自适应估值 cap”的混合方案；stdout 保持主输出，持久化结果必须显式指定 JSON / Excel 输出路径。

## Problem

- Today: `stock-research` 只能从用户给定 ticker 开始做深度研究；它不能主动从市场池里筛出“优秀公司 + 低估值”的候选。
- Impact: 用户要找“优秀公司错误定价”的机会时，必须先依赖外部股票池或人工筛选，容易把时间浪费在低质量便宜股或数据不完整标的上。
- Evidence: `skills/stock-research/scripts/fetch_stock_data.py` 是单 ticker fetcher；`../growing/radar/stock/crawler.py` 已能抓 A 股/港股行情、PE/PB、行业、分红、VWAP、MA；`PassiveMoney/quant/data/stock.py` 和 `insights/stock` 已沉淀了 ROE 稳定性、现金流/利润、预期收益率、DCF/PEG、低估值筛选等指标思路。

## Goal

- Goal: 给 `stock-research` 增加一个轻量低估值候选筛选能力，先批量找出“可能值得深度研究”的优秀低估值股票，再交给现有单票研究流程验证安全边际。
- In Scope:
  - 增加 `screen_stock_candidates.py` 候选筛选脚本，stdout 输出摘要 JSON；支持显式 `--json-out` 完整 JSON 和 `--xlsx-out` Excel 表格。
  - 移植 `radar` 中与东方财富 A 股/港股股票列表、行情、估值、分红、VWAP/MA 相关的轻量抓取思路。
  - 参考 `PassiveMoney` / `insights` 的指标，计算质量代理指标、估值代理指标、低估值 reason codes 和 reject reasons。
  - 更新 `SKILL.md`，把筛选器定位成 candidate generator，而不是投资建议或 `MISPRICED_QUALITY_BUY` 生成器。
  - 增加 mock 单元测试和 gated live tests。
- Out of Scope:
  - 不移植 Django Admin、Django model、Celery task、数据库或复杂日报报表工作流；V1 只提供简单显式 Excel 导出。
  - V1 不做大型官方公告/PDF 抓取解析；primary source 仍由单票研究阶段完成。
  - V1 不直接输出 BUY、WATCHLIST 或 90% Safety Margin Confidence。
  - V1 不把期权策略、ETF 期权收益计算器或 portfolio sizing 移植进 `stock-research`。

## Rules

- R1: 筛选器只能产生 `CANDIDATE` / `REJECTED` / `INSUFFICIENT_DATA` 级别的候选结果；不得直接产生 `MISPRICED_QUALITY_BUY`、`BUY` 或 `Safety Margin Confidence >= 90%`。
- R2: `stock-research` 的最终投资信号仍以单票深度研究为准；筛选结果只用于缩小研究池。
- R3: 新脚本必须保持 stdout 为主输出，并支持显式可选 `--json-out` 和 `--xlsx-out`；不得重新引入隐式 `--output-dir` 或默认写 `reports/` 的副作用。
- R4: V1 默认市场范围同时启用 A 股 `SH/SZ` 与港股 `HK`；美股和日股可以在输出中标记为 unsupported market，后续单独设计。
- R5: V1 可以使用东方财富作为 secondary market data source；所有候选输出必须标明 source、fetchedAt、market、currency、dataLimits。最终研究报告仍需按 `SKILL.md` 的 Primary Source Routing 核验。
- R6: 移植必须是轻量脚本级实现，不依赖 Django、Celery、MySQL、Redis、Admin、`radar.models.Stock` 或 `insights` 的数据库表。
- R7: 质量代理指标至少包括：上市年限、总市值、行业、ROE 均值、ROE 稳定性、ROIC 均值、OCF/净利润、FCF/净利润、资产负债率、商誉/净资产、分红率或股息率。
- R8: 低估值代理指标至少包括：PE TTM、PB、市值/5 年平均净利润、市值/5 年平均 FCF、预期收益率、同币种 10 年期无风险利率推导的 PE/FCF multiple cap。默认阈值使用混合方案：质量护栏采用固定保守阈值，估值倍数 cap 随同币种 10Y 无风险利率自适应。
- R9: 候选筛选必须先处理 deterministic rejects：无有效价格或停牌、A 股 `ST/*ST`、市值低于默认下限、非正 PE/利润、非正 5 年平均 FCF、现金流/利润显著不匹配、资产负债风险过高、商誉风险过高。上市或财务年限不足、关键字段缺失、行业不适配应标记为 `INSUFFICIENT_DATA` 或 `INDUSTRY_REVIEW_REQUIRED`，不要混入 `REJECTED`。
- R10: 银行、保险、地产、周期资源、SaaS、生物医药等行业不得硬套同一 FCF/PE 规则；V1 可先 `INSUFFICIENT_DATA` 或 `INDUSTRY_REVIEW_REQUIRED`，但必须在输出中说明。
- R11: 筛选评分必须分离为 `quality_score`、`valuation_score` 和 `screen_score`；字段名不得暗示已完成好公司评分或安全边际结论。
- R12: 风险利率必须使用现金流/财务口径币种对应的 10Y 主权债收益率；HKD 应使用 HKMA Section 10 HKD Government Bond benchmark yield，不得使用 USD proxy。
- R13: 候选结果必须能被后续单票流程消费，字段统一使用 snake_case；每条候选至少包含 `ticker`、`name`、`market`、`currency`、`financial_currency`、`price`、`market_cap`、`market_cap_rank`、`market_cap_percentile`、`analyzed`、`industry`、`metrics`、`quality_flags`、`valuation_flags`、`reject_reasons`、`data_gaps`。
- R14: 批量筛选时 JSON 是机器可读 source of truth，Excel 是人工扫描视图；若需要落盘，agent 必须显式传入 `--json-out reports/stock-screen-<date>.json` 和/或 `--xlsx-out reports/stock-screen-<date>.xlsx`，且两者的候选行数与排序必须一致。
- R15: `metrics` 内的指标字段也必须使用 snake_case；例如 `pe` 表示默认 TTM PE，`roe_mean`、`roe_std`、`roe_stability`、`roic_mean`、`ocf_to_profit`、`fcf_to_profit`、`market_cap_to_avg_profit`、`market_cap_to_avg_fcf`、`expected_return`、`debt_to_assets`、`goodwill_to_equity`、`risk_free_multiple_cap`。
- R16: `quality_flags` 和 `valuation_flags` 只记录通过的正向、可计算标签；缺陷、失败和跳过原因必须进入 `reject_reasons` 或 `data_gaps`。默认不输出 `next_research_checks` 顶层字段；单票研究需要核验的事项从 `data_gaps` 和固定 primary-source workflow 推导。
- R17: `valuation_flags` V1 只允许 `cheap_pe`、`cheap_profit`、`cheap_fcf`、`reasonable_pb`。`expected_return` 保留在 `metrics` 并可参与排序加分，但不得作为 `valuation_flags`，因为它混合了估值、ROE 和分红政策，不是纯便宜证据。
- R18: 东方财富快照必须按总市值降序抓取；`--max-count` 按每个市场限制原始快照池；财务补充和候选评分只作用于每个市场市值排名前 20% 的股票。不要暴露单独 enrichment limit 参数；市值排名 20% 以外的股票保留快照并标记 `outside_top_20_percent_by_market_cap`。

## Open Questions

| ID | Question | Blocks Development | Owner |
|---|---|---|---|
| Q1 | None identified. Defaults are resolved as `SH,SZ,HK`, hybrid thresholds, stdout primary, explicit `--json-out` / `--xlsx-out`. | No | wangweiwei |

## Acceptance

| ID | Acceptance | Evidence |
|---|---|---|
| A1 | R1-R3 被落实：筛选器只输出候选，不输出最终投资信号。 | `SKILL.md` review；mock test 验证没有 BUY / Safety Margin Confidence 字段。 |
| A2 | R4-R6 被落实：脚本可在 `stock-research` skill 内独立运行，不依赖 Django/Celery/DB。 | `python -m py_compile`；单元测试；源码 import 检查。 |
| A3 | R7-R18 被落实：候选 JSON 使用 snake_case，包含 `metrics`、质量代理、估值代理、screen score、flags、reject reasons、data gaps 和市值排名字段。 | `tests/test_screen_stock_candidates.py` 使用 mock 东方财富响应覆盖 pass/reject/insufficient data/top-20% analysis。 |
| A4 | R12 被落实：HKD 筛选使用 HKMA Section 10 风险利率路径；无 HKD rate 时只降级候选，不使用 USD proxy。 | `tests/test_fetch_risk_free_rate.py` 新增 HKMA `.xls` parser mock；live test gated by `STOCK_RESEARCH_RUN_LIVE_TESTS=1`。 |
| A5 | R13 被落实：输出候选可直接作为单票研究输入。 | fixture JSON 中每条候选可映射到 `fetch_stock_data.py --ticker <ticker>` 的 ticker 格式。 |
| A6 | 文档明确候选筛选和深度研究的关系，避免把 secondary data 当 primary evidence。 | `SKILL.md` 和 `assets/report-template.md` diff review。 |
| A7 | Skill 结构仍通过本地 validator。 | `python3 skills/skill-creator/scripts/quick_validate.py skills/stock-research`。 |
| A8 | R14 被落实：可生成面向人工扫描的 Excel，同时 JSON 保持机器可读源。 | CLI test 验证 `--json-out` 与 `--xlsx-out` 行数、排序和关键字段一致。 |
