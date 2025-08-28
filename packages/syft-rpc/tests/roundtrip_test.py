import json
from pathlib import Path

from syft_core import Client
from syft_crypto import EncryptedPayload, bootstrap_user, decrypt_message
from syft_rpc.protocol import SyftFuture, SyftRequest, SyftResponse, SyftStatus
from syft_rpc.rpc import broadcast, make_url, reply_to, send

from tests.conftest import create_temp_client


def test_unencrypted_roundtrip(alice_client: Client, bob_client: Client):
    """Test complete unencrypted request/response roundtrip."""
    url = make_url(bob_client.email, "test_app", "echo")
    request_body = {"message": "hello from alice"}

    # Alice sends request to Bob
    future = send(url=url, body=request_body, encrypt=False, client=alice_client)

    # Verify request was created correctly
    assert isinstance(future, SyftFuture)
    request_file = future.path / f"{future.id}.request"
    assert request_file.exists()

    # Bob receives and loads the request
    received_request = SyftRequest.load(request_file)
    assert received_request.sender == alice_client.email
    assert received_request.body == b'{"message":"hello from alice"}'

    # Bob processes request and creates response
    response_body = {"reply": "hello back from bob"}
    response = reply_to(
        request=received_request, body=response_body, encrypt=False, client=bob_client
    )

    # Verify response was created correctly
    assert isinstance(response, SyftResponse)
    assert response.sender == bob_client.email
    assert response.id == received_request.id  # Same ID as request
    assert (
        response.body == b'{"reply":"hello back from bob"}'
    )  # unencrypted response body

    # Verify response file exists
    response_file = (
        response.url.to_local_path(bob_client.workspace.datasites)
        / f"{response.id}.response"
    )
    assert response_file.exists()

    # Alice loads the response
    loaded_response = SyftResponse.load(response_file)
    assert loaded_response.sender == bob_client.email
    assert loaded_response.body == b'{"reply":"hello back from bob"}'
    assert loaded_response.status_code == SyftStatus.SYFT_200_OK


def test_encrypted_roundtrip(alice_client: Client, bob_client: Client):
    """Test complete encrypted request/response roundtrip."""
    url = make_url(bob_client.email, "test_app", "secure_echo")
    request_body = {"secret_message": "confidential data from alice"}

    # Alice sends encrypted request to Bob
    future = send(url=url, body=request_body, encrypt=True, client=alice_client)

    # Verify encrypted request was created
    assert isinstance(future, SyftFuture)
    request_file = future.path / f"{future.id}.request"
    assert request_file.exists()

    # Bob receives and loads the encrypted request
    received_request = SyftRequest.load(request_file)
    assert received_request.sender == alice_client.email
    assert (
        received_request.body != b'{"secret_message":"confidential data from alice"}'
    )  # Should be encrypted

    # Bob decrypts the request body
    encrypted_payload = EncryptedPayload.model_validate_json(
        received_request.body.decode()
    )
    decrypted_request_body = decrypt_message(encrypted_payload, client=bob_client)
    assert decrypted_request_body == '{"secret_message":"confidential data from alice"}'

    # Bob processes request and creates encrypted response
    response_body = {"secret_reply": "confidential response from bob"}
    response = reply_to(
        request=received_request, body=response_body, encrypt=True, client=bob_client
    )

    # Verify encrypted response was created correctly
    assert isinstance(response, SyftResponse)
    assert response.sender == bob_client.email
    assert response.id == received_request.id
    assert (
        response.body != b'{"secret_reply":"confidential response from bob"}'
    )  # Should be encrypted

    # Verify response encryption details
    encrypted_response_payload = EncryptedPayload.model_validate_json(
        response.body.decode()
    )
    assert encrypted_response_payload.sender == bob_client.email
    assert encrypted_response_payload.receiver == alice_client.email

    # Alice receives and decrypts the response
    response_file = (
        response.url.to_local_path(bob_client.workspace.datasites)
        / f"{response.id}.response"
    )
    assert response_file.exists()

    loaded_response = SyftResponse.load(response_file)
    encrypted_response_payload = EncryptedPayload.model_validate_json(
        loaded_response.body.decode()
    )
    decrypted_response_body = decrypt_message(
        encrypted_response_payload, client=alice_client
    )
    assert (
        decrypted_response_body == '{"secret_reply":"confidential response from bob"}'
    )


