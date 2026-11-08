"""Fail-safe Telegram delivery for MEXC scanner.

A timeout may mean a message was delivered but its HTTP acknowledgement was lost.
We must never mark a delivery confirmed without a successful return. The
scanner's reports and refreshed market state should still be published.
"""
def guarded_notification(should_notify, heartbeat_due, setup_sender, heartbeat_sender):
    kind = "setup_change" if should_notify else ("heartbeat" if heartbeat_due else None)
    if kind is None:
        return False, None, None
    try:
        result = setup_sender() if kind == "setup_change" else heartbeat_sender()
        return bool(result), kind, None
    except Exception as exc:
        # Some HTTP exception messages include request URLs with bot tokens.
        # Only expose the exception class, never stringified exception text.
        return False, kind, type(exc).__name__
