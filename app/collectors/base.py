from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.schemas.collector import CollectedJob


class JobCollector(ABC):
    """Contract implemented by each future public job source adapter."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the stable source identifier stored with collected jobs."""

    @abstractmethod
    def collect(self) -> AsyncIterator[CollectedJob]:
        """Yield validated jobs using non-blocking I/O."""
