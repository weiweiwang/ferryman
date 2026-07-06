# Source Playbook

Use this reference when collecting demand signals.

## Source Priority

Prefer sources where users describe their own problem in natural language:

1. Reddit posts and comments
2. App Store / Play Store reviews
3. Niche forums and Discord-exported/public forum threads
4. Product Hunt comments and alternatives pages
5. Hacker News / Indie Hackers / developer communities
6. YouTube comments for tutorial-heavy workflows
7. Competitor support forums, changelogs, and feature-request boards
8. Search autocomplete, People Also Ask, related searches, and exact-match competitor pages

Marketing pages are useful for competitor coverage, but weak for discovering pain unless paired with user complaints.

## Query Patterns

Use problem-shaped queries:

- `"is there an app for" <domain>`
- `"looking for an app" <workflow>`
- `"app that lets me" <job>`
- `"I tried Notion" <workflow>`
- `"too complicated" <category> app`
- `"alternative to" <competitor> <pain>`
- `"wish there was" <workflow>`
- `"how do you track" <workflow> reddit`
- `"best app for" <workflow> "too expensive"`
- Reddit RSS: `https://www.reddit.com/search.rss?q=<query>`
- Subreddit RSS: `https://www.reddit.com/r/<subreddit>/search.rss?q=<query>&restrict_sr=on`
- `site:reddit.com/r/<subreddit> "app" "wish"`
- `site:reddit.com/r/<subreddit> "Notion" "too much"`
- `site:apps.apple.com <competitor> reviews <pain phrase>`
- `"<competitor>" "App Store" "Ratings and Reviews"`
- `"<category> app" "App Store" "too complicated"`
- `"<category> app" "Play Store" "too complicated"`

Use audience-shaped queries:

- `"for couples" chore app reddit`
- `"for ADHD" task app too complicated`
- `"for freelancers" invoice tracker spreadsheet`
- `"for parents" schedule app overwhelmed`
- `"for students" study planner app not notion`

## Default Broad Discovery Seeds

When the user asks for new product opportunities without naming a domain, sample several unrelated areas before ranking. Use these as starting seeds and replace weak categories quickly:

| Area | Example Subreddits / Sources | Example Demand Queries |
|---|---|---|
| Home and repairs | `homeowners`, `DIY`, home app reviews | `home maintenance checklist spreadsheet`, `new homeowner overwhelmed app` |
| Travel and events | `travel`, `solotravel`, itinerary tool reviews | `group trip budget spreadsheet`, `travel planning app too complicated` |
| Finance-lite and bookkeeping | `Bookkeeping`, `freelance`, invoice app reviews | `invoice tracker spreadsheet freelancer`, `csv cleanup bank statement` |
| Creators and marketing | `socialmedia`, creator tool reviews | `content calendar approval spreadsheet`, `brand deal tracker spreadsheet` |
| Students and learning | `GetStudying`, student app reviews | `study planner overwhelmed assignments`, `adaptive study planner missed days` |
| Local services and small business | `smallbusiness`, trade forums, service app reviews | `quote calculator spreadsheet`, `job scheduling app too expensive` |
| File and data utilities | workflow forums, app reviews, search snippets | `pdf to csv safe tool`, `merge csv cleanup tool` |
| Parents and households | parenting forums, chore app reviews | `family schedule app overwhelmed`, `chore app leaderboard simple` |
| Health-log without advice | patient communities and health tracker reviews | `symptom log printable tracker`, `appointment prep checklist` |

Avoid regulated advice products. For health, legal, tax, or finance, prefer logs, checklists, calculators with clear disclaimers, file helpers, or prep sheets over diagnosis, recommendations, or compliance claims.

## Signal Strength

Strong signals:

- Multiple users describe the same workaround or abandonment pattern.
- Users name tools they tried and why they quit.
- Users ask for a product-shaped solution.
- The workflow repeats and has a clear trigger.
- Users already pay for adjacent products or tolerate painful manual work.

Weak signals:

- One vague complaint without a repeated job.
- A novelty request with no retention.
- A broad category like "AI productivity app" without a concrete workflow.
- A solution request that existing tools already satisfy cleanly.

## Fallback Paths

When Reddit or another community source is blocked, rate-limited, or noisy, pivot quickly:

- App Store / Play Store review pages: use rating count, review language, pricing, and feature claims to infer pain intensity, retention, and willingness to pay.
- Competitor support forums and feature boards: use repeated complaints, duplicate requests, and workaround threads.
- Product Hunt comments and alternative pages: use launch comments for novelty, comparison language, and switching objections.
- Search result snippets: use only as weak directional evidence unless backed by a primary source.

Do not treat a competitor's marketing copy as direct demand evidence. Pair it with reviews, support requests, forum posts, or search language.

## Evidence Hygiene

- Provide URLs for web-derived evidence.
- Use compliant short quotes only when needed; otherwise paraphrase.
- Record dates when recency matters.
- Record blocked or unavailable sources and the fallback sources used.
- Label inferences as interpretation.
- Do not fabricate search volume, market size, review counts, or pricing.