def test_mixed_encryption_roundtrip(alice_client: Client, bob_client: Client):
    """Test roundtrip where request is unencrypted but response is encrypted."""
    url = make_url(bob_client.email, "test_app", "mixed_security")
    request_body = {"public_query": "get user profile"}

    # Alice sends unencrypted request
    future = send(url=url, body=request_body, encrypt=False, client=alice_client)

    # Bob receives unencrypted request
    request_file = future.path / f"{future.id}.request"
    received_request = SyftRequest.load(request_file)
    assert received_request.body == b'{"public_query":"get user profile"}'

    # Bob creates encrypted response (sensitive user data)
    response_body = {
        "user_profile": {
            "name": "Alice Johnson",
            "email": "alice@example.com",
            "private_key": "secret123",
            "balance": 1000.50,
        }
    }
    response = reply_to(
        request=received_request,
        body=response_body,
        encrypt=True,  # Encrypt sensitive response
        client=bob_client,
    )

    # Verify response is encrypted
    assert response.body != json.dumps(response_body).encode()

    # Alice decrypts the sensitive response
    response_file = (
        response.url.to_local_path(bob_client.workspace.datasites)
        / f"{response.id}.response"
    )
    loaded_response = SyftResponse.load(response_file)
    encrypted_payload = EncryptedPayload.model_validate_json(
        loaded_response.body.decode()
    )
    decrypted_response = decrypt_message(encrypted_payload, client=alice_client)

    assert json.loads(decrypted_response) == response_body


def test_nonencrypted_error_response_roundtrip(
    alice_client: Client, bob_client: Client
):
    """Test roundtrip with error responses."""
    url = make_url(bob_client.email, "test_app", "failing_endpoint")
    request_body = {"invalid_request": "this will fail"}

    # Alice sends request
    future = send(url=url, body=request_body, encrypt=False, client=alice_client)

    # Bob receives request and creates error response
    request_file = future.path / f"{future.id}.request"
    received_request = SyftRequest.load(request_file)

    error_response_body = {
        "error": "Invalid request format",
        "code": "INVALID_FORMAT",
        "details": "The 'invalid_request' field is not supported",
    }

    response = reply_to(
        request=received_request,
        body=error_response_body,
        status_code=SyftStatus.SYFT_400_BAD_REQUEST,
        encrypt=False,
        client=bob_client,
    )

    # Verify error response
    assert response.status_code == SyftStatus.SYFT_400_BAD_REQUEST
    # Parse and compare as dicts since JSON formatting may differ
    assert json.loads(response.body.decode()) == error_response_body

    # Alice receives error response
    response_file = (
        response.url.to_local_path(bob_client.workspace.datasites)
        / f"{response.id}.response"
    )
    loaded_response = SyftResponse.load(response_file)
    assert loaded_response.status_code == SyftStatus.SYFT_400_BAD_REQUEST
    assert json.loads(loaded_response.body.decode()) == error_response_body


def test_encrypted_error_response_roundtrip(alice_client: Client, bob_client: Client):
    """Test roundtrip with encrypted error responses."""
    url = make_url(bob_client.email, "test_app", "secure_failing_endpoint")
    request_body = {"sensitive_invalid_request": "confidential but wrong"}

    # Alice sends encrypted request
    future = send(url=url, body=request_body, encrypt=True, client=alice_client)

    # Bob receives and processes encrypted request
    request_file = future.path / f"{future.id}.request"
    received_request = SyftRequest.load(request_file)

    # Bob creates encrypted error response
    error_response_body = {
        "error": "Authentication failed",
        "code": "AUTH_FAILED",
        "sensitive_details": "User credentials are invalid or expired",
    }

    response = reply_to(
        request=received_request,
        body=error_response_body,
        status_code=SyftStatus.SYFT_403_FORBIDDEN,
        encrypt=True,  # Encrypt sensitive error details
        client=bob_client,
    )

    # Verify encrypted error response
    assert response.status_code == SyftStatus.SYFT_403_FORBIDDEN
    assert response.body != json.dumps(error_response_body).encode()

    # Alice decrypts error response
    response_file = (
        response.url.to_local_path(bob_client.workspace.datasites)
        / f"{response.id}.response"
    )
    loaded_response = SyftResponse.load(response_file)

    encrypted_payload = EncryptedPayload.model_validate_json(
        loaded_response.body.decode()
    )
    decrypted_error = decrypt_message(encrypted_payload, client=alice_client)
    assert json.loads(decrypted_error) == error_response_body


