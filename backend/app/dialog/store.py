from collections import OrderedDict

from app.dialog.models import DialogState


class InMemoryDialogStore:
    """Bounded single-process store; callers serialize turns within a session later."""

    def __init__(self, max_sessions: int = 100) -> None:
        if max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self._max_sessions = max_sessions
        self._states: OrderedDict[str, DialogState] = OrderedDict()

    def get(self, session_id: str) -> DialogState | None:
        state = self._states.get(session_id)
        if state is None:
            return None
        self._states.move_to_end(session_id)
        return state.model_copy(deep=True)

    def save(self, state: DialogState) -> None:
        self._states[state.session_id] = state.model_copy(deep=True)
        self._states.move_to_end(state.session_id)
        while len(self._states) > self._max_sessions:
            self._states.popitem(last=False)

    def delete(self, session_id: str) -> None:
        self._states.pop(session_id, None)
