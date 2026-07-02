# Implementation And Validation Plan

## Target

Spec: features/stock-research-valuation-screen/spec.md
Spec Review: Ready For Development
Owner: wangweiwei
Last Updated: 2026-07-02

Status: Complete

## Context Reviewed

- instructions: AGENTS.md from current Ferryman thread instructions
- spec: features/stock-research-valuation-screen/spec.md, Ready For Development
- review: None identified
- code/tests/docs: `skills/stock-research/SKILL.md`, `skills/stock-research/scripts/fetch_stock_data.py`, `skills/stock-research/scripts/fetch_risk_free_rate.py`, `skills/stock-research/tests/test_fetch_stock_data.py`, `skills/stock-research/tests/test_fetch_risk_free_rate.py`, `skills/stock-research/assets/report-template.md`, `/Users/wangweiwei/PycharmProjects/growing/radar/stock/crawler.py`, `/Users/wangweiwei/PycharmProjects/growing/radar/tasks.py`, `/Users/wangweiwei/PycharmProjects/growing/radar/admin.py`, `/Users/wangweiwei/PycharmProjects/PassiveMoney/quant/data/stock.py`, `/Users/wangweiwei/PycharmProjects/insights/stock/models.py`, `/Users/wangweiwei/PycharmProjects/insights/stock/views.py`, `/Users/wangweiwei/PycharmProjects/insights/stock/templates/stock/index.html`, `/Users/wangweiwei/PycharmProjects/insights/option/models.py`

## Summary

- Goal: 在 `stock-research` 中实现一个轻量低估值候选筛选器，批量生成可进入单票深度研究的优秀低估值股票候选。
- Non-Goals: 不迁移 Django/Celery/Admin/数据库，不直接给 BUY，不做 primary source PDF 解析，不迁移期权策略。
- Primary Risk: 东方财富数据是 secondary source 且接口非正式；必须把它限制在筛选阶段，并用 mock + gated live tests 验证解析稳定性。

## Open Questions

| Question | Owner | Blocks Development | Target Date |
|---|---|---|---|
| None identified. Defaults are `SH,SZ,HK`, hybrid thresholds, stdout primary, explicit JSON / Excel artifacts. | wangweiwei | No | 2026-07-02 |

## Implementation Approach

- 新增 `skills/stock-research/scripts/screen_stock_candidates.py`，把 `radar/stock/crawler.py` 的东方财富股票列表、行情字段映射、港股/A股市场配置思路移植为纯脚本实现。
- 不复制 `radar.tasks`、`radar.models`、`radar.admin`；并发、入库、复杂日报报表都不是 V1。V1 只支持显式 `--xlsx-out` 导出人工扫描表。
- 从 `PassiveMoney` 移植指标思想而不是大段代码：5 年均值、OCF/净利润、FCF/净利润、ROE 均值与波动、ROIC、资产负债率、商誉/净资产、市值/平均利润、市值/平均 FCF、预期收益率、PEG/DCF 作为可解释 flags。
- 从 `insights` 移植筛选交互背后的规则：固定质量护栏、ROE 稳定性、expected_ret、OCF/净利润、上市年限和最新快照选择。
- 复用 `fetch_risk_free_rate.py` 的 `multipleCaps` 逻辑，先补齐 HKD 的 HKMA Section 10 `.xls` 解析，再让筛选器按币种取 PE/FCF multiple cap。
- 默认阈值采用混合方案：质量指标用固定保守阈值过滤垃圾和不稳定公司，估值倍数 cap 按同币种 10Y 无风险利率自适应。
- 新筛选器输出统一使用 snake_case；核心指标放入 `metrics`，通过项放入 `quality_flags` / `valuation_flags`，失败原因放入 `reject_reasons`，数据不足放入 `data_gaps`。
- `valuation_flags` V1 只保留 `cheap_pe`、`cheap_profit`、`cheap_fcf`、`reasonable_pb`；`expected_return` 保留在 `metrics` 并可参与排序加分，但不作为估值 flag。
- 更新 `SKILL.md`，增加 `screen_stock_candidates.py` 的使用边界和字段说明；报告模板只增加“候选来源”入口提示，不把筛选分数变成最终结论。

