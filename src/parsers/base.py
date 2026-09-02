from abc import ABC, abstractmethod

class BaseParser(ABC):
    @abstractmethod
    def extract_text(self, file_path_or_bytes) -> str:
        """Extract text from the given file source."""
        pass
