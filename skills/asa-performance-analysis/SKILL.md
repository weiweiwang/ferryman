---
name: asa-performance-analysis
description: >
  Use this for Apple Search Ads (ASA) post-campaign performance analysis,
  purchase cohort reporting, keyword-level CPS/CPI/RRC diagnostics, LTV-based
  payback analysis, and optimization decision support for App Store ads.
version: 1.0.0
author: Ferryman
created: 2026-05-22
updated: 2026-05-22
---

# ASA Performance Analysis

**专家目标**：作为资深ASA投放优化师，基于关键词级投放表现、订阅续费质量和目标回本周期内的回本能力，输出可执行的拓量、降价、暂停、观察和否词建议。

## 一、工作原则

使用技能内置脚本获取关键词表现CSV。脚本输出是默认数据底座；报告分析必须基于脚本输出的CSV字段完成，不得创建或执行任何临时分析脚本。

默认回本周期为180天。若用户指定其他回本周期，执行脚本时传入`--payback-days`，报告中的LTV、预估收入、回本率和Target_CPI都应按该周期解释。

关键字段：
- `payback_ratio`：目标回本周期内的预估净收入/spend。
- `LTV_per_purchase_user`：目标回本周期内单个购买用户的预估净收入。
- `Target_CPI`：由关键词自己的LTV和安装到购买率换算得到，物理上对应苹果ASA后台的CPA目标，不是统一人工目标。
- `RUC1_mature_purchases`至`RUC5_mature_purchases`：对应续订周期已成熟的购买分母，用来判断续订率是否可用。
- `RRC1`至`RRC5`保留原始观测值；`effective_RRC1`至`effective_RRC5`用于LTV和回本计算，并对累计续费率做单调不升约束。

---

## 二、匹配类型优化策略

在进行决策时，必须严格区分关键词的匹配类型（Match Type）：

### 1. 精确匹配（Exact Match）
- **特点**：流量精准，用户意图强。
- **优化路径**：
  - `payback_ratio >= 1.0`：调高出价（Raise Bid），获取更多曝光。
  - `payback_ratio < 1.0`：若数据充足且CPS过高，通过降低出价（Lower Bid）使实际CPI逼近 `Target_CPI`；若CPS依然失控或续订率极低，则暂停（Pause）。

### 2. 广泛匹配/搜索匹配（Broad Match / Search Match）
- **特点**：用于拓词与流量探测，杂音大。
- **优化路径**：
  - **核心动作是“否词”而非单纯调整出价**。必须分析搜索词报告，针对高消耗、无转化或偏离产品定位的搜索词，在ASA后台添加为“否定关键词（Negative Keywords）”。
  - 只有在搜索词结构健康但整体流量包CPS偏高时，才降低该广泛匹配关键词的出价。

---

## 三、分析决策SOP

### 1. 数据准备与脚本执行
确认参数：`bundle_id`、输出CSV路径、`start_date`、目标本位币（默认CNY）、试用期天数（`--trial-days`，默认7）、账单周期天数（`--billing-period-days`，默认30）、首期毛收入（`--first-purchase-gross`）、常规续费毛价（`--regular-period-gross`）、苹果税率（`--apple-fee`，默认0.15）、目标回本周期（`--payback-days`，默认180）。

使用技能内置脚本 `scripts/fetch_asa_bigquery_report.py`，路径相对本技能目录解析。调用时传入以下参数：`--bundle-id`、`--output`、`--start-date`、`--target-currency`、`--trial-days`、`--billing-period-days`、`--first-purchase-gross`、`--regular-period-gross`、`--payback-days`。

脚本执行后，除了在指定的`--output`路径下生成整体关键词聚合汇总表（例如`report.csv`）外，还会自动在其同级目录下生成拆分CSV文件（对于未成熟的数据切片，对应的聚合表可能为空，仅包含表头），用于报告撰写时基于CSV字段按需读取、核对和深入分析：
- `report_daily.csv`：按天维度的原始明细数据，包含完整字段，用于趋势与波动分析。
- `report_ruc1.csv`：对`report_date <= ruc1_cutoff`的成熟期数据进行切片后的关键词聚合表。列名为常规的`purchases`、`renewals`和`RRC`。
- `report_ruc2.csv`：对`report_date <= ruc2_cutoff`的成熟期数据进行切片后的关键词聚合表。列名为常规的`purchases`、`renewals`和`RRC`。
- `report_ruc3.csv`：对`report_date <= ruc3_cutoff`的成熟期数据进行切片后的关键词聚合表。列名为常规的`purchases`、`renewals`和`RRC`。
- `report_ruc4.csv`：对`report_date <= ruc4_cutoff`的成熟期数据进行切片后的关键词聚合表。
- `report_ruc5.csv`：对`report_date <= ruc5_cutoff`的成熟期数据进行切片后的关键词聚合表。

### 2. 置信度与数据充要性研判
对关键词的数据量进行分级：
- **样本量（Sample Size）**：
  - `installs < 20`：样本很小，通常只观察，除非消耗异常高。
  - `20 <= installs < 50`：弱方向性信号，可做小幅降价或继续观察。
  - `50 <= installs < 100`：方向性信号，可以做明确优化动作。
  - `installs >= 100`：稳定信号，可以做强动作。
