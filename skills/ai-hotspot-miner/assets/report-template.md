# Deliverable Template

Use the following Markdown structures as the blueprint for your output. Adapt the headings and labels to match the user's requested language and channel.

## Research Brief

```md
# AI Hotspot Brief

**Date**: [YYYY-MM-DD]  
**Scope**: [AI news / launches / repos / research / mixed]  
**Sources Scanned**: [List of domains actually scanned]  
**Source Budget Notes**: [How many meaningful sources were used and why that was enough]  

## Publication Profile

- **Publication / Channel**: [e.g. WeChat public account / newsletter / blog]
- **Brand Name**: [Name or "Not provided"]
- **Audience**: [Who the article is for]
- **Positioning**: [How the publication wants to be perceived]
- **Growth Goal**: [Clicks / shares / follows / authority / mixed]
- **Tone**: [restrained / analytical / practical / sharp / etc.]

## Executive Summary

- **Hotspot Count**: [N]
- **Overall Signal Quality**: [High / Medium / Low]
- **Main Takeaway**: [1-2 sentence summary of today's meta-trend]

## Candidate Topics

### 1. [Candidate Topic]

- **Why It Matters Now**: [Freshness or shift]
- **Audience Fit**: [Why the intended audience would care]
- **Attention Rationale**: [Why it may earn opens, reads, shares, or follows]
- **Editorial Risk**: [Too crowded / too technical / too early / etc.]
- **Source Confidence**: [High / Medium / Low]
- **Why Not Chosen**: [Why this is not today's best publishing choice]
- **What Would Make It Stronger**: [What missing evidence, traction, or angle would improve it]

### 2. [Candidate Topic]
*(Repeat as needed; usually 3 candidates are enough)*

## Recommended Topic

- **Chosen Topic**: [Title]
- **Recommended Angle**: [Concrete framing]
- **Why This One Wins**: [Why this topic is the best publishing choice today]
- **Format Decision**: [Single-topic article / Roundup]

## Claim Layers

### Confirmed Facts

- [Fact 1]
- [Fact 2]

### Interpretation

- [What the confirmed facts suggest]

### What To Watch

- [Forward-looking implication or uncertainty]

## Top Hotspots

### 1. [Hotspot Title]

- **Type**: [product / repo / model / research / benchmark / market_topic / other]
- **Ranking**: [high / medium / low]
- **Value**: [Why it matters / Strategic impact]
- **Editorial Angle**: [Best user-facing frame]
- **Attention Rationale**: [Why the topic can travel]
- **Supporting Sources**: [List domains]
- **Source URLs**: [List direct URLs used as evidence]
- **Observed At UTC**: [YYYY-MM-DDTHH:MM:SSZ]
- **Evidence Snippets**: [Concise metrics, upvotes, or factual text snippets establishing this hotspot]

### 2. [Hotspot Title]
*(Repeat schema for each identified hotspot)*

## Cross-Source Evidence Matrix

| Hotspot | Source | Source URL | Observed At UTC | Key Signal / Metric |
| :------ | :----- | :--------- | :-------------- | :------------------ |
| [Title] | [Domain] | [URL] | [YYYY-MM-DDTHH:MM:SSZ] | [e.g., 500 upvotes] |

## Blocked / Weak Sources & Methodology

- **Blocked/Weak Domains**: [List any sources that failed to load, hit CAPTCHAs, or lacked valid AI content]
- **Methodology Notes**: [Briefly summarize any autonomous search pivots or navigation decisions made during this session]
- **Why Research Stopped Here**: [Why the evidence was sufficient or why deeper browsing would have low return]
```

## Article Draft

Use this exact structure for the publishable article output. The article file is the clean publication source; it must contain only the final title and final body.

```md
# [One final title only]

[Final copy-paste-ready article body only]
```

Do not include date metadata, publication profile, article strategy, title candidates, fact-check notes, source URLs, `Operations Publishing Zone` markers, or handoff instructions in this article file. Put all non-publication material in the research brief.

## Formatted Article HTML

After saving the publishable article Markdown, generate the formatted HTML file with:

```sh
scripts/render_article_html.py reports/<yyyy-mm-dd>/ai-hotspot-article-<article_slug>.md
```

The generated file must be named:

```md
reports/<yyyy-mm-dd>/ai-hotspot-article-<article_slug>.html
```

This HTML file is a copy-paste-ready formatted rendering for a rich-text editor. It renders the clean article Markdown directly.
