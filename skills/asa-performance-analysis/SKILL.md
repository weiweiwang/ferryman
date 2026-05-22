---
name: asa-performance-analysis
description: >
  Use this for Apple Search Ads (ASA) post-campaign performance analysis,
  BigQuery attribution and purchase cohort reporting, keyword-level CPR/RRC
  diagnostics, and optimization decision support for App Store ads.
version: 1.0.0
author: Ferryman
created: 2026-05-22
updated: 2026-05-22
---

# ASA Performance Analysis

**专家目标**：从BigQuery拉取分天粒度的ASA关键词表现数据，通过Python在本地进行订阅归因队列分析，排除队列成熟度偏差（Cohort Maturity Bias），计算精确的LTV6与多维度订阅健康指标，最终生成包含出价调整、停投、否词屏蔽等专家级优化决策的分析报告。

## 一、核心数学模型与数据说明

本技能将分析工作流中的复杂数学计算（包括LTV6、成熟期校正以及转化成本转换）完全下放到数据提取脚本 `fetch_asa_bigquery_report.py` 中。智能体**严禁**自行编写或执行临时Python脚本进行数据清洗和数学计算，只需直接读取并分析生成的CSV报表。

### 1. 核心计算指标说明
脚本在提取并聚合数据时已完成了以下计算：
- **无偏差续订率（RRC1, RRC2, RRC3）**：通过队列成熟度截止日（Cut-off Date）过滤，仅累加已到达续订点（试用期+账单周期天数）的成熟用户，排除由于“近期获取用户尚未到达续订点”导致的生存偏差（Survival Bias）。
- **订阅LTV6（6个月生命周期价值）**：基于输入的首期毛价、常规续费毛价、试用天数、计费天数和苹果税率（默认15%），根据180天内最大计费期数（Weekly约为25期，Monthly约为5期，Yearly为0期），乘以对应的无偏差续订率（缺失或未成熟期使用行业默认衰减曲线估算）进行累加计算。
- **预估6个月净收入（expected_revenue_6m）**：$\text{LTV6\_per\_purchase\_user} \times \text{purchase\_users}$。
- **预估6个月回本率（payback_ratio_6m）**：$\text{expected\_revenue\_6m} / \text{spend}$。
- **目标CPA（Target_CPA）**：根据每次购买签约成本目标（Target CPS）和安装到购买率自动转换所得：$\text{Target\_CPA} = \text{Target\_Purchase\_CPS} \times \frac{\text{purchase\_users}}{\text{installs}}$。

### 2. 智能体职责定义
- **最终决策与定性诊断**：智能体是整个优化流程的决策大脑。大模型负责读取并分析客观数据、进行定性诊断与异常指标归因（例如通过 `ASR15m` 评估订阅质量），并在研判数据置信度后输出最终的优化动作决策（如 Scale、Lower Bid、Pause、Observe 等）。
- **脚本定位**：Python 脚本仅作为客观的数据计算工具，提供无偏差的数学指标（如 LTV6、回本率、目标 CPA 等），脚本本身不参与任何规则判断与决策生成。
- **杜绝运行时脚本计算**：智能体应直接读取汇总 CSV 和分切片 CSV（如 `ruc1`, `ruc2`, `ruc3`），**绝对禁止**尝试通过编写本地 Python 脚本对数据进行二次加工。

---

## 二、匹配类型优化策略

在进行决策时，必须严格区分关键词的匹配类型（Match Type）：

### 1. 精确匹配（Exact Match）
- **特点**：流量精准，用户意图强。
- **优化路径**：
  - **Payback6 >= 1.0**：调高出价（Raise Bid），获取更多曝光。
  - **Payback6 < 1.0**：若数据充足且CPS过高，通过降低出价（Lower Bid）使实际CPA逼近 `Target_CPA`；若CPS依然失控或续订率极低，则暂停（Pause）。

### 2. 广泛匹配/搜索匹配（Broad Match / Search Match）
- **特点**：用于拓词与流量探测，杂音大。
- **优化路径**：
  - **核心动作是“否词”而非单纯调整出价**。必须分析搜索词报告，针对高消耗、无转化或偏离产品定位的搜索词，在ASA后台添加为“否定关键词（Negative Keywords）”。
  - 只有在搜索词结构健康但整体流量包CPS偏高时，才降低该广泛匹配关键词的出价。

---

## 三、分析决策SOP

### 1. 数据准备与脚本执行
确认参数：`bundle_id`、输出CSV路径、`start_date`、目标本位币（默认CNY）、试用期天数（`--trial-days`，默认7）、账单周期天数（`--billing-period-days`，默认30）、首期毛收入（`--first-purchase-gross`）、常规续费毛价（`--regular-period-gross`）、苹果税率（`--apple-fee`，默认0.15）、目标CPS（`--target-cps`）。

