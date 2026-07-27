"""今日简报路由（L3 主动化产品）。

接口：
- GET /api/briefing              全局今日简报（扫所有项目）
- GET /api/briefing/{project_id} 单项目今日简报

启动时前端调 /api/briefing 拉取今日简报，作为首屏（不是 dashboard）。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter

from app.core.briefing import generate_daily_briefing

logger = logging.getLogger("pbc.routes_briefing")

router = APIRouter(prefix="/api/briefing", tags=["briefing"])

_DEFAULT_PROJECT = "demo"


@router.get("")
async def briefing_global() -> dict:
    """全局今日简报（扫所有项目，返回 N 条最高优风险事件）。"""
    try:
        return generate_daily_briefing(project_id=None)
    except Exception as e:
        logger.exception("briefing global failed")
        return {
            "generated_at": "",
            "project_id": None,
            "events": [],
            "summary": {
                "high_count": 0,
                "medium_count": 0,
                "total_events": 0,
                "scanned_projects": 0,
                "error": str(e),
            },
        }


@router.get("/{project_id}")
async def briefing_by_project(project_id: str, since: Optional[float] = None) -> dict:
    """单项目今日简报。

    参数:
        since: Unix 时间戳，只返回此时间之后的增量事件。
               不传时返回全量存量（兼容旧调用）。
    """
    try:
        return generate_daily_briefing(project_id=project_id, since=since)
    except Exception as e:
        logger.exception("briefing by project %s failed", project_id)
        return {
            "generated_at": "",
            "project_id": project_id,
            "events": [],
            "delta_count": 0,
            "delta_groups": [],
            "has_delta": False,
            "stock_total": 0,
            "stock_high": 0,
            "summary": {
                "high_count": 0,
                "medium_count": 0,
                "total_events": 0,
                "scanned_projects": 0,
                "error": str(e),
            },
        }