- **购买信号（Purchase Signal）**：
  - `purchase_users = 0` 且 `installs < 50`：不要轻易暂停，优先观察或小幅降价。
  - `purchase_users = 0` 且 `installs >= 50`：若消耗明显、CPI/CPC不低，可降价或暂停。
  - `purchase_users = 0` 且 `installs >= 100`：通常可暂停，除非该词有战略价值。
  - `purchase_users >= 1`：有弱正向信号。
  - `purchase_users >= 3`：有方向性购买信号；`purchase_users >= 10`：强购买信号。
- **续订信号（Renewal Signal）**：
  - `RUC1_mature_purchases < 3`：不能用RRC1做强判断。
  - `RUC1_mature_purchases >= 3`：弱方向性续订信号。
  - `RUC1_mature_purchases >= 5`：可用于辅助判断。
  - `RUC1_mature_purchases >= 10`：续订判断较稳定。
  - **警惕**：若 `RUC1_mature_purchases = 0`，不能用RRC1判断续订质量；此时主要看购买转化、消耗和样本量。

### 3. 基准（Benchmark）制定
为了防止小样本/偶发性高回本词污染基准（如花费极低、仅产生1~2个安装和1个购买的词），健康基准词必须同时满足以下数据充要性门槛：
1. `spend >= 100`（按账户本位币计，如100 CNY）
2. `installs >= 50`
3. `RUC1_mature_purchases >= 5`
4. `payback_ratio >= 1.0`

筛选出上述优质关键词集合后，计算其平均 `CVR`、`RRC1` 和 `CPC` 作为全账户的“健康基准值”，用以指导弱表现关键词的归因诊断。若没有可靠健康词，不要硬凑基准，直接说明“暂无可靠健康基准”。

### 4. 优化动作决策矩阵

| 状态分类 | 判定条件 | 核心推荐动作 |
| :--- | :--- | :--- |
| **Scale (拓量)** | `payback_ratio >= 1.2` 且数据置信度中等及以上 | 提高出价（每次+10%~20%），确保预算充足 |
| **Keep (维持)** | `0.9 <= payback_ratio < 1.2` 且表现稳定 | 维持当前出价与预算 |
| **Lower Bid (降价)** | `payback_ratio < 0.9` 且有真实购买转化，降幅缺口（`required_CPS_reduction`） $\le 50\%$ | 降低出价，幅度可参考：$\text{New\_Bid} = \text{Current\_Bid} \times \frac{\text{Target\_CPI}}{\text{CPI}}$（注：若 `installs = 0`，CPI 为空，此时直接执行固定降幅如降价 20%~30%，不使用该公式） |
| **Pause (暂停)** | `payback_ratio < 0.9` 且有成熟购买但 $\text{RRC1}$ 极低，或降幅缺口 $> 50\%$；或无购买转化且样本稳定；或 `installs = 0` 且消耗已超出测试预算上限 | 暂停关键词投放 |
| **Observe (观察)** | 消耗低，数据未达置信度门槛，或 $\text{RUC1\_mature\_purchases} = 0$，或 `payback_ratio` 很高但安装/购买样本仍很小 | 保持观察，不做实质动作，等待数据累积；高回本小样本词可标记为“小预算验证”，但不要写成“接近回本线” |
| **Review Only (仅复盘)** | 关键词状态为 `PAUSED` | 仅做历史复盘与成效总结，不建议重新开启 |

### 5. Pro模型复核与优化

完成Markdown报告和Action CSV后，应使用更高阶Pro模型进行一次最终复核、策略审视和表达优化。复核阶段不允许创建或执行任何临时分析脚本。

复核重点：
- 验证报告中的核心计算、指标解释和推导逻辑是否准确。
- 审视投放动作是否符合数据证据、样本置信度、订阅质量和回本目标。
- 识别报告中可能存在的过度判断、遗漏判断、前后矛盾或表达不清。
- 优化最终报告，使结论更像资深投放优化师的决策复盘，动作明确、理由充分、优先级清晰。

---

## 四、输出规范与模板

若用户未指定最终报告文件名，默认使用：
- `asa-{bundle_id_short}-{run_timestamp}_actions.csv`
- `asa-{bundle_id_short}-{run_timestamp}_report.md`

其中，`bundle_id_short`取`bundle_id`最后一段，例如`app.blynkai.todo`取`todo`，`com.linkaiapp.gtrans`取`gtrans`；`run_timestamp`使用本地时间`YYYYMMDD-HHMM`。若同一分钟内重复生成同一产品报告导致文件名冲突，追加`-2`、`-3`等序号。

### 1. CSV格式规范（Action CSV）
分析产生的决策应生成对应的 CSV 文件，表头契约如下：
```csv
keyword,ad_group,match_type,keyword_status,action,priority,confidence,spend,daily_spend,CPS,Target_CPI,payback_ratio,required_CPS_reduction,purchase_users,RUC1,RUC2,RUC3,RUC4,RUC5,RRC1,RRC2,RRC3,RRC4,RRC5,effective_RRC1,effective_RRC2,effective_RRC3,effective_RRC4,effective_RRC5,RUC1_mature_purchases,RUC2_mature_purchases,RUC3_mature_purchases,RUC4_mature_purchases,RUC5_mature_purchases,LTV_per_purchase_user,expected_revenue,days,clicks,installs,CVR,CPR1,reason,ad_group_id
```

