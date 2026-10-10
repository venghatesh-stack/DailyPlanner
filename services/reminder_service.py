import logging
from datetime import datetime, timezone
from supabase_client import get, update

logger = logging.getLogger("daily_plan")


def check_reminders():
    now_iso = datetime.now(timezone.utc).isoformat()

    # One filter. The dict used to name "reminder_at" twice, so the second
    # ("not.is.null") silently replaced the first and EVERY set reminder —
    # future ones included — was cleared. lte already excludes NULLs.
    rows = get("inbox_links", params={
        "reminder_at": f"lte.{now_iso}",
        "select": "id,url,title",
    }) or []

    for row in rows:
        logger.info("REMINDER due: %s — %s", row.get("id"), row.get("url"))
        try:
            update(
                "inbox_links",
                params={"id": f"eq.{row['id']}"},
                json={"reminder_at": None},
            )
        except Exception as e:
            logger.error("Failed to clear reminder for %s: %s", row.get("id"), e)

    return len(rows)