Architecture Check:
- Boundary: `skills/stock-research` 内的 skill 脚本、测试和文档；不跨入 Ferryman backend runtime。
- SSOT: `features/stock-research-valuation-screen/spec.md` 定义产品规则；脚本字段契约由 `screen_stock_candidates.py` 和 tests 固化；`SKILL.md` 定义 agent 使用边界。
- Existing Mechanism: stdout-first JSON、optional `--json-out`、stable `{ok:false, phase, error}` failure payload、risk-free-rate multiple caps、skill validator；新增 optional `--xlsx-out` 仅作人工扫描视图。
- Interface: 新增 CLI `screen_stock_candidates.py --markets SH SZ HK --max-count N --sort-by screen_score --json-out path --xlsx-out path`；脚本内部固定按市值降序抓快照，`--max-count` 按每个市场限制原始快照池，并只对每个市场市值排名前 20% 的股票做财务补充和候选评分。
- Docs: `SKILL.md` usage；必要时 `report-template.md` 增加候选来源字段。
- Locality: 修改限定在 `skills/stock-research/**` 和本 feature docs。
- Design Checks: 改动扩散控制在 skill；规则重复通过 spec 和 `SKILL.md` 分层；边界不清风险通过 R1/R2 明确候选不等于买入。
- Test Target: JSON contract、parser behavior、筛选 pass/reject、risk-free-rate HKD parser、CLI behavior。
- Refactor Needed First: 在 `fetch_risk_free_rate.py` 中抽出/新增 HKD parser，避免 screen 脚本自行抓风险利率。
- Separate long-term architecture decision doc needed: No，目前是 skill 内轻量能力，不是平台级架构。

TDD Planning:
- Use TDD for HKD risk-free parser、Eastmoney list parser、screen rules、CLI JSON contract。
- Do not use TDD for纯文档更新；用 validator 和人工 diff review。

## Key Decisions

| Decision | Rationale | Rejected Alternative |
|---|---|---|
| 只移植 crawler 思路，不移植 Django/Celery/DB | `stock-research` 是轻量 skill，stdout JSON 更适合 agent 消费 | 迁移 `radar` app 会引入数据库、后台任务、Admin 和部署复杂度 |
| 筛选器只输出候选，不输出投资建议 | 保持 90% 安全边际必须来自单票 primary evidence 和估值模型 | 用低 PE/高 ROE 直接生成 BUY 会违背当前 skill 契约 |
| 估值筛选使用多指标 flags，不只看 PE/PB | PassiveMoney/insights 的价值在于现金流、ROE 稳定、预期收益、资产风险一起看 | 单一 PE/PB 会把周期股、价值陷阱和一次性利润误判为便宜 |
| 默认阈值使用混合方案 | 固定质量护栏保证公司质量底线，同币种无风险利率自适应估值 cap 让不同市场利率环境可比 | 完全固定 PE cap 会忽略利率环境；完全 adaptive 又可能放松质量底线 |
| `expected_return` 不进入估值 flags | 它混合了 PE、ROE 和分红政策，是综合回报 proxy，不是纯便宜证据 | 用 `high_expected_return` 会和 `cheap_pe` / `cheap_profit` / `cheap_fcf` 重叠并误导安全边际判断 |
| PB 只保留 `reasonable_pb` | PB 是账面资产辅助约束，不应被当作优秀公司低估的核心证据 | `cheap_pb` 或 `low_pb` 容易把低 PB 价值陷阱推高 |
| 风险利率复用 `fetch_risk_free_rate.py` | 避免同币种 10Y 收益率规则重复 | screen 脚本内部独立实现利率抓取会制造两个口径 |
| Excel 作为显式人工扫描视图 | 几千只股票用表格筛选更高效，但 JSON 仍是 agent 可审计源数据 | 默认写 reports 会制造隐式副作用；只输出 Excel 又不利于 agent 消费 |
| 不暴露财报补充数量参数 | 分析范围应由“市值排名前 20%”这条业务规则决定，而不是让用户猜一个财报抓取数量 | 数量参数会把实现细节暴露给用户，且容易和候选质量混淆 |
| live tests gated by env var | 本地和 CI 默认稳定，用户需要时可跑真实源验证 | 默认所有测试都访问外网会让 CI 和沙箱不稳定 |

