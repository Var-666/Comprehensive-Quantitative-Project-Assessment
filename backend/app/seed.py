"""Explicit, atomic developer fixture loader. Never a production import or migration."""

import argparse
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import select

from .config import ROOT, settings
from .db import SessionLocal
from .models import (
    ActualRecord,
    Department,
    NodeType,
    PlanVersion,
    Project,
    User,
    now,
)
from .schemas import MilestoneInput, ProjectInput
from .services import audit, create_milestone, create_project


def load_sample(db, path):
    if settings.app_env not in ("development", "test") or not settings.demo_mode:
        raise RuntimeError("模拟数据仅可在 development/test + demo_mode 使用")
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        projects = list(workbook["01_项目台账"].values)[6:]
        nodes = list(workbook["02_节点计划"].values)[6:]
        for i, name in enumerate(sorted({r[4] for r in projects} | {r[9] for r in nodes})):
            if not db.scalar(select(Department).where(Department.dept_name == name)):
                db.add(Department(dept_code=f"DEMO-D{i + 1}", dept_name=name))
        db.flush()
        departments = {d.dept_name: d.id for d in db.scalars(select(Department))}
        for i, name in enumerate(sorted({r[3] for r in projects} | {r[10] for r in nodes})):
            if not db.scalar(select(User).where(User.display_name == name)):
                db.add(User(employee_code=f"DEMO-U{i + 1}", display_name=name))
        for name in sorted({r[3] for r in nodes}):
            if not db.get(NodeType, name):
                db.add(NodeType(code=name, display_name=name))
        db.flush()
        users = {u.display_name: u.id for u in db.scalars(select(User))}
        inserted = 0
        for row in projects:
            code, name, kind, owner, dept, status, start, end, label = row[:9]
            existing = db.scalar(select(Project).where(Project.project_code == code))
            if existing:
                if existing.data_source != "sample_excel":
                    raise RuntimeError(f"{code} 已存在且不是样本项目；拒绝覆盖")
                continue
            project = create_project(
                db,
                ProjectInput(
                    project_code=code,
                    project_name=name,
                    project_type=kind,
                    owner_id=users[owner],
                    department_id=departments[dept],
                    project_status="active" if status == "进行中" else "draft",
                    attention_note="Excel原始状态：需关注" if status == "需关注" else None,
                    planned_start=start.date(),
                    planned_end=end.date(),
                ),
                "sample-seed",
                "sample_excel",
            )
            plan = db.scalar(select(PlanVersion).where(PlanVersion.project_id == project.id))
            # Only V2 facts exist in the workbook: do not invent a historical V1.
            plan.version_label = label
            for r in (r for r in nodes if r[0] == code):
                node = create_milestone(
                    db,
                    project.id,
                    MilestoneInput(
                        plan_version_id=plan.id,
                        milestone_code=r[1],
                        milestone_name=r[2],
                        node_type_code=r[3],
                        planned_date=r[5].date(),
                        department_id=departments[r[9]],
                        owner_id=users[r[10]],
                        source_ref=r[11],
                        date_kind="unconfirmed" if "未核实" in r[11] else "internal_plan",
                        change_reason="模拟Excel初始快照",
                    ),
                    "sample-seed",
                )
                if r[6] or r[7] == "待核实":
                    actual = ActualRecord(
                        milestone_id=node.id,
                        actual_date=r[6].date() if r[6] else None,
                        completion_flag=True if r[6] else None,
                        verification_status="verified" if r[7] == "已核实" else "submitted",
                        is_current=r[7] == "已核实",
                        evidence_ref="模拟Excel中的虚构核实记录，非真实企业证据",
                        verified_by="sample-fixture" if r[7] == "已核实" else None,
                        verified_at=now() if r[7] == "已核实" else None,
                    )
                    db.add(actual)
                    audit(db, actual, "sample_fact", "sample-seed")
            plan.status = "effective"
            plan.effective_at = now()
            plan.source_ref = "模拟Excel现有版本；非正式审批"
            project.current_plan_version_id = plan.id
            audit(db, plan, "sample_plan", "sample-seed")
            inserted += 1
        db.flush()
        return inserted
    finally:
        workbook.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, default=ROOT / "模拟业务测试数据 V0.1.xlsx")
    args = parser.parse_args()
    with SessionLocal.begin() as session:
        count = load_sample(session, args.file)
    print(f"模拟数据初始化完成：新增 {count} 个项目；已有样本不覆盖")
