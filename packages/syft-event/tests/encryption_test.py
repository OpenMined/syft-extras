"""
Test SyftEvents with encryption functionality
"""

import json
from unittest.mock import patch

import pytest
from loguru import logger
from syft_core import Client
from syft_crypto import EncryptedPayload, decrypt_message, encrypt_message
from syft_event.server2 import SyftEvents
from syft_event.types import Request, Response
from syft_rpc.protocol import SyftRequest, SyftResponse
from syft_rpc.rpc import make_url


# ===== HELPER FUNCTIONS =====
def create_plain_request(
    sender_email: str, receiver_email: str, body_data: dict, endpoint: str = "endpoint"
) -> SyftRequest:
    """Helper to create a plain (unencrypted) SyftRequest"""
    url = make_url(receiver_email, "test_app", endpoint)
    request = SyftRequest(
        sender=sender_email,
        method="POST",
        url=url,
        headers={},
        body=json.dumps(body_data).encode(),
    )
    return request


def create_encrypted_request(
    sender_client: Client,
    receiver_email: str,
    body_data: dict,
    endpoint: str = "endpoint",
) -> SyftRequest:
    """Helper to create an encrypted SyftRequest"""
    encrypted_payload = encrypt_message(
        json.dumps(body_data), receiver_email, sender_client
    )

    url = make_url(receiver_email, "test_app", endpoint)
    request = SyftRequest(
        sender=sender_client.email,
        method="POST",
        url=url,
        headers={},
        body=encrypted_payload.model_dump_json().encode(),
    )
    return request


# ===== AUTO-DECRYPTION TESTS =====
def test_syft_events_on_request_decorator_auto_decrypt_settings(
    alice_events: SyftEvents,
):
    """Test on_request decorator properly stores auto_decrypt settings"""

    # Test default auto_decrypt=True
    @alice_events.on_request("/default")
    def default_handler(data: dict):
        return {"response": "ok"}

    # Test explicit auto_decrypt=False
    @alice_events.on_request("/raw", auto_decrypt=False)
    def raw_handler(request):
        return {"response": "raw"}

    # Verify settings are stored correctly
    default_endpoint = alice_events.app_rpc_dir / "default"
    raw_endpoint = alice_events.app_rpc_dir / "raw"

    default_info = alice_events._SyftEvents__rpc[default_endpoint]
    raw_info = alice_events._SyftEvents__rpc[raw_endpoint]

    # Check default behavior
    assert isinstance(default_info, dict)
    assert default_info["auto_decrypt"] is True
    assert default_info["handler"] == default_handler

    # Check explicit disabled
    assert isinstance(raw_info, dict)
    assert raw_info["auto_decrypt"] is False
    assert raw_info["handler"] == raw_handler


def test_process_encrypted_request_success(
    alice_events: SyftEvents, bob_client: Client
):
    """Test successful auto-decryption of encrypted request"""
    body_data = {"message": "secret data"}
    encrypted_req = create_encrypted_request(
        bob_client, alice_events.client.email, body_data
    )

    # Process the encrypted request
    processed_req = alice_events._process_encrypted_request(
        encrypted_req, auto_decrypt=True
    )

    # Should be decrypted
    assert processed_req.body == json.dumps(body_data).encode()
    assert processed_req.headers["X-Syft-Decrypted"] == "true"
    assert processed_req.headers["X-Syft-Original-Sender"] == bob_client.email


def test_process_encrypted_request_auto_decrypt_disabled(
    alice_events: SyftEvents, bob_client: Client
):
    """Test that auto-decryption is skipped when disabled"""
    body_data = {"message": "secret data"}
    encrypted_req = create_encrypted_request(
        bob_client, alice_events.client.email, body_data
    )
    original_body = encrypted_req.body

    # Process with auto_decrypt=False
    processed_req = alice_events._process_encrypted_request(
        encrypted_req, auto_decrypt=False
    )

    # Should remain encrypted
    assert processed_req.body == original_body
    assert "X-Syft-Decrypted" not in processed_req.headers


def test_process_plain_request_unchanged(alice_events: SyftEvents):
    """Test that plain requests are not modified"""
    body_data = {"message": "plain data"}
    plain_req = create_plain_request(
        "bob@example.com", alice_events.client.email, body_data
    )
    original_body = plain_req.body

    # Process the plain request
    processed_req = alice_events._process_encrypted_request(
        plain_req, auto_decrypt=True
    )

    # Should remain unchanged
    assert processed_req.body == original_body
    assert "X-Syft-Decrypted" not in processed_req.headers


