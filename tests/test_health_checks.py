import httpx
import socket
import httpcore

from app.dispatcher import classify_connect_error


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

def connect_error_caused_by(os_error: OSError) -> httpx.ConnectError:
    # Same chain httpx produces: httpx.ConnectError <- httpcore.ConnectError <- OS error
    inner = httpcore.ConnectError(str(os_error))
    inner.__cause__ = os_error
    outer = httpx.ConnectError(str(os_error))
    outer.__cause__ = inner
    return outer


def test_refused_connection_is_classified():
    error = connect_error_caused_by(ConnectionRefusedError(111, "Connection refused"))
    assert classify_connect_error(error) == "connection_refused"


def test_unresolvable_host_is_classified():
    error = connect_error_caused_by(socket.gaierror(-2, "Name or service not known"))
    assert classify_connect_error(error) == "dns_failure"


def test_other_connect_errors_are_not_mislabelled():
    error = connect_error_caused_by(OSError(113, "No route to host"))
    assert classify_connect_error(error) == "connect_error"