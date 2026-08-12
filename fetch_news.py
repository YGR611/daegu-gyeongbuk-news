#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
대구경북 뉴스 대시보드 데이터 생성 스크립트

네이버 뉴스 검색 API로 대구경북 관련 기사를 모은 뒤,
1) 관련 없는/저품질 기사 제외 (부고, 인사동정, 광고성 등)
2) 같은 사건을 다룬 중복 기사 묶기
3) 여러 매체가 다룰수록, 최신일수록, 하드뉴스 카테고리일수록 중요도를 높게 계산
4) docs/data.json 으로 저장 (대시보드 HTML이 이 파일을 읽음)

(선택) 유튜브 데이터 API 키가 있으면 대구경북 관련 화제 영상도 함께 수집.
"""

import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

# 검색 쿼리 (대구경북 관련성을 이 단계에서 1차로 확보)
NEWS_QUERIES = [
    "대구",
    "경북",
    "대구시",
    "경상북도",
    "대구경북",
]

# 지역 관련성 재확인용 키워드 (제목+요약에 하나라도 있어야 통과)
REGION_KEYWORDS = [
    "대구", "경북", "경상북도", "대구시", "포항", "안동", "구미", "경산", "김천",
    "영주", "영천", "상주", "문경", "경주", "칠곡", "성주", "고령", "청도", "군위",
    "의성", "청송", "영양", "영덕", "울진", "봉화", "예천", "울릉",
]

# 지역 관련성이 있어도 뉴스로서 가치가 낮아 제외할 카테고리 (부고/인사/공지성)
EXCLUDE_KEYWORDS = [
    "부고", "부음", "인사동정", "동정]", "[인사]", "승진 인사", "정기인사",
    "인사말씀", "축사", "화보", "포토뉴스", "날씨]", "오늘의 날씨",
]

CATEGORY_RULES = [
    ("사건사고", ["사고", "화재", "붕괴", "추락", "폭발", "충돌", "전복", "실종", "익사",
                "교통사고", "산불", "침수", "붕괴사고"], 1.3),
    ("범죄사법", ["구속", "검찰", "기소", "징역", "재판", "수사", "체포", "마약", "사기",
                "경찰", "고소", "고발", "압수수색"], 1.25),
    ("정치행정", ["시장", "도지사", "시의회", "도의회", "국회의원", "예산", "조례",
                "공약", "선거", "국정감사", "시청", "도청"], 1.1),
    ("경제", ["기업", "일자리", "실업률", "부동산", "분양", "수출", "투자", "공장",
             "산업단지", "창업", "물가"], 1.1),
    ("사회복지", ["교육", "복지", "의료", "병원", "학교", "환경", "폭염", "한파",
                "태풍", "호우", "지진", "재난"], 1.15),
    ("문화생활", ["축제", "공연", "전시", "관광", "맛집", "행사", "박람회"], 0.85),
    ("스포츠", ["프로야구", "축구", "야구", "경기", "선수", "우승", "구단"], 0.9),
]

STOPWORDS = set(list("이가을를은는의에서와과도만로으로하다했다되다된다있다없다위해대해"))


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def call_naver(endpoint: str, query: str, display: int = 100, sort: str = "date"):
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 없습니다.")
    url = (
        f"https://openapi.naver.com/v1/search/{endpoint}.json?"
        f"query={urllib.parse.quote(query)}&display={display}&sort={sort}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
            "User-Agent": "daegu-gyeongbuk-news-dashboard",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_all_news():
    seen_links = set()
    articles = []
    for q in NEWS_QUERIES:
        try:
            data = call_naver("news", q, display=100, sort="date")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            print(f"[WARN] '{q}' 검색 실패: HTTP {e.code} {body}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"[WARN] '{q}' 검색 실패: {e}", file=sys.stderr)
            continue

        for item in data.get("items", []):
            link = item.get("originallink") or item.get("link")
            if not link or link in seen_links:
                continue
            seen_links.add(link)

            title = strip_html(item.get("title", ""))
            desc = strip_html(item.get("description", ""))
            pub_raw = item.get("pubDate", "")
            try:
                pub_dt = datetime.strptime(pub_raw, "%a, %d %b %Y %H:%M:%S %z").astimezone(KST)
            except Exception:
                pub_dt = datetime.now(KST)

            press = urllib.parse.urlparse(link).netloc.replace("www.", "")

            articles.append({
                "title": title,
                "desc": desc,
                "link": link,
                "press": press,
                "pub_dt": pub_dt,
            })
        time.sleep(0.15)  # API 예의상 살짝 딜레이
    return articles


def is_relevant(article) -> bool:
    text = article["title"] + " " + article["desc"]
    if not any(k in text for k in REGION_KEYWORDS):
        return False
    if any(k in text for k in EXCLUDE_KEYWORDS):
        return False
    return True


def classify(article):
    text = article["title"] + " " + article["desc"]
    best = ("일반", 1.0)
    for name, keywords, weight in CATEGORY_RULES:
        if any(k in text for k in keywords):
            best = (name, weight)
            break
    return best


def tokenize(title: str):
    words = re.findall(r"[가-힣A-Za-z0-9]+", title)
    return set(w for w in words if len(w) > 1 and w not in STOPWORDS)


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def cluster_articles(articles, window_hours=30, threshold=0.45):
    """같은 사건을 다룬 기사를 묶는다 (union-find)."""
    n = len(articles)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    tokens = [tokenize(a["title"]) for a in articles]
    for i in range(n):
        for j in range(i + 1, n):
            dt = abs((articles[i]["pub_dt"] - articles[j]["pub_dt"]).total_seconds()) / 3600
            if dt > window_hours:
                continue
            if jaccard(tokens[i], tokens[j]) >= threshold:
                union(i, j)

    groups = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)
    return list(groups.values())


def build_dataset():
    raw = fetch_all_news()
    relevant = [a for a in raw if is_relevant(a)]

    if not relevant:
        return {"generated_at": datetime.now(KST).isoformat(), "articles": [], "stats": {}}

    groups = cluster_articles(relevant)
    now = datetime.now(KST)

    results = []
    for idx_list in groups:
        members = [relevant[i] for i in idx_list]
        members.sort(key=lambda a: a["pub_dt"])
        rep = members[-1]  # 가장 최근 기사를 대표로
        cat_name, cat_weight = classify(rep)
        press_list = sorted(set(m["press"] for m in members))

        age_hours = max((now - rep["pub_dt"]).total_seconds() / 3600, 0)
        recency_score = max(0.0, 1 - age_hours / 48)  # 48시간 지나면 0에 수렴
        coverage_score = 1 + 0.8 * (len(press_list) - 1)
        importance = round((coverage_score + recency_score) * cat_weight, 3)

        results.append({
            "title": rep["title"],
            "desc": rep["desc"],
            "link": rep["link"],
            "press": rep["press"],
            "press_count": len(press_list),
            "press_list": press_list,
            "pub_date": rep["pub_dt"].isoformat(),
            "category": cat_name,
            "importance": importance,
        })

    results.sort(key=lambda r: r["importance"], reverse=True)

    stats = {
        "total_articles_raw": len(raw),
        "total_relevant": len(relevant),
        "total_clusters": len(results),
        "excluded": len(raw) - len(relevant),
    }

    youtube = fetch_youtube_trending() if YOUTUBE_API_KEY else []

    return {
        "generated_at": now.isoformat(),
        "articles": results,
        "youtube": youtube,
        "stats": stats,
    }


def fetch_youtube_trending():
    """대구경북 관련 최근 화제 유튜브 영상 (선택 기능)."""
    try:
        published_after = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        search_url = (
            "https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
            f"&q={urllib.parse.quote('대구 경북')}&order=viewCount&maxResults=10"
            f"&publishedAfter={published_after}&regionCode=KR&relevanceLanguage=ko"
            f"&key={YOUTUBE_API_KEY}"
        )
        with urllib.request.urlopen(search_url, timeout=15) as resp:
            search_data = json.loads(resp.read().decode("utf-8"))

        video_ids = [it["id"]["videoId"] for it in search_data.get("items", []) if it.get("id", {}).get("videoId")]
        if not video_ids:
            return []

        stats_url = (
            "https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics"
            f"&id={','.join(video_ids)}&key={YOUTUBE_API_KEY}"
        )
        with urllib.request.urlopen(stats_url, timeout=15) as resp:
            stats_data = json.loads(resp.read().decode("utf-8"))

        videos = []
        for it in stats_data.get("items", []):
            snippet = it.get("snippet", {})
            stats = it.get("statistics", {})
            videos.append({
                "title": snippet.get("title", ""),
                "channel": snippet.get("channelTitle", ""),
                "video_id": it.get("id"),
                "url": f"https://www.youtube.com/watch?v={it.get('id')}",
                "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                "view_count": int(stats.get("viewCount", 0)),
                "published_at": snippet.get("publishedAt", ""),
            })
        videos.sort(key=lambda v: v["view_count"], reverse=True)
        return videos
    except Exception as e:
        print(f"[WARN] 유튜브 수집 실패: {e}", file=sys.stderr)
        return []


def main():
    dataset = build_dataset()
    out_path = os.path.join(os.path.dirname(__file__), "docs", "data.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    print(f"저장 완료: {out_path} (기사 {len(dataset.get('articles', []))}건)")


if __name__ == "__main__":
    main()
