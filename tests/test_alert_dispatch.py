from app.models import AlertChannel


def test_alert_fires_when_failures_reach_threshold(add_alert, run_check, queued):
    add_alert(threshold=3)
    run_check(500)
    run_check(500)
    assert queued.kinds() == []

    run_check(500)
    assert queued.kinds() == ["down"]


def test_repeated_failures_do_not_resend(add_alert, run_check, queued):
    add_alert(threshold=3)
    for _ in range(6):
        run_check(500)

    assert queued.kinds() == ["down"]


def test_recovery_sends_once_and_resets_streak(add_alert, run_check, queued):
    add_alert(threshold=3)
    for _ in range(3):
        run_check(500)
    run_check(200)
    run_check(200)
    assert queued.kinds() == ["down", "recovery"]

    # The streak restarted: two failures are not enough to alert again, the third is
    run_check(500)
    run_check(500)
    assert queued.kinds() == ["down", "recovery"]
    run_check(500)
    assert queued.kinds() == ["down", "recovery", "down"]


def test_blip_below_threshold_sends_nothing(add_alert, run_check, queued):
    add_alert(threshold=3)
    run_check(200)
    run_check(500)
    run_check(500)
    run_check(200)  # no recovery either: nothing was alerted
    run_check(500)

    assert queued.kinds() == []


def test_webhook_config_uses_webhook_task(add_alert, run_check, queued):
    add_alert(threshold=1, channel=AlertChannel.WEBHOOK)
    run_check(500)

    assert queued.kinds("webhook") == ["down"]
    assert queued.kinds("email") == []


def test_inactive_config_never_alerts(add_alert, run_check, queued):
    add_alert(threshold=1, is_active=False)
    run_check(500)

    assert queued.kinds() == []
