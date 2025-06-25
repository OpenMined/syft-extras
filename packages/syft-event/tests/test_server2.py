import pytest
import warnings
from unittest.mock import MagicMock, AsyncMock, patch, call
from pathlib import Path
from threading import Event
from syft_event.server2 import SyftEvents
from syft_event.router import EventRouter
from syft_event.types import Response
from syft_rpc.protocol import SyftStatus
import types

@pytest.fixture
def mock_client(tmp_path):
    # Mock the syft_core.Client and its methods
    mock = MagicMock()
    mock.email = "test@example.com"
    mock.app_data.return_value = tmp_path / "app_data"
    mock.datasites = tmp_path
    return mock

@pytest.fixture
def syft_events(mock_client):
    # Patch Client.load to return our mock
    with patch("syft_event.server2.Client.load", return_value=mock_client):
        yield SyftEvents("test_app", client=mock_client)

@pytest.fixture
def dummy_handler():
    def handler(request=None):
        return Response(body={"ok": True})
    return handler

@pytest.mark.parametrize("publish_schema", [True, False])
def test_init_creates_dirs_and_schema(mock_client, publish_schema, tmp_path):
    se = SyftEvents("test_app", publish_schema=publish_schema, client=mock_client)
    with patch.object(se, "publish_schema") as mock_schema:
        se.init()
        assert se.app_dir.exists()
        assert se.app_rpc_dir.exists()
        perms_file = se.app_rpc_dir / "syft.pub.yaml"
        assert perms_file.exists()
        if publish_schema:
            mock_schema.assert_called_once()
        else:
            mock_schema.assert_not_called()

@patch("syft_event.server2.SyftEvents.process_pending_requests")
def test_start_calls_init_and_starts_observer(mock_process, syft_events):
    with patch.object(syft_events, "init") as mock_init, \
         patch.object(syft_events.obs, "start") as mock_obs_start:
        syft_events.start()
        mock_init.assert_called_once()
        mock_process.assert_called_once()
        mock_obs_start.assert_called_once()

@patch("syft_event.server2.generate_schema")
def test_publish_schema_writes_schema(mock_generate, syft_events, tmp_path):
    # Ensure directories exist
    syft_events.app_rpc_dir.mkdir(parents=True, exist_ok=True)
    
    # Register a dummy handler
    dummy = lambda req: Response(body={"ok": True})
    endpoint = syft_events.app_rpc_dir / "test"
    syft_events._SyftEvents__rpc[endpoint] = dummy
    mock_generate.return_value = {"args": {}, "returns": "any"}
    schema_path = syft_events.app_rpc_dir / "rpc.schema.json"
    syft_events.publish_schema()
    assert schema_path.exists()
    content = schema_path.read_text()
    assert "test" in content

@patch("syft_event.server2.SyftEvents._SyftEvents__handle_rpc")
def test_process_pending_requests_calls_handle_rpc(mock_handle, syft_events, tmp_path):
    # Setup a fake .request file and handler
    req_dir = syft_events.app_rpc_dir / "foo"
    req_dir.mkdir(parents=True, exist_ok=True)
    req_file = req_dir / "bar.request"
    req_file.write_text("{}")
    syft_events._SyftEvents__rpc[req_dir] = lambda req: Response(body={})
    # No .response file exists
    syft_events.process_pending_requests()
    mock_handle.assert_called_once()

@patch("syft_event.server2.SyftEvents.stop")
def test_run_forever_handles_keyboard_interrupt(mock_stop, syft_events):
    with patch.object(syft_events, "start"), \
         patch.object(syft_events._stop_event, "is_set", side_effect=[False, True]), \
         patch.object(syft_events._stop_event, "wait", side_effect=KeyboardInterrupt):
        # Should not raise
        syft_events.run_forever()
    mock_stop.assert_called_once()