# ===== ENCRYPTION REPLY TESTS =====


def test_on_request_encryption_options_defaults(alice_events: SyftEvents):
    """Test that on_request decorator has correct defaults"""

    @alice_events.on_request("/test")
    def test_handler(data: dict):
        return {"response": "ok"}

    # Check defaults
    endpoint_path = alice_events.app_rpc_dir / "test"
    handler_info = alice_events._SyftEvents__rpc[endpoint_path]

    assert isinstance(handler_info, dict)
    assert handler_info["auto_decrypt"] is True  # default
    assert handler_info["encrypt_reply"] is False  # default
    assert handler_info["handler"] == test_handler


def test_on_request_encryption_options_custom(alice_events: SyftEvents):
    """Test setting both encryption options"""

    @alice_events.on_request("/secure", auto_decrypt=False, encrypt_reply=True)
    def secure_handler(req: Request):
        return Response(body={"response": "encrypted"})

    # Check custom settings
    endpoint_path = alice_events.app_rpc_dir / "secure"
    handler_info = alice_events._SyftEvents__rpc[endpoint_path]

    assert isinstance(handler_info, dict)
    assert handler_info["auto_decrypt"] is False
    assert handler_info["encrypt_reply"] is True
    assert handler_info["handler"] == secure_handler


@patch("syft_rpc.rpc.reply_to")
def test_reply_encryption_settings(mock_reply_to, alice_events: SyftEvents):
    """Test that reply_to is called with correct encryption settings"""

    scenarios = [
        (False, "unencrypted_replies"),
        (True, "encrypted_replies"),
    ]

    for i, (encrypt_reply, endpoint_name) in enumerate(scenarios):
        # Register handler with specific encryption setting (unique name to avoid conflicts)
        endpoint = f"/{endpoint_name}_{i}"

        @alice_events.on_request(endpoint, encrypt_reply=encrypt_reply)
        def handler(data: dict):
            return {"result": endpoint_name}

        # Create and process request
        body_data = {"input": "test"}
        plain_req = create_plain_request(
            "bob@example.com", alice_events.client.email, body_data
        )

        alice_events.init()
        endpoint_dir = alice_events.app_rpc_dir / f"{endpoint_name}_{i}"
        request_dir = endpoint_dir / "bob@example.com"
        request_dir.mkdir(parents=True, exist_ok=True)
        request_path = request_dir / f"{plain_req.id}.request"
        plain_req.dump(request_path)

        handler_info = alice_events._SyftEvents__rpc[endpoint_dir]
        alice_events._SyftEvents__handle_rpc(request_path, handler_info["handler"])

        # Verify encryption setting was passed to reply_to
        mock_reply_to.assert_called()
        call_args = mock_reply_to.call_args
        if encrypt_reply:
            assert call_args.kwargs.get("encrypt") is True
        else:
            assert "encrypt" not in call_args.kwargs

        mock_reply_to.reset_mock()


# ===== ERROR HANDLING TESTS =====
def test_error_encryption(alice_events: SyftEvents, bob_client: Client):
    """Test error encryption"""

    @alice_events.on_request("/actual_error", auto_decrypt=True, encrypt_reply=True)
    def actual_error_handler(data: dict):
        raise RuntimeError(f"Failed to process: {data['input']}")

    alice_events.set_debug_mode(True)  # Get detailed errors

    # Send encrypted request that will cause error
    error_data = {"input": "bad data"}
    encrypted_req = create_encrypted_request(
        bob_client, alice_events.client.email, error_data, "actual_error"
    )

    alice_events.init()
    endpoint_dir = alice_events.app_rpc_dir / "actual_error"
    request_dir = endpoint_dir / bob_client.email
    request_dir.mkdir(parents=True, exist_ok=True)
    request_path = request_dir / f"{encrypted_req.id}.request"
    encrypted_req.dump(request_path)

    handler_info = alice_events._SyftEvents__rpc[endpoint_dir]
    alice_events._SyftEvents__handle_rpc(request_path, handler_info["handler"])

    # Check encrypted error response
    response_path = request_path.with_suffix(".response")
    assert response_path.exists()

    response = SyftResponse.load(response_path)
    encrypted_response = EncryptedPayload.model_validate_json(response.body.decode())

    # Bob can decrypt the error
    decrypted_error = decrypt_message(encrypted_response, client=bob_client)
    error_data = json.loads(decrypted_error)

    logger.debug(f"Got expected error response from Alice: {error_data}")

    assert "error_type" in error_data
    assert error_data["error_type"] == "RuntimeError"
    assert "Failed to process: bad data" in error_data["error_message"]


