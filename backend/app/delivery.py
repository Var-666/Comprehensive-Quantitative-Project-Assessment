"""Replaceable delivery boundary. Only transactional in-app delivery is enabled."""

from .models import now
from .services import audit, fail, record
from .workflow_models import DeliveryAttempt, InboxMessage


def deliver(db, notice, channel, request_id):
    if channel != "in_app":
        fail(409, "CHANNEL_DISABLED", "外部通知渠道尚未授权，仅允许显式站内发布")
    before = record(notice)
    message = InboxMessage(
        notification_id=notice.id,
        recipient_user_id=notice.recipient_user_id,
        title=notice.title,
        body=notice.body,
    )
    db.add(message)
    db.flush()
    db.add(
        DeliveryAttempt(
            notification_id=notice.id,
            channel=channel,
            destination_ref=notice.recipient_user_id,
            attempt_state="delivered",
            finished_at=now(),
            provider_message_id=message.id,
        )
    )
    notice.status = "sent"
    audit(db, notice, "dispatch_in_app", request_id, before)
