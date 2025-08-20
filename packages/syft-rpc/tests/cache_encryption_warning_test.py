import warnings

from syft_core import Client
from syft_rpc.rpc import make_url, send


def test_cache_default_with_encryption(alice_client: Client, bob_client: Client):
    """Test that cache defaults to False when encrypt=True."""
    url = make_url(bob_client.email, "test_app", "endpoint")
    body = {"message": "test"}

    # When encrypt=True and cache=None, cache should default to False
    future = send(url=url, body=body, encrypt=True, client=alice_client)

    # Should create a request but without cache behavior (different IDs each time)
    future2 = send(url=url, body=body, encrypt=True, client=alice_client)
    assert future.id != future2.id  # No caching, different IDs


def test_cache_default_without_encryption(alice_client: Client):
    """Test that cache defaults to True when encrypt=False."""
    url = make_url("recipient@domain.com", "test_app", "endpoint")
    body = {"message": "test"}

    # When encrypt=False and cache=None, cache should default to True
    future1 = send(url=url, body=body, encrypt=False, client=alice_client)
    future2 = send(url=url, body=body, encrypt=False, client=alice_client)

    # Should use caching (same ID for identical requests)
    assert future1.id == future2.id


def test_warning_when_cache_true_and_encrypt_true(
    alice_client: Client, bob_client: Client
):
    """Test that warning is issued when cache=True and encrypt=True."""
    url = make_url(bob_client.email, "test_app", "endpoint")
    body = {"message": "test"}

    # Should issue warning when explicitly setting cache=True with encrypt=True
    with warnings.catch_warnings(record=True) as warns:
        warnings.simplefilter("always")

        send(url=url, body=body, encrypt=True, cache=True, client=alice_client)

        # Should have issued exactly one warning
        assert len(warns) == 1
        assert issubclass(warns[0].category, UserWarning)
        assert "ineffective" in str(warns[0].message).lower()
        assert "ephemeral keys" in str(warns[0].message).lower()


def test_no_warning_when_cache_false_and_encrypt_true(
    alice_client: Client, bob_client: Client
):
    """Test that no warning is issued when cache=False and encrypt=True."""
    url = make_url(bob_client.email, "test_app", "endpoint")
    body = {"message": "test"}

    # Should NOT issue warning when cache=False with encrypt=True
    with warnings.catch_warnings(record=True) as warns:
        warnings.simplefilter("always")

        send(url=url, body=body, encrypt=True, cache=False, client=alice_client)

        # Should not have issued any warnings
        assert len(warns) == 0


def test_explicit_cache_true_overrides_default(alice_client: Client):
    """Test that explicitly setting cache=True works even without encryption."""
    url = make_url("recipient@domain.com", "test_app", "endpoint")
    body = {"message": "test"}

    # Explicitly set cache=True (should work for non-encrypted)
    future1 = send(url=url, body=body, encrypt=False, cache=True, client=alice_client)
    future2 = send(url=url, body=body, encrypt=False, cache=True, client=alice_client)

    # Should use caching
    assert future1.id == future2.id


def test_explicit_cache_false_overrides_default(alice_client: Client):
    """Test that explicitly setting cache=False disables caching even without encryption."""
    url = make_url("recipient@domain.com", "test_app", "endpoint")
    body = {"message": "test"}

    # Explicitly set cache=False (should disable caching even for non-encrypted)
    future1 = send(url=url, body=body, encrypt=False, cache=False, client=alice_client)
    future2 = send(url=url, body=body, encrypt=False, cache=False, client=alice_client)

    # Should NOT use caching (different IDs)
    assert future1.id != future2.id