# ===== END-TO-END INTEGRATION TESTS =====
def test_complete_encryption_roundtrip(alice_events: SyftEvents, bob_client: Client):
    """Test complete encrypted request + encrypted reply flow"""

    @alice_events.on_request("/roundtrip", auto_decrypt=True, encrypt_reply=True)
    def roundtrip_handler(data: dict, request: Request):
        # Verify decryption metadata
        assert request.headers["X-Syft-Decrypted"] == "true"
        assert request.headers["X-Syft-Original-Sender"] == bob_client.email
        return {"response": f"processed {data['message']}", "secret": "classified"}

    # Create encrypted request from Bob
    body_data = {"message": "secret data"}
    encrypted_req = create_encrypted_request(
        sender_client=bob_client,
        receiver_email=alice_events.client.email,
        body_data=body_data,
        endpoint="roundtrip",
    )

    # Setup and process request manually (without observer to avoid race conditions)
    alice_events.init()
    endpoint_dir = alice_events.app_rpc_dir / "roundtrip"
    request_dir = endpoint_dir / bob_client.email
    request_dir.mkdir(parents=True, exist_ok=True)
    request_path = request_dir / f"{encrypted_req.id}.request"
    encrypted_req.dump(request_path)

    # Ensure the request file exists before processing
    assert request_path.exists(), f"Request file not created at {request_path}"

    # Process the request manually
    handler_info = alice_events._SyftEvents__rpc[endpoint_dir]
    alice_events._SyftEvents__handle_rpc(request_path, handler_info["handler"])

    # Verify encrypted response was created
    response_path = request_path.with_suffix(".response")
    assert response_path.exists(), f"Response file not found at {response_path}"
    response = SyftResponse.load(response_path)
    encrypted_response = EncryptedPayload.model_validate_json(response.body.decode())

    # Verify addressing
    assert encrypted_response.sender == alice_events.client.email
    assert encrypted_response.receiver == bob_client.email

    # Bob can decrypt
    decrypted_response = decrypt_message(encrypted_response, client=bob_client)
    response_data = json.loads(decrypted_response)

    assert response_data["response"] == f"processed {body_data['message']}"
    assert response_data["secret"] == "classified"


