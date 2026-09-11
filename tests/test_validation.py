import pytest
from pydantic import ValidationError

from app.models import EndpointCreate


@pytest.mark.parametrize("url", ["hello", "example.com", "http://", "ftp://example.com", "https://exa mple.com"])
def test_invalid_urls_are_rejected(url):
    with pytest.raises(ValidationError):
        EndpointCreate(url=url)


@pytest.mark.parametrize("url", ["https://example.com", "http://host.docker.internal:9000/health"])
def test_valid_urls_are_kept_as_given(url):
    assert EndpointCreate(url=url).url == url


def test_interval_below_minimum_is_rejected():
    with pytest.raises(ValidationError):
        EndpointCreate(url="https://example.com", interval_seconds=5)