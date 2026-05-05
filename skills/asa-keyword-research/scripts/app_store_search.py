import argparse
import json
import logging
import sys

import requests

from app_store_suggester import DEFAULT_USER_AGENT, AppStoreSuggester, SuggestionLookupError

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


class AppStoreSearchError(RuntimeError):
    """Raised when App Store search results cannot be retrieved reliably."""


class AppStoreSearchClient:
    def __init__(self) -> None:
        self.url = "https://itunes.apple.com/search"
        self.suggester = AppStoreSuggester()

    def build_params(self, term: str, country_code: str, limit: int) -> dict[str, str | int]:
        country_code = country_code.upper()
        if country_code not in self.suggester.countries:
            supported = ", ".join(sorted(self.suggester.countries))
            raise AppStoreSearchError(f"未知国家代码: {country_code}. 支持: {supported}")
        return {
            "term": term,
            "country": country_code,
            "entity": "software",
            "limit": max(1, min(limit, 50)),
        }

    def search_apps(self, term: str, country_code: str = "US", limit: int = 20) -> dict[str, object]:
        params = self.build_params(term, country_code, limit)
        language = self.suggester.get_language(country_code)
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept-Language": language,
        }

        try:
            response = requests.get(self.url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise AppStoreSearchError(f"请求 iTunes Search API 失败: {exc}") from exc
        except ValueError as exc:
            raise AppStoreSearchError("iTunes Search API 返回了无法解析的 JSON 数据") from exc

        results = []
        for item in payload.get("results", []):
            if not isinstance(item, dict):
                continue
            results.append(
                {
                    "track_id": item.get("trackId"),
                    "track_name": item.get("trackName"),
                    "seller_name": item.get("sellerName"),
                    "bundle_id": item.get("bundleId"),
                    "primary_genre": item.get("primaryGenreName"),
                    "average_user_rating": item.get("averageUserRating"),
                    "user_rating_count": item.get("userRatingCount"),
                    "price": item.get("price"),
                    "currency": item.get("currency"),
                    "track_view_url": item.get("trackViewUrl"),
                    "description": item.get("description"),
                }
            )

        return {
            "ok": True,
            "term": term,
            "country": params["country"],
            "language": language,
            "source": "itunes_search_api",
            "result_count": len(results),
            "results": results,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="搜索 App Store app 候选竞品")
    parser.add_argument("--term", required=True, help="搜索关键词")
    parser.add_argument("--country", default="US", help="国家代码 (如 CN, US, JP)")
    parser.add_argument("--limit", type=int, default=20, help="返回数量，范围 1-50")
    args = parser.parse_args()

    client = AppStoreSearchClient()
    try:
        result = client.search_apps(args.term, args.country, args.limit)
    except (AppStoreSearchError, SuggestionLookupError) as exc:
        logger.error(str(exc))
        print(
            json.dumps(
                {"ok": False, "error": {"type": exc.__class__.__name__, "message": str(exc)}},
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False))