## Affected Surface

| Area | Files / Modules | Expected Change | Risk |
|---|---|---|---|
| Risk-free rate | `skills/stock-research/scripts/fetch_risk_free_rate.py`, `skills/stock-research/tests/test_fetch_risk_free_rate.py` | 增加 HKD HKMA Section 10 `.xls` parser 和 live test | Medium |
| Stock candidate screen | `skills/stock-research/scripts/screen_stock_candidates.py`, `skills/stock-research/tests/test_screen_stock_candidates.py` | 新增东方财富轻量抓取、指标计算、筛选规则、CLI、显式 JSON/Excel 导出 | High |
| Skill contract | `skills/stock-research/SKILL.md` | 增加候选筛选 workflow 和限制 | Medium |
| Report template | `skills/stock-research/assets/report-template.md` | 增加候选来源/筛选指标披露提示 | Low |
| Validation docs | `features/stock-research-valuation-screen/spec.md`, `features/stock-research-valuation-screen/plan.md` | 保存设计和实施计划 | Low |

## Execution Plan

1. 完成 HKD risk-free 官方源支持
   - Outcome: `fetch_risk_free_rate.py --currency HKD` 返回 HKMA Section 10 10Y benchmark yield，不使用 USD proxy。
   - Human Review: No (agent-only)
   - Status: Complete
   - Touches: `fetch_risk_free_rate.py`, `test_fetch_risk_free_rate.py`
   - Dependencies: `xlrd==2.0.1` 已在本机 Python 环境安装；需要加入 skill `requirements.txt`。
   - Validation: mock `.xls` parser test；`STOCK_RESEARCH_RUN_LIVE_TESTS=1 ... test_fetch_risk_free_rate.py`
   - Recovery: HKD 分支保留 stable `ok:false`，screen 对 HKD 标记 `rateUnavailable`。
2. 移植轻量市场列表抓取
   - Outcome: 新脚本能抓 `SH/SZ/HK` 股票列表并输出基本行情字段。
   - Human Review: No (agent-only)
   - Status: Complete
   - Touches: `screen_stock_candidates.py`, `test_screen_stock_candidates.py`
   - Dependencies: Slice 1 对 HKD screen 有帮助，但 A 股可独立实现。
   - Validation: mock Eastmoney `clist/get` 响应；CLI stdout/json-out/xlsx-out test；import 检查不依赖 Django/Celery/DB。
   - Recovery: 默认仍请求 `SH/SZ/HK`；失败市场写入 `dataLimits.errors`，不让一个市场失败吞掉其他市场结果。
3. 增加低估值与质量代理指标
   - Outcome: 每个候选包含 `quality_score`、`valuation_score`、`screen_score`、`metrics`、`quality_flags`、`valuation_flags`、`reject_reasons`、`data_gaps`。
   - Human Review: Yes (HITL)
   - Status: Complete
   - Touches: `screen_stock_candidates.py`, tests
   - Dependencies: Slice 2；阈值使用 spec 的 hybrid default。
   - Validation: fixtures 覆盖优秀低估、低质便宜、数据不足、行业需人工 review。
   - Recovery: 把复杂指标降级为 flags，不阻塞基本 candidate output。
4. 接入文档和 agent workflow
   - Outcome: `SKILL.md` 明确何时运行筛选器、如何解释结果、如何进入单票研究。
   - Human Review: Yes (HITL)
   - Status: Complete
   - Touches: `SKILL.md`, `report-template.md`
   - Dependencies: Slice 3 输出字段稳定。
   - Validation: skill quick validator；人工 review 文档是否仍精简。
   - Recovery: 只在 `SKILL.md` 增加短小段落，把详细字段留在脚本 help/test。
5. 全面验证和 live smoke
   - Outcome: 离线测试、skill validator、live source smoke 都有明确结果。
   - Human Review: No (agent-only)
   - Status: Complete
   - Touches: tests and validation evidence only
   - Dependencies: Slices 1-4。
   - Validation: `python -m pytest skills/stock-research/tests/test_fetch_risk_free_rate.py skills/stock-research/tests/test_screen_stock_candidates.py`; `STOCK_RESEARCH_RUN_LIVE_TESTS=1 ...`; `python3 skills/skill-creator/scripts/quick_validate.py skills/stock-research`; `git diff --check -- skills/stock-research features/stock-research-valuation-screen`
   - Recovery: 若 live source 失败，保留 mock pass，报告具体外网/源站 blocker，不伪造 live pass。

