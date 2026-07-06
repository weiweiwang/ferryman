# Reddit Data Acquisition

Use this reference when Reddit evidence matters.

## Recommended Order

1. **RSS/Atom search with automatic Old Reddit fallback**: use `scripts/reddit_rss_search.py` for logged-out, low-volume discovery. It returns post titles, URLs, authors, subreddits, timestamps, and body snippets when available. If RSS returns `403`, `429`, or a network error, the script falls back to Old Reddit HTML.
2. **Old Reddit HTML direct inspection**: use `https://old.reddit.com/search?q=<query>` when RSS needs visual inspection, comment counts, scores, or the next-page cursor.
3. **Official OAuth Data API**: use only when the task requires authenticated access, higher reliability, or endpoints that RSS cannot provide. Reddit's public API docs describe listing pagination and OAuth behavior; Reddit's wiki says developers must follow the Responsible Builder Policy, Developer Terms, and Data API Terms.
4. **Search engine `site:reddit.com` queries**: use as a discovery fallback, then open the Reddit result itself when possible.
5. **Third-party archives or mirrors**: use only as weak fallback evidence and label them clearly.

## What Works Without OAuth

- Global post search: `https://www.reddit.com/search.rss?q=<query>`
- Subreddit-scoped post search: `https://www.reddit.com/r/<subreddit>/search.rss?q=<query>&restrict_sr=on`
- Old Reddit search page: `https://old.reddit.com/search?q=<query>`
- Old Reddit subreddit search: `https://old.reddit.com/r/<subreddit>/search?q=<query>&restrict_sr=on`

RSS is usually enough for product opportunity mining because it exposes raw titles and selftext snippets. Use several query variants and deduplicate URLs.

## Known Failure Modes

- `www.reddit.com/*.json` may return `403` even with a User-Agent.
- RSS can rate-limit with `429` or temporarily return sparse results; use Old Reddit fallback and slow down repeated queries.
- Search results may include subreddits, promotional posts, or off-topic matches.
- Comment bodies are not reliably available from RSS search. Open high-signal posts manually or use OAuth when comment-level mining is required.

## OAuth Escalation

Use OAuth when the task needs repeatable comment mining, higher request limits, or reliable listing pagination. At minimum, the operator needs a Reddit app client id/secret and should use the smallest required scopes, usually `read` for public content. Do not ask users for Reddit credentials directly; use app credentials or an approved local environment variable flow.

## Evidence Handling

- Prefer raw Reddit post URLs in reports.
- Paraphrase user language unless a short quote is essential.
- Record query strings and source type: `rss`, `old-reddit-html`, `oauth`, or `search-engine`.
- Label scraped snippets as partial evidence when comments were not inspected.
