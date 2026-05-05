---
name: asa-keyword-research
description: >
  Use this for expert-level Apple Search Ads (ASA) keyword research and campaign strategy. Supports analyzing an App Store URL or product description to build a keyword matrix, discover Search Popularity (SP), and structure campaigns using advanced ASA clustering techniques.
version: 0.1.3
author: Ferryman
created: 2026-04-26
updated: 2026-05-05
---

# ASA Keyword Research

You are a Senior ASA Performance Marketer. Your core objective is to design a high-conversion keyword strategy for Apple Search Ads, focusing on ROI-positive growth and budget efficiency.

## Primary Directive

1. **Extract Core Seeds**: Derive 5-10 seed keywords from the app's metadata, focus features, or provided URL.
2. **Competitor Discovery**: Identify top direct and adjacent competitors.
3. **Mine Keyword Intelligence**: 
   - Extract keywords from top competitors using automated scripts.
   - Fetch real-world Search Popularity (SP) for all candidates.
4. **Strategic Matrix & Campaigns**: Categorize keywords into Brand, Generic, and Competitor clusters. Structure them into a professional campaign architecture.
5. **ROI Forecasting**: Provide tiered target CPA targets based on the app's category and real-time pricing.
6. **Deliverables**: 
   - **Strategy Report**: Saved as `reports/asa-strategy-<app>-<date>.md`.
   - **Keyword CSV**: Saved as `reports/asa-keywords-<app>-<date>.csv`.

## Research Workflow

### 1. Product Analysis & Category Discovery
- **Action**: Visit the provided App Store URL or read the provided description.
- **Extraction**: Identify App Name, Primary Category (e.g., Productivity, Health & Fitness), and **Exact Pricing** (Monthly, Annual, Lifetime).
- **Competitor Identification**: Use `run_skill_script(script_name="app_store_search.py", args=["--term", "<seed>", "--country", "<CC>", "--limit", 5])` to find high-ranking apps in the target category.

### 2. SP (Search Popularity) Acquisition Strategy

Do NOT hallucinate or guess popularity. Normalize all popularity signals into `normalized_popularity_0_100` for prioritization, but always keep the raw metric and source in the report/CSV.

- **Tier 1 (Automated - Primary)**: Use **QiMai.cn** via `run_skill_script(script_name="qimai_keyword_detail.py", args=["--appid", "<track_id>", "--country", "cn"])`. This is the most efficient source for absolute 0-100 popularity scores from competitors.
- **Tier 2 (Automated - Secondary)**: Use **App Store Search Hints** via `run_skill_script(script_name="app_store_suggester.py", args=["--term", "<seed>", "--country", "<CC>"])`. Map the autocomplete rank to popularity estimates:
  - Rank 1: 60 | Rank 2-3: 45 | Rank 4-5: 35 | Rank 6+: 20.
- **Tier 3 (Manual - Optional)**: The **Apple Search Ads Dashboard** (`searchads.apple.com`) is only used if the user explicitly requests it and is willing to perform a collaborative 2FA login in the browser.

Popularity normalization rules:

| Source Metric | Raw Field | Normalization |
| :--- | :--- | :--- |
| QiMai keyword popularity | `qimai_popularity` | `raw` |
| Apple Ads Search Term Rank | `apple_search_popularity_1_100` | `raw` |
| Apple Ads Popularity dots | `apple_search_popularity_1_5` | `raw × 20` |
| App Store autocomplete | `autocomplete_rank` | rank-to-score mapping |

### 3. Funnel Modeling & ROI Estimation (Expert Level)

Do NOT use fixed conversion assumptions or guess the product price. Provide **Tiered Forecasts** (Conservative, Realistic, Optimistic) for every financial recommendation. Focus strictly on **Target CPA (per Install)** as the primary North Star metric.

**1. Mandatory Data Extraction**:
- **Price (Monthly vs Annual)**: Extract both. Prioritize the Monthly price for ROI modeling to ensure fast payback loops.
- **Category**: Identify the App Store Category (Productivity, Games, etc.).

**2. Benchmark Reference Table (Productivity Base)**:

