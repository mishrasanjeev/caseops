"""Preserve worker failures when a processing snapshot barrier is not reached."""


def wait_for_processing_barrier(entered, pending, message):
    if entered.wait(20):
        return
    if pending.done():
        pending.result()
    raise AssertionError(message)