def test_multiple_roundtrips_same_clients(alice_client: Client, bob_client: Client):
    """Test multiple sequential encrypted roundtrips between same clients."""
    base_url = make_url(bob_client.email, "test_app", "counter")

    for i in range(3):
        # Alice sends request
        request_body = {"increment": i}
        future = send(
            url=base_url, body=request_body, encrypt=True, client=alice_client
        )

        # Bob receives and responds
        request_file = future.path / f"{future.id}.request"
        received_request = SyftRequest.load(request_file)

        # Decrypt Alice's request
        encrypted_payload = EncryptedPayload.model_validate_json(
            received_request.body.decode()
        )
        decrypted_request = json.loads(
            decrypt_message(encrypted_payload, client=bob_client)
        )

        # Bob creates response
        response_body = {"counter_value": decrypted_request["increment"] * 2}
        response = reply_to(
            request=received_request,
            body=response_body,
            encrypt=True,
            client=bob_client,
        )

        # Verify Alice can decrypt Bob's response
        response_file = (
            response.url.to_local_path(bob_client.workspace.datasites)
            / f"{response.id}.response"
        )
        loaded_response = SyftResponse.load(response_file)
        encrypted_response = EncryptedPayload.model_validate_json(
            loaded_response.body.decode()
        )
        decrypted_response = json.loads(
            decrypt_message(encrypted_response, client=alice_client)
        )

        assert decrypted_response["counter_value"] == i * 2


def test_broadcast_roundtrip(
    alice_client: Client, bob_client: Client, temp_workspace: Path
):
    """Test roundtrip with broadcast to multiple recipients."""
    charlie_client = create_temp_client("charlie@example.com", temp_workspace)
    bootstrap_user(charlie_client)

    # Alice broadcasts to Bob and Charlie
    urls = [
        make_url(bob_client.email, "test_app", "broadcast_endpoint"),
        make_url(charlie_client.email, "test_app", "broadcast_endpoint"),
    ]

    broadcast_body = {"announcement": "Hello everyone!"}
    bulk_future = broadcast(
        urls=urls, body=broadcast_body, encrypt=True, client=alice_client
    )

    # Verify all futures were created
    assert len(bulk_future.futures) == 2

    # Both Bob and Charlie respond
    responses = []
    for i, future in enumerate(bulk_future.futures):
        # Load request
        request_file = future.path / f"{future.id}.request"
        received_request = SyftRequest.load(request_file)

        # Choose responder
        responder_client = bob_client if i == 0 else charlie_client
        responder_name = "Bob" if i == 0 else "Charlie"

        # Create response
        response_body = {"reply": f"Hello back from {responder_name}!"}
        response = reply_to(
            request=received_request,
            body=response_body,
            encrypt=True,
            client=responder_client,
        )
        responses.append(response)

    # Verify Alice can decrypt all responses
    for i, response in enumerate(responses):
        response_file = (
            response.url.to_local_path(
                (bob_client if i == 0 else charlie_client).workspace.datasites
            )
            / f"{response.id}.response"
        )
        loaded_response = SyftResponse.load(response_file)

        encrypted_payload = EncryptedPayload.model_validate_json(
            loaded_response.body.decode()
        )
        decrypted_response = json.loads(
            decrypt_message(encrypted_payload, client=alice_client)
        )

        expected_name = "Bob" if i == 0 else "Charlie"
        assert decrypted_response["reply"] == f"Hello back from {expected_name}!"
