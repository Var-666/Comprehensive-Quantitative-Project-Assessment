"""Load source Excel action drafts only. No synthetic approval, recipients or enterprise holidays."""

import argparse
from collections import defaultdict

from openpyxl import load_workbook
from sqlalchemy import select

from .config import ROOT, settings
from .db import SessionLocal
from .models import Credential, Department, NodeType
from .services import audit
from .workflow_models import ActionItem, ActionTemplate


def load_action_drafts(db, path, actor_id):
    if settings.app_env not in ("development", "test") or not settings.demo_mode:
        raise RuntimeError("模拟动作仅允许在开发/测试环境加载")
    workbook = load_workbook(path, read_only=True, data_only=True)
    groups = defaultdict(list)
    try:
        for row in list(workbook["03_标准动作"].values)[6:]:
            if row and row[0]:
                groups[(row[0].rsplit("-", 1)[0], row[1])].append(row)
    finally:
        workbook.close()
    count = 0
    for (code, node_type), rows in groups.items():
        if db.scalar(
            select(ActionTemplate.id).where(
                ActionTemplate.template_code == code, ActionTemplate.version_label == "SAMPLE-V1"
            )
        ):
            continue
        if not db.get(NodeType, node_type):
            raise RuntimeError("请先加载第一阶段模拟项目及目录")
        obj = ActionTemplate(
            template_code=code,
            version_label="SAMPLE-V1",
            title=node_type + "准备（模拟草案）",
            node_type_code=node_type,
            applicability_json={},
            source_ref=f"模拟业务测试数据 V0.1.xlsx / 03_标准动作；适用条件、接收人、核实依据待业务确认；来源规则{rows[0][10]}，提前{rows[0][6]}{rows[0][7]}",
            created_by=actor_id,
            editor_ids=[actor_id],
        )
        db.add(obj)
        db.flush()
        for row in rows:
            department = db.scalar(select(Department).where(Department.dept_name == row[5]))
            db.add(
                ActionItem(
                    template_version_id=obj.id,
                    item_code=row[0],
                    title=row[3],
                    materials_required_json=[row[4]] if row[4] else [],
                    default_department_id=department.id if department else None,
                    completion_criteria="待业务确认；来源列示材料：" + (row[4] or "未提供"),
                    sort_order=row[2],
                )
            )
        audit(db, obj, "load_sample_action_draft", "phase2-sample-seed")
        count += 1
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True, help="现有系统管理员账号")
    args = parser.parse_args()
    with SessionLocal.begin() as db:
        account = db.scalar(
            select(Credential).where(
                Credential.username == args.username,
                Credential.enabled.is_(True),
                Credential.is_system_admin.is_(True),
            )
        )
        if not account:
            raise RuntimeError("需要已配置的系统管理员账号")
        db.info["actor_id"] = account.user_id
        count = load_action_drafts(db, ROOT / "模拟业务测试数据 V0.1.xlsx", account.user_id)
    print(f"已加载{count}个模拟模板草稿；未批准、未绑定、未生成通知或任务")