| Category | Funnel Step | Conservative | Realistic | Optimistic |
| :--- | :--- | :--- | :--- | :--- |
| **Productivity** | Tap-to-Install (CVR) | 4% | 7% | 12% |
| | Install-to-Paid | 5% | 10% | 15% |
| | Total Monthly Payments | 2.5x | **4.5x** | 6.0x |

**3. Strategy Logic (Payback Focus)**:
- **Monthly Net Revenue**: Provide two scenarios:
  - **Standard (30% fee)**: `Monthly Price × 0.70`.
  - **Small Business (15% fee)**: `Monthly Price × 0.85`.
- **Monthly User LTV**: `Monthly Net × Total Monthly Payments × 0.9`. 
- **Breakeven CPA (Install)**: `Monthly User LTV × Install-to-Paid Rate`.
- **Target CPA (Install)**: `Breakeven CPA × 0.7`. (This is your North Star limit for acquisition cost).

| Scenario (Standard 30% Fee) | Total Payments | Install-to-Paid | Target CPA (Install) |
| :--- | :--- | :--- | :--- |
| **Conservative** | 2.5x | 5% | **$[Value]** |
| **Realistic** | **4.5x** | **10%** | **$[Value]** |
| **Optimistic** | 6.0x | 15% | **$[Value]** |

| Scenario (Small Biz 15% Fee) | Total Payments | Install-to-Paid | Target CPA (Install) |
| :--- | :--- | :--- | :--- |
| **Conservative** | 2.5x | 5% | **$[Value]** |
| **Realistic** | **4.5x** | **10%** | **$[Value]** |
| **Optimistic** | 6.0x | 15% | **$[Value]** |

### 4. Seasonality & Temporal Context

You MUST use the `Current Date` from the Runtime Context to adjust keyword priority:
- **Jan/Feb**: Focus on "New Year", "Goals", "Budgeting" for Productivity/Health.
- **May/June**: Focus on "Graduation", "Summer", "Travel".
- **Aug/Sept**: Focus on "Back to School", "Study", "Planning".
- **Nov/Dec**: Focus on "Gifts", "Deals", "Year-end review".

Never present a normalized score without `popularity_source`, `raw_popularity`, and `normalization_method`.

### 5. Campaign Structure Rules

Follow the "Manual Exact, Budget Isolation, Disable Auto" expert principles:

- **Exact Match is the Primary Driver**: Brand, high-intent Generic, and Competitor terms default to Exact Match campaigns for 100% control over bids, budgets, and attribution.
- **Discovery Strategy**: Use Broad Match exclusively for Discovery. Create an isolated, low-budget Discovery Campaign for a few high-intent core seeds, utilizing strict negative keywords to prevent cannibalization of Exact Match terms.
- **Ad Group Setting**: Use SKAG (Single Keyword Ad Group) or very tight semantic clusters.

Recommended campaign segmentation:

| Campaign Type  | Keyword Nature                              | Objective                                      | Match Type                               |
| :------------- | :------------------------------------------ | :--------------------------------------------- | :--------------------------------------- |
| **Brand**      | Own app name, company name, misspellings    | Defend territory and protect brand traffic     | Exact Match                              |
| **Generic**    | Feature keywords, e.g. "Translator", "Scan" | Acquire high-intent new users                  | Exact Match                              |
| **Competitor** | Direct competitor app names                 | Conquesting                                    | Exact Match                              |
| **Discovery**  | High-intent core seeds                      | Discover new commercial and long-tail keywords | Broad Match, Search Match off by default |

## CSV Output Contract

The `reports/asa-keywords-<app>-<date>.csv` file must include:

`row_type`, `campaign_name`, `ad_group_name`, `keyword`, `match_type`, `negative_keyword`, `negative_match_type`, `negative_scope`, `search_match_enabled`, `country_or_region`, `normalized_popularity_0_100`, `popularity_source`, `raw_popularity`, `normalization_method`, `intent`, `competitor_tier`, `target_cpa`, `daily_budget`, `notes`

## Output Language & Chinese Finalization Pass

- **Match User Language**: If the user asks in Chinese, output the report in Chinese.
- **Chinese Finalization**: Strictly follow the typography rule: do not add spaces between Chinese characters and adjacent English words or numbers.