**凭证处理规范(重要)**：
- 脚本执行需要GCP BigQuery访问凭证。优先依赖环境变量`ASA_BIGQUERY_SERVICE_ACCOUNT_JSON`或`GOOGLE_APPLICATION_CREDENTIALS`。由于Ferryman后端已支持在macOS GUI启动时动态继承当前用户的终端shell环境变量，因此大多数情况下无需显式传递凭证文件参数。
- 如果环境变量未设置，或者需要覆盖默认凭证，则可以使用 `--credentials-file` 参数指定凭证路径。
- **用户当前的正确本地凭证路径为**：`/Users/wangweiwei/Library/Mobile Documents/com~apple~CloudDocs/chatgpt/公司/晦朔移动/ASA/asa-analysis-service-account.json`
- **严禁**虚构、猜测或盲目传入不存在的默认凭证路径。

执行数据提取命令示例：
```bash
conda run -n ferryman python skills/asa-performance-analysis/scripts/fetch_asa_bigquery_report.py \
  --bundle-id app.blynkai.todo \
  --output reports/2026-05-22/asa-performance-app-blynkai-todo-2026-04-22.csv \
  --start-date 2026-04-22 \
  --target-currency CNY \
  --trial-days 7 \
  --billing-period-days 30 \
  --credentials-file "/Users/wangweiwei/Library/Mobile Documents/com~apple~CloudDocs/chatgpt/公司/晦朔移动/ASA/asa-analysis-service-account.json"
```

该命令执行后，除了在指定的`--output`路径下生成整体关键词聚合汇总表（例如`report.csv`）外，还会自动在其同级目录下生成以下四个拆分CSV文件（对于未成熟的数据切片，对应的聚合表可能为空，仅包含表头），以便智能体直接扫描和深入分析：
- `report_daily.csv`：按天维度的原始明细数据，包含完整字段，用于趋势与波动分析。
- `report_ruc1.csv`：对`report_date <= ruc1_cutoff`的成熟期数据进行切片后的关键词聚合表。列名为常规的`purchases`、`renewals`和`RRC`。
- `report_ruc2.csv`：对`report_date <= ruc2_cutoff`的成熟期数据进行切片后的关键词聚合表。列名为常规的`purchases`、`renewals`和`RRC`。
- `report_ruc3.csv`：对`report_date <= ruc3_cutoff`的成熟期数据进行切片后的关键词聚合表。列名为常规的`purchases`、`renewals`和`RRC`。

### 2. 置信度与数据充要性研判
对关键词的数据量进行分级：
- **转化信号（Conversion Signal）**：
  - `installs < 10` 且 `clicks < 30`：无置信度，直接判定为 **Observe**。
  - `installs >= 10`：弱置信度；`installs >= 20`：中等置信度；`installs >= 50`：高置信度。
- **购买信号（Purchase Signal）**：
  - `purchase_users = 0` 且 `spend` 已达到目标CPS的1.5倍以上：可判定为 **Pause**。
  - `purchase_users >= 3`：有方向性购买信号；`purchase_users >= 10`：强购买信号。
- **续订信号（Renewal Signal）**：
  - `RUC1_mature_purchases >= 5`：弱置信度；`RUC1_mature_purchases >= 10`：中等置信度；`RUC1_mature_purchases >= 20`：高置信度。
  - **警惕**：若 `RUC1_mature_purchases = 0`，代表该关键词的首期用户还未到续费点，即便 `RUC1 = 0` 也不能代表流失，必须判定为 **Observe**。

### 3. 基准（Benchmark）制定
筛选出 `payback_ratio_6m >= 1.0` 且具有中等及以上置信度（`purchase_users >= 3` 且 `RUC1_mature_purchases >= 5`）的优质关键词集合，计算其平均 `CVR`、`RRC1` 和 `CPC` 作为全账户的“健康基准值”，用以指导弱表现关键词的归因诊断。

### 4. 优化动作决策矩阵

| 状态分类 | 判定条件 | 核心推荐动作 |
| :--- | :--- | :--- |
| **Scale (拓量)** | `payback_ratio_6m >= 1.2` 且数据置信度中等及以上 | 提高出价（每次+10%~20%），确保预算充足 |
| **Keep (维持)** | `0.9 <= payback_ratio_6m < 1.2` 且表现稳定 | 维持当前出价与预算 |
| **Lower Bid (降价)** | `payback_ratio_6m < 0.9` 且有真实购买转化，降幅缺口（`required_CPS_reduction`） $\le 50\%$ | 降低出价，幅度可参考：$\text{New\_Bid} = \text{Current\_Bid} \times \frac{\text{Target\_CPA}}{\text{Actual\_CPA}}$ |
| **Pause (暂停)** | `payback_ratio_6m < 0.9` 且有成熟购买但 $\text{RRC1}$ 极低，或降幅缺口 $> 50\%$；或无购买转化且消耗已超过目标CPS的1.5倍 | 暂停关键词投放 |
| **Observe (观察)** | 消耗低，数据未达置信度门槛，或 $\text{RUC1\_mature\_purchases} = 0$ | 保持观察，不做实质动作，等待数据累积 |
| **Review Only (仅复盘)** | 关键词状态为 `PAUSED` | 仅做历史复盘与成效总结，不建议重新开启 |

