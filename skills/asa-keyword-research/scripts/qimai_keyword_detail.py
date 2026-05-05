import argparse
import json
import logging
import sys
import requests
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def fetch_qimai_keyword_detail(appid: str, country: str = "cn"):
    """
    Fetch keyword details for a specific app from QiMai.
    Uses direct requests as 'analysis' is not strictly required for this endpoint.
    """
    api_url = f"https://api.qimai.cn/appDetail/keywordDetail?appid={appid}&country={country}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"https://www.qimai.cn/app/keyword/appid/{appid}/country/{country}"
    }
    
    try:
        logger.info(f"Fetching API: {api_url}")
        response = requests.get(api_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return {"ok": False, "error": f"HTTP {response.status_code}"}
            
        data_json = response.json()
        
        if data_json.get("code") == 10000:
            raw_list = data_json.get("data", [])
            formatted_list = []
            for item in raw_list:
                formatted_list.append({
                    "keyword": item.get("word_name") or item.get("word"),
                    "popularity": item.get("popular"),
                    "rank": item.get("erank") or item.get("rank"),
                    "results": item.get("search_no") or item.get("result")
                })
            return {"ok": True, "data": formatted_list, "total": data_json.get("appNum")}
        else:
            return {"ok": False, "error": f"QiMai API error {data_json.get('code')}: {data_json.get('msg')}"}
            
    except Exception as e:
        logger.error(f"Error during QiMai fetch: {e}")
        return {"ok": False, "error": str(e)}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch keyword details from QiMai")
    parser.add_argument("--appid", required=True, help="Apple App ID")
    parser.add_argument("--country", default="cn", help="Country code (default: cn)")
    
    args = parser.parse_args()
    
    result = fetch_qimai_keyword_detail(args.appid, args.country)
    print(json.dumps(result, ensure_ascii=False))
