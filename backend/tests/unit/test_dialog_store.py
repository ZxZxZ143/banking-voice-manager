import asyncio

import pytest

from app.dialog.models import DialogState
from app.dialog.store import InMemoryDialogStore, SessionCapacityError


def test_failed_turn_releases_its_session_lease():
    async def run():
        store = InMemoryDialogStore(max_sessions=1)
        with pytest.raises(RuntimeError, match="failed turn"):
            async with store.session("failed"):
                raise RuntimeError("failed turn")
        # A leaked lease would exhaust the single available session slot.
        async with store.session("next"):
            store.save(DialogState(session_id="next", turn_number=1))
        assert store.get("failed") is None
        assert store.get("next").turn_number == 1

    asyncio.run(run())


def test_cancelled_waiter_preserves_holder_lease_and_cancelled_holder_releases_it():
    async def run():
        store = InMemoryDialogStore(max_sessions=1)
        holder_entered = asyncio.Event()
        waiter_started = asyncio.Event()
        hold = asyncio.Event()

        async def holder():
            async with store.session("shared"):
                holder_entered.set()
                await hold.wait()

        async def waiter():
            waiter_started.set()
            async with store.session("shared"):
                pytest.fail("Cancelled waiter must never acquire the session")

        holder_task = asyncio.create_task(holder())
        await holder_entered.wait()
        waiter_task = asyncio.create_task(waiter())
        await waiter_started.wait()
        waiter_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter_task
        # Cancelling the queued user must not remove the current holder's lease.
        with pytest.raises(SessionCapacityError):
            async with store.session("other"):
                pytest.fail("The holder still occupies capacity")
        holder_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await holder_task
        async with store.session("other"):
            store.save(DialogState(session_id="other"))
        assert store.get("other") is not None

    asyncio.run(run())


def test_distinct_in_flight_sessions_are_bounded_and_rejected_leases_do_not_leak():
    async def run():
        store = InMemoryDialogStore(max_sessions=2)
        async with store.session("first"):
            async with store.session("second"):
                for session_id in ("third", "fourth"):
                    with pytest.raises(SessionCapacityError):
                        async with store.session(session_id):
                            pytest.fail("The active session bound must reject this lease")
            async with store.session("third"):
                store.save(DialogState(session_id="third"))
        async with store.session("fourth"):
            store.save(DialogState(session_id="fourth"))
        assert store.get("third") is not None
        assert store.get("fourth") is not None

    asyncio.run(run())


def test_pinned_state_survives_another_session_save_and_all_pinned_rejects_eviction():
    async def run():
        store = InMemoryDialogStore(max_sessions=2)
        store.save(DialogState(session_id="oldest", slots={"phone": "+77010000000"}))
        store.save(DialogState(session_id="idle"))
        async with store.session("oldest"):
            async with store.session("new"):
                store.save(DialogState(session_id="new", turn_number=1))
                assert store.get("idle") is None
                assert store.get("oldest").slots == {"phone": "+77010000000"}
                with pytest.raises(SessionCapacityError):
                    store.save(DialogState(session_id="overflow"))
                assert store.get("overflow") is None
                assert store.get("new").turn_number == 1
                assert store.get("oldest").slots == {"phone": "+77010000000"}

    asyncio.run(run())


def test_lru_read_refreshes_recency_and_save_and_get_keep_nested_copies():
    store = InMemoryDialogStore(max_sessions=2)
    original = DialogState(session_id="first", slots={"drivers_iin": ["111111111111"]})
    store.save(original)
    store.save(DialogState(session_id="second"))
    original.slots["drivers_iin"].append("222222222222")
    retrieved = store.get("first")
    assert retrieved.slots == {"drivers_iin": ["111111111111"]}
    retrieved.slots["drivers_iin"].clear()
    store.save(DialogState(session_id="third"))
    assert store.get("second") is None
    assert store.get("first").slots == {"drivers_iin": ["111111111111"]}
    assert store.get("third") is not None
