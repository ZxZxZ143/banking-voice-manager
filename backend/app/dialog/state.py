from app.dialog.models import DialogState, DialogTurn


def append_turn(state: DialogState, turn: DialogTurn) -> DialogState:
    """Return a copy; conversation orchestration must save it explicitly."""
    updated = state.model_copy(deep=True)
    updated.history = [*updated.history, turn.model_copy(deep=True)][-20:]
    if turn.role == "user":
        updated.turn_number += 1
    return updated
