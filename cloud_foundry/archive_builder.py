class ArchiveBuilder:
    def hash(self) -> str:
        raise NotImplementedError

    def location(self) -> str:
        raise NotImplementedError
