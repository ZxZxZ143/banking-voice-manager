from app.packs.contracts import ScenarioPack


class UnknownScenarioPackError(ValueError):
    def __init__(self) -> None:
        super().__init__("Requested scenario pack is not registered")


class ScenarioRegistry:
    """Authoritative trusted startup registrations, never imported from user input."""

    def __init__(self, *, default_pack_id: str) -> None:
        self.default_pack_id = default_pack_id
        self._packs: dict[str, ScenarioPack] = {}

    def register(self, pack: ScenarioPack) -> None:
        if pack.manifest.id in self._packs:
            raise ValueError("Scenario pack is already registered")
        self._packs[pack.manifest.id] = pack

    def get(self, pack_id: str | None = None) -> ScenarioPack:
        pack = self._packs.get(pack_id if pack_id is not None else self.default_pack_id)
        if pack is None:
            raise UnknownScenarioPackError()
        return pack

    def exists(self, pack_id: str) -> bool:
        return pack_id in self._packs

    def list(self) -> list[ScenarioPack]:
        return list(self._packs.values())