@patch("syft_event.server2.SyftEvents.stop")
def test_run_forever_handles_exception(mock_stop, syft_events):
    with patch.object(syft_events, "start"), \
         patch.object(syft_events._stop_event, "is_set", side_effect=[False, True]), \
         patch.object(syft_events._stop_event, "wait", side_effect=Exception("fail")):
        with pytest.raises(Exception):
            syft_events.run_forever()
    mock_stop.assert_called_once()

def test_stop_shuts_down(syft_events):
    with patch.object(syft_events.obs, "stop") as mock_obs_stop, \
         patch.object(syft_events.obs, "join") as mock_obs_join, \
         patch.object(syft_events._thread_pool, "shutdown") as mock_shutdown:
        syft_events.stop()
        assert syft_events._stop_event.is_set()
        mock_obs_stop.assert_called_once()
        mock_obs_join.assert_called_once()
        mock_shutdown.assert_called_once_with(wait=True)

def test_include_router_registers_routes(syft_events):
    router = EventRouter()
    @router.on_request("/foo")
    def foo(req): return Response(body={})
    with patch.object(syft_events, "on_request", wraps=syft_events.on_request) as mock_on_req:
        syft_events.include_router(router, prefix="/api")
        mock_on_req.assert_called_with("/api/foo")

def test_on_request_registers_rpc(syft_events):
    func = lambda req: Response(body={})
    with patch.object(syft_events, "_SyftEvents__register_rpc") as mock_reg:
        decorator = syft_events.on_request("/bar")
        decorator(func)
        mock_reg.assert_called()

def test_watch_registers_handler(syft_events):
    func = lambda event: None
    with patch.object(syft_events.obs, "schedule") as mock_sched:
        decorator = syft_events.watch("foo/*.json")
        cb = decorator(func)
        assert callable(cb)
        mock_sched.assert_called()

@pytest.mark.parametrize("endpoint,expected", [("/foo", True), ("foo/bar", True), ("foo*", False)])
def test_to_endpoint_path_validation(syft_events, endpoint, expected):
    if "*" in endpoint or "?" in endpoint:
        with pytest.raises(ValueError):
            syft_events._SyftEvents__to_endpoint_path(endpoint)
    else:
        path = syft_events._SyftEvents__to_endpoint_path(endpoint)
        assert isinstance(path, Path)

def test_format_glob_replaces_placeholders(syft_events):
    result = syft_events._SyftEvents__format_glob("{datasite}/foo")
    assert result.startswith("**/")
    assert syft_events.client.email in result

# --- Integration-like test for __handle_rpc ---
@patch("syft_event.server2.SyftRequest")
@patch("syft_event.server2.rpc")
@patch("syft_event.server2.func_args_from_request")
def test_handle_rpc_happy_path(mock_args, mock_rpc, mock_req, syft_events):
    path = Path("/tmp/fake.request")
    func = MagicMock(return_value=Response(body={"ok": 1}))
    mock_req.load.return_value = MagicMock(is_expired=False)
    mock_args.return_value = {}
    # Use patch.object on the Path class instead of instance
    with patch.object(Path, "exists", return_value=True):
        syft_events._SyftEvents__handle_rpc(path, func)
    mock_rpc.reply_to.assert_called()

@patch("syft_event.server2.SyftRequest")
@patch("syft_event.server2.rpc")
def test_handle_rpc_request_load_error(mock_rpc, mock_req, syft_events):
    path = Path("/tmp/fake.request")
    func = MagicMock()
    mock_req.load.side_effect = Exception("fail load")
    # Use patch.object on the Path class instead of instance
    with patch.object(Path, "exists", return_value=True), \
         patch("loguru.logger.error") as mock_logger:  # Capture the error log
        syft_events._SyftEvents__handle_rpc(path, func)
    mock_rpc.write_response.assert_called()
    # Verify the error was logged
    mock_logger.assert_called_once()

@patch("syft_event.server2.SyftRequest")
@patch("syft_event.server2.rpc")
def test_handle_rpc_expired(mock_rpc, mock_req, syft_events):
    path = Path("/tmp/fake.request")
    func = MagicMock()
    req = MagicMock(is_expired=True, url="/expired")
    mock_req.load.return_value = req
    # Use patch.object on the Path class instead of instance
    with patch.object(Path, "exists", return_value=True):
        syft_events._SyftEvents__handle_rpc(path, func)
    mock_rpc.reply_to.assert_called_with(req, body="Request expired", status_code=SyftStatus.SYFT_419_EXPIRED, client=syft_events.client)