---

## 四、输出规范与模板

### 1. CSV格式规范（Action CSV）
分析产生的决策应生成对应的 CSV 文件，表头契约如下：
```csv
keyword,action,reason,payback_ratio_6m,required_CPS_reduction,confidence,keyword_status,spend,daily_spend,purchase_users,RUC1,RRC1,RRC2,RRC3,CPS,CPR1,LTV6_per_purchase_user,expected_revenue_6m,breakeven_CPS,ad_group,match_type,days,clicks,installs,RUC2,RUC3,CVR,priority,ad_group_id
```

### 2. 诊断报告模板（Markdown Report）
分析报告需使用中文输出，中英文边界不加空格。

```markdown
# ASA关键词表现与队列LTV分析报告

## 一、核心评估假设 (Assumptions)
- **分析周期**：YYYY-MM-DD 至 YYYY-MM-DD (共 {days} 天)
- **应用App ID**：{bundle_id}
- **订阅模式**：[免费试用 (如7天试用+30天续订) / 无免费试用直接付费]
- **产品毛价**：{monthly_gross_price} {currency} | **首期毛收入**：{first_purchase_gross_revenue} {currency}
- **苹果渠道税率**：{apple_fee}%
- **回本周期目标**：6个月 (Payback6)

## 二、账户整体表现 (Account Summary)
- **总消耗**：{total_spend} {currency} | **每日均消耗**：{daily_spend} {currency}
- **总购买人数**：{total_purchase_users} | **总首期续订数**：{total_ruc1}
- **平均每次购买成本 (CPS)**：{account_cps} {currency} | **平均首期续订成本 (CPR1)**：{account_cpr1} {currency}
- **无偏差首期续订率 (RRC1)**：{account_rrc1}% (成熟分母：{account_ruc1_mature_purchases})
- **预估6个月净收入**：{estimated_revenue_6m} {currency}
- **预估6个月回本率 (Payback Ratio)**：{account_payback_ratio}%

## 三、健康账户基准 (Healthy Benchmark)
- **优质基准词数**：{benchmark_count} 个
- **基准线 CVR**：{benchmark_cvr}% | **基准线 RRC1**：{benchmark_rrc1}%
- **基准回本率 (Payback6)**：{benchmark_payback_ratio}%

| 关键词 (Keyword) | 匹配类型 | 消耗 (Spend) | 购买成本 (CPS) | 购买人数 | RRC1 | 6月回本率 | 诊断结论 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| example_exact | EXACT | 120.00 | 15.00 | 8 | 50.00% | 125.0% | 表现健康，回本符合预期 |

## 四、核心优化决策 (Key Actions)
*(注：以下仅列出高影响力/高消耗的代表性词，完整列表见决策CSV：[action_csv_basename](file:///path/to/csv))*

### 1. 拓量 (Scale)
- **{keyword}** ({match_type} | 消耗: {spend} | 回本率: {payback_ratio}): [决策逻辑，如：回本表现极佳，CVR高于基准，建议提价15%夺取曝光。]

### 2. 降低出价 (Lower Bid)
- **{keyword}** ({match_type} | 消耗: {spend} | CPS: {cps}): [决策逻辑，如：匹配类型为EXACT，有稳定付费转化，但CPS超标30%。目前Install-to-Purchase为10%，建议控制台目标CPA由原出价调低至{target_cpa} {currency}。]

### 3. 暂停投放 (Pause)
- **{keyword}** ({match_type} | 消耗: {spend} | 转化数: {purchase_users}): [决策逻辑，如：EXACT词，消耗已达{spend}且无任何购买用户；或RRC1为0%已完全成熟，判断无法回本，建议立即暂停。]

### 4. 否词屏蔽 (Negative Keywords)
- **{keyword}** ({match_type} | 消耗: {spend}): [决策逻辑，如：广泛匹配/搜索匹配流量混杂。搜索词报告显示存在大量[无效搜索词]，导致整体CPS偏高，建议在后台将[无效搜索词]添加为精确否定词，不调整该广泛匹配词的出价。]

### 5. 保持观察 (Observe)
- **{keyword}** ({match_type} | 消耗: {spend} | 成熟分母: {mature_purchases}): [决策逻辑，如：用户均未达续订期，RRC1尚未成熟，首期流失率具有欺骗性，建议继续观察。]

## 五、风险与不确定性提示 (Risks & Limitations)
1. **数据不成熟**：近期（近38天内）获取的用户尚未经过续订点，本报告已通过分天归因排除此偏差，但整体数据量仍偏少。
2. **长尾预测依赖**：RUC4及以后的留存基于70%-90%的行业衰减率预测，若实际产品长期留存偏离该曲线，LTV6将存在波动。
