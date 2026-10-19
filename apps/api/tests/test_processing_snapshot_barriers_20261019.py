"""Deterministic controls for processing snapshot barrier failure diagnostics."""

from concurrent.futures import Future
from threading import Event
from unittest.mock import Mock, patch

import pytest

from tests.processing_snapshot_barriers import wait_for_processing_barrier


def test_entered_barrier_does_not_inspect_future():
    entered = Mock(spec=Event)
    entered.wait.return_value = True
    pending = Mock(spec=Future)

    assert wait_for_processing_barrier(entered, pending, "missing barrier") is None

    entered.wait.assert_called_once_with(20)
    pending.done.assert_not_called()
    pending.result.assert_not_called()


def test_completed_future_original_exception_is_preserved():
    entered = Mock(spec=Event)
    entered.wait.return_value = False
    pending = Future()
    original = RuntimeError("original worker exception")
    pending.set_exception(original)

    with patch.object(pending, "result", wraps=pending.result) as result:
        with pytest.raises(RuntimeError) as caught:
            wait_for_processing_barrier(entered, pending, "missing barrier")
        result.assert_called_once_with()

    assert caught.value is original
    entered.wait.assert_called_once_with(20)


def test_completed_success_without_barrier_keeps_original_assertion():
    entered = Mock(spec=Event)
    entered.wait.return_value = False
    pending = Future()
    pending.set_result("completed without entering")
    message = "original missing barrier"

    with patch.object(pending, "result", wraps=pending.result) as result:
        with pytest.raises(AssertionError) as caught:
            wait_for_processing_barrier(entered, pending, message)
        result.assert_called_once_with()

    assert str(caught.value) == message
    entered.wait.assert_called_once_with(20)


def test_pending_future_keeps_assertion_without_waiting_for_result():
    entered = Mock(spec=Event)
    entered.wait.return_value = False
    pending = Mock(spec=Future)
    pending.done.return_value = False
    pending.result.side_effect = AssertionError("pending result must not be awaited")
    message = "original missing barrier"

    with pytest.raises(AssertionError) as caught:
        wait_for_processing_barrier(entered, pending, message)

    assert str(caught.value) == message
    entered.wait.assert_called_once_with(20)
    pending.done.assert_called_once_with()
    pending.result.assert_not_called()
