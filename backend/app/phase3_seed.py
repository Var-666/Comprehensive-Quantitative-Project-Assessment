"""Explicit test-only finance fixture. Currency is caller supplied, absent in source sheet."""

import argparse
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import select

from .config import ROOT, settings
from .db import SessionLocal
from .evaluation_models import FinancialActual, FinancialPlan
from .models import Milestone, Project, now
from .services import audit


def load_finance(db, path, currency):
    if settings.app_env not in ("development", "test") or not settings.demo_mode:
        raise RuntimeError("模拟数据仅允许development/test + demo_mode")
    if (
        len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or not currency.isupper()
    ):
        raise ValueError("必须显式提供三位大写币种，例如CNY；原表未单独提供币种字段")
    workbook = load_workbook(path, read_only=True, data_only=True)
    count = 0
    try:
        for row in list(workbook["06_收付款计划实际"].values)[6:]:
            if not row or not row[0] or len(row) < 10:
                continue
            project = db.scalar(select(Project).where(Project.project_code == row[0]))
            if not project or project.data_source != "sample_excel":
                raise RuntimeError("请先导入原始模拟项目；拒绝写入真实项目")
            old = db.scalar(
                select(FinancialPlan).where(
                    FinancialPlan.project_id == project.id, FinancialPlan.record_code == row[1]
                )
            )
            if old:
                if not old.source_ref.startswith("模拟Excel06"):
                    raise RuntimeError("财务编号冲突，拒绝覆盖")
                continue
            node = db.scalar(
                select(Milestone).where(
                    Milestone.project_id == project.id, Milestone.milestone_code == row[3]
                )
            )
            plan = FinancialPlan(
                project_id=project.id,
                milestone_id=node.id if node else None,
                record_code=row[1],
                direction="receivable" if row[2] == "计划收款" else "payable",
                planned_date=row[5].date(),
                planned_amount=Decimal(str(row[6])),
                currency=currency,
                date_source_kind="unconfirmed",
                source_ref="模拟Excel06：" + str(row[4]) + "；币种由初始化命令显式指定",
                created_by="sample-fixture",
            )
            db.add(plan)
            audit(db, plan, "sample_financial_plan", "phase3-seed")
            if row[7] and row[8] is not None:
                obj = FinancialActual(
                    project_id=project.id,
                    financial_plan_id=plan.id,
                    record_code=row[1] + "-ACTUAL",
                    direction="receipt" if plan.direction == "receivable" else "payment",
                    actual_date=row[7].date(),
                    actual_amount=Decimal(str(row[8])),
                    currency=currency,
                    evidence_ref="模拟Excel06虚构历史核实事实；非真实财务凭证",
                    submitted_by="sample-fixture-submit",
                    verification_status="verified" if row[9] == "已核实" else "submitted",
                    verified_by="sample-fixture-review" if row[9] == "已核实" else None,
                    verified_at=now() if row[9] == "已核实" else None,
                )
                db.add(obj)
                audit(db, obj, "sample_financial_actual", "phase3-seed")
            count += 1
        db.flush()
        return count
    finally:
        workbook.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, default=ROOT / "模拟业务测试数据 V0.1.xlsx")
    parser.add_argument("--currency", required=True)
    args = parser.parse_args()
    with SessionLocal.begin() as db:
        count = load_finance(db, args.file, args.currency)
    print(
        f"新增模拟财务计划 {count} 条；仅实际发生列存在时写入实际记录；已有数据不覆盖，未授权任何财务权限。"
    )
