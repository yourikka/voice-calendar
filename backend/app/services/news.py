from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.models import (
    HotTopicPanelResponse,
    HotTopicRefreshRequest,
    HotTopicRefreshResponse,
    NewsItemRead,
    NewsTodayResponse,
)


CACHE_TTL = timedelta(minutes=10)


class NewsService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_today_news(
        self,
        timezone_name: str,
        category: str | None = None,
        region: str = "CN",
        limit: int = 5,
        fresh: bool = False,
    ) -> NewsTodayResponse:
        now = datetime.now(ZoneInfo(timezone_name))
        if fresh or self._cache_expired(now, region):
            self.refresh_hot_topics(
                HotTopicRefreshRequest(
                    timezone=timezone_name,
                    region=region,
                    categories=[category] if category else ["general", "technology", "finance"],
                )
            )
        items = self._list_items(region=region, category=category, limit=limit)
        fetched_at = max((item.fetched_at for item in items), default=now)
        return NewsTodayResponse(
            date=now.date().isoformat(),
            timezone=timezone_name,
            fresh=fresh,
            fetched_at=fetched_at,
            items=items,
            spoken_summary=_spoken_news_summary(items, category),
        )

    def get_hot_topic_panel(
        self,
        date: str,
        timezone_name: str,
        limit: int = 5,
        region: str = "CN",
    ) -> HotTopicPanelResponse:
        now = datetime.now(ZoneInfo(timezone_name))
        stale = self._cache_expired(now, region)
        if stale and not self._list_items(region=region, category=None, limit=1):
            self.refresh_hot_topics(HotTopicRefreshRequest(timezone=timezone_name, region=region))
            stale = False
        items = self._list_items(region=region, category=None, limit=limit)
        refreshed_at = max((item.fetched_at for item in items), default=now)
        return HotTopicPanelResponse(
            date=date,
            timezone=timezone_name,
            refreshed_at=refreshed_at,
            cache_expires_at=refreshed_at + CACHE_TTL,
            stale=stale,
            items=items,
        )

    def refresh_hot_topics(self, request: HotTopicRefreshRequest) -> HotTopicRefreshResponse:
        now = datetime.now(ZoneInfo(request.timezone))
        items = _fixture_topics(now, request.region, request.categories)
        with self.conn:
            for item in items:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO news_items (
                        id, title, summary, category, region, source_name, source_url,
                        published_at, fetched_at, language, hot_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.title,
                        item.summary,
                        item.category,
                        item.region,
                        item.source_name,
                        item.source_url,
                        item.published_at.isoformat(),
                        now.isoformat(),
                        item.language,
                        item.hot_score,
                    ),
                )
        return HotTopicRefreshResponse(status="completed", refreshed_at=now, item_count=len(items))

    def _cache_expired(self, now: datetime, region: str) -> bool:
        row = self.conn.execute(
            "SELECT MAX(fetched_at) AS fetched_at FROM news_items WHERE region = ?",
            (region,),
        ).fetchone()
        if row is None or row["fetched_at"] is None:
            return True
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        return now - fetched_at > CACHE_TTL

    def _list_items(
        self,
        region: str,
        category: str | None,
        limit: int,
    ) -> list[NewsItemRead]:
        params: list[object] = [region]
        category_clause = ""
        if category:
            category_clause = "AND category = ?"
            params.append(category)
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT * FROM news_items
            WHERE region = ?
              {category_clause}
            ORDER BY hot_score DESC, published_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [_row_to_news(row) for row in rows]


def _row_to_news(row: sqlite3.Row) -> NewsItemRead:
    return NewsItemRead(
        id=row["id"],
        title=row["title"],
        summary=row["summary"],
        category=row["category"],
        region=row["region"],
        source_name=row["source_name"],
        source_url=row["source_url"],
        published_at=datetime.fromisoformat(row["published_at"]),
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        language=row["language"],
        hot_score=row["hot_score"],
    )


def _fixture_topics(now: datetime, region: str, categories: list[str]) -> list[NewsItemRead]:
    catalog = [
        ("general", "本地交通发布晚高峰提示", "主要道路晚高峰压力较高，建议提前规划出行。", "示例本地", 0.82),
        ("technology", "AI 多模态应用持续升温", "多家产品更新多模态能力，行业关注度持续提升。", "示例科技", 0.91),
        ("finance", "国内财经政策发布新动态", "市场关注新的政策执行方向和流动性变化。", "示例财经", 0.88),
        ("general", "公共服务平台更新办事入口", "多项线上办事服务入口完成整合更新。", "示例新闻", 0.76),
        ("technology", "智能体工具生态继续扩展", "多个开发平台增强工具调用和工作流编排能力。", "示例科技", 0.84),
    ]
    selected = [item for item in catalog if item[0] in categories or "general" in categories]
    return [
        NewsItemRead(
            id=f"news_{uuid4().hex}",
            title=title,
            summary=summary,
            category=category,
            region=region,
            source_name=source_name,
            source_url=f"https://example.com/news/{index}",
            published_at=now - timedelta(minutes=index * 11),
            fetched_at=now,
            language="zh-CN",
            hot_score=score,
        )
        for index, (category, title, summary, source_name, score) in enumerate(selected, start=1)
    ]


def _spoken_news_summary(items: list[NewsItemRead], category: str | None) -> str:
    if not items:
        return "暂时没有获取到当日热点。"
    scope = f"{category} 相关" if category else ""
    titles = "。".join(f"第{index}，{item.title}" for index, item in enumerate(items[:3], start=1))
    return f"今天{scope}有 {len(items)} 条热点。我先说前三条：{titles}。"