@patch("syft_event.server2.SyftRequest")
@patch("syft_event.server2.rpc")
@patch("syft_event.server2.func_args_from_request")
def test_handle_rpc_invalid_schema(mock_args, mock_rpc, mock_req, syft_events):
    path = Path("/tmp/fake.request")
    func = MagicMock()
    req = MagicMock(is_expired=False, url="/bad_schema")
    mock_req.load.return_value = req
    mock_args.side_effect = Exception("bad schema")
    # Use patch.object on the Path class instead of instance
    with patch.object(Path, "exists", return_value=True):
        syft_events._SyftEvents__handle_rpc(path, func)
    mock_rpc.reply_to.assert_called_with(req, body="Invalid request schema: bad schema", status_code=SyftStatus.SYFT_400_BAD_REQUEST, client=syft_events.client)

@patch("syft_event.server2.SyftRequest")
@patch("syft_event.server2.rpc")
@patch("syft_event.server2.func_args_from_request")
def test_handle_rpc_async_func(mock_args, mock_rpc, mock_req, syft_events):
    path = Path("/tmp/fake.request")
    
    # Create a real async function instead of mocking
    async def async_func(**kwargs):
        return Response(body={"ok": 2})
    
    mock_req.load.return_value = MagicMock(is_expired=False)
    mock_args.return_value = {}
    
    # Use patch.object on the Path class instead of instance
    with patch.object(Path, "exists", return_value=True), \
         patch.object(syft_events._thread_pool, "submit") as mock_submit:
        future = MagicMock()
        future.result.return_value = Response(body={"ok": 2})
        mock_submit.return_value = future
        syft_events._SyftEvents__handle_rpc(path, async_func)
    mock_rpc.reply_to.assert_called()

# Additional tests for edge cases
def test_handle_rpc_path_not_exists(syft_events):
    path = Path("/tmp/nonexistent.request")
    func = MagicMock()
    # Use patch.object on the Path class instead of instance
    with patch.object(Path, "exists", return_value=False):
        syft_events._SyftEvents__handle_rpc(path, func)
    # Should return early without calling anything
    func.assert_not_called()

@patch("syft_event.server2.SyftRequest")
@patch("syft_event.server2.rpc")
@patch("syft_event.server2.func_args_from_request")
def test_handle_rpc_sync_func_returns_dict(mock_args, mock_rpc, mock_req, syft_events):
    path = Path("/tmp/fake.request")
    func = MagicMock(return_value={"data": "test"})  # Return dict instead of Response
    mock_req.load.return_value = MagicMock(is_expired=False)
    mock_args.return_value = {}
    # Use patch.object on the Path class instead of instance
    with patch.object(Path, "exists", return_value=True):
        syft_events._SyftEvents__handle_rpc(path, func)
    # Should call reply_to with the dict as body and default status code
    mock_rpc.reply_to.assert_called()
    call_args = mock_rpc.reply_to.call_args
    assert call_args[1]["body"] == {"data": "test"}
    assert call_args[1]["status_code"] == SyftStatus.SYFT_200_OK

@patch("syft_event.server2.SyftRequest")
@patch("syft_event.server2.rpc")
@patch("syft_event.server2.func_args_from_request")
def test_handle_rpc_exception_in_handler(mock_args, mock_rpc, mock_req, syft_events):
    path = Path("/tmp/fake.request")
    func = MagicMock(side_effect=Exception("handler error"))
    mock_req.load.return_value = MagicMock(is_expired=False)
    mock_args.return_value = {}
    # Use patch.object on the Path class instead of instance
    with patch.object(Path, "exists", return_value=True):
        with pytest.raises(Exception, match="handler error"):
            syft_events._SyftEvents__handle_rpc(path, func) 