### 2. 诊断报告模板（Markdown Report）
报告语言跟随用户输入语言；中文报告遵守中文文案规范。

```markdown
# ASA关键词表现与队列LTV分析报告

## 一、核心评估假设 (Assumptions)
- **分析周期**：YYYY-MM-DD 至 YYYY-MM-DD (共 {days} 天)
- **应用App ID**：{bundle_id}
- **订阅模式**：[免费试用 (如7天试用+30天续订) / 无免费试用直接付费]
- **产品毛价**：{monthly_gross_price} {currency} | **首期毛收入**：{first_purchase_gross_revenue} {currency}
- **苹果渠道税率**：{apple_fee}%
- **回本目标**：{payback_days}天内预估净收入 >= spend

## 二、账户整体表现 (Account Summary)
- **总消耗**：{total_spend} {currency} | **每日均消耗**：{daily_spend} {currency}
- **总购买人数**：{total_purchase_users} | **总首期续订数**：{total_ruc1}
- **平均每次购买成本 (CPS)**：{account_cps} {currency} | **平均首期续订成本 (CPR1)**：{account_cpr1} {currency}
- **无偏差首期续订率 (RRC1)**：{account_rrc1}% (成熟分母：{account_ruc1_mature_purchases})
- **预估净收入**：{estimated_revenue} {currency}
- **目标周期回本率 (Payback Ratio)**：{account_payback_ratio}%

## 三、健康账户基准 (Healthy Benchmark)
- **优质基准词数**：{benchmark_count} 个
- **基准线 CVR**：{benchmark_cvr}% | **基准线 RRC1**：{benchmark_rrc1}%
- **基准回本率**：{benchmark_payback_ratio}%

| 关键词 (Keyword) | 匹配类型 | 消耗 (Spend) | 购买成本 (CPS) | 购买人数 | RRC1 | 回本率 | 诊断结论 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| example_exact | EXACT | 120.00 | 15.00 | 8 | 50.00% | 125.0% | 表现健康，回本符合预期 |

## 四、核心优化决策 (Key Actions)
每个动作分组优先使用表格展示，单表最多展示20个关键词；完整明细见决策CSV：[action_csv_basename](file:///path/to/csv)。

### 1. 拓量 (Scale)

| 关键词 | 广告组 | 状态 | spend | installs | purchase | CPS | Target_CPI | RRC1/RRC2/RRC3/RRC4/RRC5 | 回本率 | 建议 |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- | ---: | :--- |
| {keyword} | {ad_group} | {keyword_status} | {spend} | {installs} | {purchase_users} | {CPS} | {Target_CPI} | {RRC_summary} | {payback_ratio} | {reason} |

### 2. 降低出价 (Lower Bid)

| 关键词 | 广告组 | 状态 | spend | installs | purchase | CPS | Target_CPI | RRC1/RRC2/RRC3/RRC4/RRC5 | 回本率 | 建议 |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- | ---: | :--- |
| {keyword} | {ad_group} | {keyword_status} | {spend} | {installs} | {purchase_users} | {CPS} | {Target_CPI} | {RRC_summary} | {payback_ratio} | {reason} |

### 3. 暂停投放 (Pause)

| 关键词 | 广告组 | 状态 | spend | installs | purchase | CPS | Target_CPI | RRC1/RRC2/RRC3/RRC4/RRC5 | 回本率 | 建议 |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- | ---: | :--- |
| {keyword} | {ad_group} | {keyword_status} | {spend} | {installs} | {purchase_users} | {CPS} | {Target_CPI} | {RRC_summary} | {payback_ratio} | {reason} |

### 4. 否词屏蔽 (Negative Keywords)

| 关键词 | 广告组 | 状态 | spend | installs | purchase | CPS | Target_CPI | 搜索词/问题 | 建议 |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- | :--- |
| {keyword} | {ad_group} | {keyword_status} | {spend} | {installs} | {purchase_users} | {CPS} | {Target_CPI} | {query_issue} | {reason} |

### 5. 保持观察 (Observe)

| 关键词 | 广告组 | 状态 | spend | installs | purchase | CPS | Target_CPI | 成熟分母 | 回本率 | 建议 |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- | ---: | :--- |
| {keyword} | {ad_group} | {keyword_status} | {spend} | {installs} | {purchase_users} | {CPS} | {Target_CPI} | {mature_purchases} | {payback_ratio} | {reason} |

## 五、风险与不确定性提示 (Risks & Limitations)
1. **数据不成熟**：未达到续订观察窗口的用户不能用于判断对应RRC，窗口由试用期和账单周期决定。
2. **长尾预测依赖**：更长期的留存依赖衰减曲线预测，若实际产品长期留存偏离该曲线，LTV将存在波动。
```