def test_federated_learning_simulation(
    alice_events: SyftEvents, bob_client: Client, charlie_client: Client
):
    """Test FL-style encrypted communication with 2 clients and model averaging"""

    received_models = []

    @alice_events.on_request("/fl_messages", auto_decrypt=True, encrypt_reply=True)
    def fl_handler(message_data: dict, request: Request):
        """Simulate FL aggregator that waits for 2 clients and averages their models"""
        logger.debug(f"Received message: {message_data}")
        if message_data["type"] == "model_update":
            received_models.append(
                {
                    "client": request.headers.get("X-Syft-Original-Sender"),
                    "weights": message_data["weights"],
                    "round": message_data["round"],
                }
            )

            # Wait for both clients before aggregating
            if len(received_models) >= 2:
                logger.debug("Received all FL models from clients, averaging...")
                # Calculate average weights across all received models
                num_models = len(received_models)
                weight_dim = len(received_models[0]["weights"])
                averaged_weights = []

                for i in range(weight_dim):
                    avg_weight = (
                        sum(model["weights"][i] for model in received_models)
                        / num_models
                    )
                    averaged_weights.append(avg_weight)

                return {
                    "type": "aggregated_model",
                    "global_weights": averaged_weights,
                    "next_round": message_data["round"] + 1,
                    "num_clients": num_models,
                }
            else:
                return {
                    "type": "waiting_for_more_clients",
                    "received": len(received_models),
                    "waiting_for": 2 - len(received_models),
                }
        return {"error": "unknown message type"}

    # Bob sends his model update
    bob_fl_message = {
        "type": "model_update",
        "weights": [0.1, 0.2, 0.3],
        "round": 1,
        "client_id": "bob_client",
    }

    # Charlie sends his model update
    charlie_fl_message = {
        "type": "model_update",
        "weights": [0.3, 0.4, 0.5],
        "round": 1,
        "client_id": "charlie_client",
    }

    # Process both FL messages
    alice_events.init()
    endpoint_dir = alice_events.app_rpc_dir / "fl_messages"
    endpoint_dir.mkdir(parents=True, exist_ok=True)

    # Process Bob's request
    bob_encrypted_req = create_encrypted_request(
        bob_client, alice_events.client.email, bob_fl_message, "fl_messages"
    )
    bob_request_dir = endpoint_dir / bob_client.email
    bob_request_dir.mkdir(parents=True, exist_ok=True)
    bob_request_path = bob_request_dir / f"{bob_encrypted_req.id}.request"
    bob_encrypted_req.dump(bob_request_path)

    handler_info = alice_events._SyftEvents__rpc[endpoint_dir]
    alice_events._SyftEvents__handle_rpc(bob_request_path, handler_info["handler"])

    # Process Charlie's request
    charlie_request_dir = endpoint_dir / charlie_client.email
    charlie_request_dir.mkdir(parents=True, exist_ok=True)
    charlie_encrypted_req = create_encrypted_request(
        charlie_client, alice_events.client.email, charlie_fl_message, "fl_messages"
    )
    charlie_request_path = charlie_request_dir / f"{charlie_encrypted_req.id}.request"
    charlie_encrypted_req.dump(charlie_request_path)

    alice_events._SyftEvents__handle_rpc(charlie_request_path, handler_info["handler"])

    # Verify both models were processed
    assert len(received_models) == 2
    assert received_models[0]["client"] == bob_client.email
    assert received_models[0]["weights"] == [0.1, 0.2, 0.3]
    assert received_models[1]["client"] == charlie_client.email
    assert received_models[1]["weights"] == [0.3, 0.4, 0.5]

    # Verify Charlie's encrypted aggregated response (the final one with averaging)
    charlie_response_path = charlie_request_path.with_suffix(".response")
    response = SyftResponse.load(charlie_response_path)
    encrypted_response = EncryptedPayload.model_validate_json(response.body.decode())

    decrypted_reply = decrypt_message(encrypted_response, client=charlie_client)
    aggregation_result = json.loads(decrypted_reply)

    assert aggregation_result["type"] == "aggregated_model"
    # Expected averages: [(0.1+0.3)/2, (0.2+0.4)/2, (0.3+0.5)/2] = [0.2, 0.3, 0.4]
    assert aggregation_result["global_weights"] == pytest.approx(
        [0.2, 0.3, 0.4], abs=1e-6
    )
    assert aggregation_result["next_round"] == 2
    assert aggregation_result["num_clients"] == 2

    # Verify Bob's response shows waiting status (since he was first)
    bob_response_path = bob_request_path.with_suffix(".response")
    bob_response = SyftResponse.load(bob_response_path)
    bob_encrypted_response = EncryptedPayload.model_validate_json(
        bob_response.body.decode()
    )

    bob_decrypted_reply = decrypt_message(bob_encrypted_response, client=bob_client)
    bob_result = json.loads(bob_decrypted_reply)

    logger.debug(f"Bob's response: {bob_result}")
    assert bob_result["type"] == "waiting_for_more_clients"
    assert bob_result["received"] == 1
    assert bob_result["waiting_for"] == 1

    # Verify Charlie's response shows aggregation is done
    charlie_response_path = charlie_request_path.with_suffix(".response")
    charlie_response = SyftResponse.load(charlie_response_path)
    encrypted_response = EncryptedPayload.model_validate_json(
        charlie_response.body.decode()
    )

    charlie_decrypted_reply = decrypt_message(encrypted_response, client=charlie_client)
    charlie_result = json.loads(charlie_decrypted_reply)

    logger.debug(f"Charlie's response: {charlie_result}")
    assert charlie_result["type"] == "aggregated_model"
    assert charlie_result["next_round"] == 2
    assert charlie_result["num_clients"] == 2
    assert charlie_result["global_weights"] == pytest.approx([0.2, 0.3, 0.4], abs=1e-6)