## Validation Plan

| Acceptance / Risk | Validation Method | Expected Evidence |
|---|---|---|
| A1 候选不是投资建议 | Unit test inspect payload fields；文档 review | JSON 无 BUY / Safety Margin Confidence；`SKILL.md` 明确 candidate only |
| A2 不依赖 Django/Celery/DB | import/source guard test | test 断言不 import `django`, `celery`, `mysql`, `radar.models` |
| A3 候选字段完整 | mock fixtures | pass/reject/insufficient payload snapshots 或字段断言；断言新 payload 不出现 camelCase 字段；断言只分析市值排名前 20% |
| A3 valuation flags 清晰可读 | mock fixtures | 只出现 `cheap_pe`、`cheap_profit`、`cheap_fcf`、`reasonable_pb`；不出现 `high_expected_return` 或 `cheap_pb` |
| A4 HKD 官方利率 | mock `.xls` + gated live test | HKD `ok:true`, source HKMA Section 10, no proxy |
| A5 可进入单票研究 | mapping test | candidate ticker 可传给 `fetch_stock_data.py --ticker` |
| A6 文档不混淆 secondary/primary | human diff review + validator | `SKILL.md` 说明 secondary source screen only |
| A7 skill 结构有效 | skill validator | `ok: true` |
| A8 JSON / Excel 输出一致 | CLI test with temp output paths | `--json-out` 与 `--xlsx-out` row count、ticker order、核心字段一致 |
| Live source drift | gated live tests | 成功输出若干 candidates 或稳定 source error |

## Coverage Expectations

- Existing coverage command: `/Users/wangweiwei/miniconda3/bin/conda run -n ferryman python -m pytest skills/stock-research/tests/test_fetch_stock_data.py skills/stock-research/tests/test_fetch_risk_free_rate.py`
- Expected new or updated tests: `skills/stock-research/tests/test_screen_stock_candidates.py`; update `test_fetch_risk_free_rate.py` for HKD parser。
- Coverage threshold or target: No repo-wide threshold identified; cover public CLI contract, parser behavior, and screen decisions.

## Validation Evidence

- Offline tests: `pytest skills/stock-research/tests` passed with 36 passed, 4 skipped.
- Live risk-free tests: `STOCK_RESEARCH_RUN_LIVE_TESTS=1 /Users/wangweiwei/miniconda3/bin/conda run -n ferryman python -m pytest skills/stock-research/tests/test_fetch_risk_free_rate.py` passed with 16 passed under elevated network access.
- Live screener smoke: earlier `conda run -n ferryman python skills/stock-research/scripts/screen_stock_candidates.py --markets HK --max-count 3 --timeout 30` returned `ok:true` with `00700.HK` as a candidate. `--markets SH SZ --max-count 3 --timeout 30` returned `ok:true` with A-share market snapshots parsed correctly and banks marked `INDUSTRY_REVIEW_REQUIRED`.
- Structure checks: `python3 skills/skill-creator/scripts/quick_validate.py skills/stock-research`, `python -m py_compile`, and `git diff --check -- skills/stock-research features/stock-research-valuation-screen` passed after fixes.

## Rollback / Recovery

- New screener can be removed by deleting `screen_stock_candidates.py` and its tests without changing existing single ticker research.
- HKD rate support can fail closed with stable `ok:false` while leaving USD/CNY/JPY behavior untouched.
- Documentation changes should be small enough to revert independently.

## Assumptions

- `xlrd==2.0.1` is acceptable for reading HKMA `.xls`; add it to skill `requirements.txt` before relying on HKD tests in a fresh runtime.
- 东方财富数据只用于候选筛选，最终报告仍必须用 primary source 验证关键异常和 normalization。
- V1 默认阈值采用 hybrid defaults，再根据实际 live 输出校准固定质量护栏的严格程度。
