import httpx


def test_success_records_status_and_response_time(run_check, results):
    run_check(200)

    [result] = results()
    assert result.status_code == 200
    assert result.error is None
    assert result.response_time_ms is not None


def test_http_error_status_is_recorded(run_check, results):
    run_check(503)

    [result] = results()
    assert result.status_code == 503
    assert result.error is None


def test_timeout_records_no_status_or_time(run_check, results):
    run_check(httpx.ConnectTimeout("timed out"))

    [result] = results()
    assert result.status_code is None
    assert result.error == "timeout"
    assert result.response_time_ms is None


def test_redirect_counts_as_up(add_alert, run_check, queued):
    add_alert(threshold=1)
    run_check(301)

    assert queued.kinds() == []


def test_timeout_counts_as_down(add_alert, run_check, queued):
    add_alert(threshold=1)
    run_check(httpx.ReadTimeout("timed out"))

    assert queued.kinds() == ["down"]
