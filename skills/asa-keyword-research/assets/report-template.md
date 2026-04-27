# Deliverable Template

Use the following Markdown structures as the blueprint for your output.
Adapt the headings and labels to match the user's requested language.

## Strategy Report

```md
# Apple Search Ads (ASA) Keyword Research Report

**App Name**: [App Name]
**Target Country/Region**: [Country]
**Report Date**: [YYYY-MM-DD]

---

## 1. Product Profile
- **Core Function**: [Core functionality]
- **Value Proposition**: [Value props]
- **Target Audience**: [User personas]
- **Main Subscription Price**: [e.g., $9.99/Year]

## 2. ROI & Target CPA Calculation
*Based on empirical data: 10% signup rate, 4 average renewals, 15% Apple Tax.*
- **Net Revenue**: [Price] × 0.85 = [Value]
- **Estimated LTV**: [Net Revenue] × 4 = [Value]
- **Break-even CPA**: [LTV] × 10% = **[Value]** *(Max allowable CPA)*
- **Target CPA (Launch Phase)**: Break-even CPA × 0.8 = **[Value]** *(Reserving 20% margin)*

## 3. Keyword Matrix

### 🏆 Brand
| Keyword | Estimated SP | Intent | Suggested CPT | Target CPA |
| :--- | :--- | :--- | :--- | :--- |
| [keyword] | [sp] | [intent] | [cpt] | [cpa] |

### 🎯 Generic
| Keyword | Estimated SP | Competition | Suggested CPT | Target CPA |
| :--- | :--- | :--- | :--- | :--- |
| [keyword] | [sp] | [comp] | [cpt] | [cpa] |

### ⚔️ Competitor
| Competitor Name | Keyword | Estimated SP | Suggested CPT | Target CPA |
| :--- | :--- | :--- | :--- | :--- |
| [comp_name] | [keyword] | [sp] | [cpt] | [cpa] |

## 3. Campaign Strategy

> Default Architecture: Exact Match is the primary budget driver; Broad Match is only used for Discovery; Search Match is only a low-budget experiment when explicitly requested.
> 
> **Important Formatting Rule for Keywords**: For Exact Match, wrap each keyword in brackets and separate them with commas (e.g., `[keyword1], [keyword2]`). For Broad Match, omit the brackets (e.g., `keyword1, keyword2`). This ensures they can be copy-pasted directly into the ASA console.

### 📂 Campaign: [Brand - Defense]
**Strategy**: Lock in 100% Share of Voice, bid high, protect brand assets.

| Ad Group | Match Type | Keywords | Suggested CPT | Target CPA |
| :--- | :--- | :--- | :--- | :--- |
| `Brand_Exact` | Exact | [[keyword_1], [keyword_2]] | [cpt] | [cpa] |

### 📂 Campaign: [Generic]
**Strategy**: Group by semantic function (Cluster) to adjust bids per feature.

| Ad Group (Cluster) | Match Type | Keywords | Suggested CPT | Target CPA |
| :--- | :--- | :--- | :--- | :--- |
| `[Cluster_Name_1]` | Exact | [[keyword_1], [keyword_2]] | [cpt] | [cpa] |
| `[Cluster_Name_2]` | Exact | [[keyword_3], [keyword_4]] | [cpt] | [cpa] |

### 📂 Campaign: [Competitor - Conquesting]
**Strategy**: Target direct competitors to siphon brand traffic, closely monitor CPA.

| Ad Group | Match Type | Keywords | Suggested CPT | Target CPA |
| :--- | :--- | :--- | :--- | :--- |
| `[Competitor_Name]` | Exact | [[comp_word_1], [comp_word_2]] | [cpt] | [cpa] |

### 📂 Campaign: [Discovery]
**Strategy**: **[Search Match disabled by default]**. Find long-tail commercial keywords via broad match on core seeds. Must be paired with strict negative keywords.

| Ad Group | Match Type | Keywords | Suggested CPT | Target CPA |
| :--- | :--- | :--- | :--- | :--- |
| `Discovery_Broad` | Broad | core_seed_1, core_seed_2 | [cpt] | [cpa] |

## 4. Negative Keywords
- **Global Negative**: [negative_word] (Reason: [reason])
- **Discovery Isolation**: [exact_keywords] (Prevent Discovery from cannibalizing Exact Match weight)

---

## 5. Execution Advice
1. **Verification & Setup**: Please download the attached `asa-keywords-*.csv` file. This table is strictly organized by the hierarchy `Campaign Name -> Ad Group Name (Cluster) -> Keyword`.
2. **Bulk Upload**: Because this data structure maps to the ASA account hierarchy, you can copy the core columns (Campaign, Ad Group, Keyword, Match Type, Bid) and paste them directly into Apple Search Ads' official Campaign Management (Bulk Upload) template for efficient mass creation.
3. **Cold Start**: We do not recommend frequently adjusting CPT within the first 3-5 days. Wait for Impressions and Taps to accumulate baseline data.
```
