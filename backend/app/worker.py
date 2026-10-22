"""Dedicated deterministic scanner; safe to run multiple workers due to project locks and keys."""

import argparse
import logging
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import Project, now
from .services import get
from .workflow import scan_project

logger = logging.getLogger("reminder-worker")


def run_once(factory=SessionLocal):
    as_of = now().astimezone(ZoneInfo(settings.business_timezone)).date()
    with factory() as db:
        project_ids = list(
            db.scalars(
                select(Project.id)
                .where(
                    Project.current_plan_version_id.is_not(None),
                    Project.project_status.not_in(["archived", "completed"]),
                )
                .order_by(Project.id)
            )
        )
    generated = 0
    for key in project_ids:
        # One transaction per project: a malformed project never commits a half-generated batch.
        with factory.begin() as db:
            db.info["actor_id"] = "reminder-worker"
            project = get(db, Project, key, True)
            rows = scan_project(db, project, as_of, str(uuid4()), True)
            generated += sum(r["eligible"] for r in rows)
    logger.info(
        "scan completed business_date=%s projects=%d generated=%d",
        as_of,
        len(project_ids),
        generated,
    )
    return generated


def main():
    parser = argparse.ArgumentParser(description="按已批准规则自动发送站内提醒并生成待办")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    if args.interval < 10:
        parser.error("扫描间隔至少10秒")
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            run_once()
        except Exception:
            logger.exception("scan failed; project transaction rolled back")
            if args.once:
                raise
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
