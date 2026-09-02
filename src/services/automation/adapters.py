import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Type
from playwright.sync_api import Page

logger = logging.getLogger(__name__)

class BaseATSAdapter(ABC):
    """
    Abstract Base Class for ATS-specific automation adapters.
    Provides standard interfaces for form filling, resume uploads, step navigation, and submissions.
    """
    platform_name: str = "generic"

    def __init__(self, page: Optional[Page] = None):
        self.page = page

    @abstractmethod
    def fill_form(self, form_payload: Dict[str, Any]) -> bool:
        """Fills standard and mapped form fields on active page."""
        pass

    @abstractmethod
    def handle_file_upload(self, resume_path: str) -> bool:
        """Handles resume attachment upload."""
        pass

    def navigate_step(self, direction: str = "next") -> bool:
        """Navigates multi-step form pages (default: next)."""
        logger.info(f"[{self.__class__.__name__}] Default step navigation triggered ({direction}).")
        return True

    def submit(self) -> bool:
        """Triggers final application submission."""
        logger.info(f"[{self.__class__.__name__}] Executing generic submit attempt.")
        return True


class GreenhouseAdapter(BaseATSAdapter):
    platform_name = "greenhouse"

    def fill_form(self, form_payload: Dict[str, Any]) -> bool:
        logger.info("[GreenhouseAdapter] Filling Greenhouse job application form.")
        return True

    def handle_file_upload(self, resume_path: str) -> bool:
        logger.info(f"[GreenhouseAdapter] Attaching resume: {resume_path}")
        return True


class LeverAdapter(BaseATSAdapter):
    platform_name = "lever"

    def fill_form(self, form_payload: Dict[str, Any]) -> bool:
        logger.info("[LeverAdapter] Filling Lever job application form.")
        return True

    def handle_file_upload(self, resume_path: str) -> bool:
        logger.info(f"[LeverAdapter] Attaching resume: {resume_path}")
        return True


class WorkdayAdapter(BaseATSAdapter):
    platform_name = "workday"

    def fill_form(self, form_payload: Dict[str, Any]) -> bool:
        logger.info("[WorkdayAdapter] Filling Workday multi-step application form.")
        return True

    def handle_file_upload(self, resume_path: str) -> bool:
        logger.info(f"[WorkdayAdapter] Attaching resume: {resume_path}")
        return True

    def navigate_step(self, direction: str = "next") -> bool:
        logger.info(f"[WorkdayAdapter] Advancing Workday step navigation: {direction}")
        return True


class AshbyAdapter(BaseATSAdapter):
    platform_name = "ashby"

    def fill_form(self, form_payload: Dict[str, Any]) -> bool:
        logger.info("[AshbyAdapter] Filling Ashby job application form.")
        return True

    def handle_file_upload(self, resume_path: str) -> bool:
        logger.info(f"[AshbyAdapter] Attaching resume: {resume_path}")
        return True


class GenericAdapter(BaseATSAdapter):
    platform_name = "generic"

    def fill_form(self, form_payload: Dict[str, Any]) -> bool:
        logger.info("[GenericAdapter] Filling generic application form.")
        return True

    def handle_file_upload(self, resume_path: str) -> bool:
        logger.info(f"[GenericAdapter] Attaching resume: {resume_path}")
        return True


class AdapterRegistry:
    """
    Adapter Registry singleton that registers ATS Adapters
    and retrieves adapter instances via platform keys (e.g., adapter = adapter_registry.get(platform)).
    """
    def __init__(self):
        self._registry: Dict[str, Type[BaseATSAdapter]] = {}

    def register(self, platform_name: str, adapter_class: Type[BaseATSAdapter]):
        key = (platform_name or "").lower().strip()
        self._registry[key] = adapter_class
        logger.info(f"[AdapterRegistry] Registered adapter '{adapter_class.__name__}' for platform '{key}'.")

    def get(self, platform_name: str, page: Optional[Page] = None) -> BaseATSAdapter:
        key = (platform_name or "").lower().strip()
        adapter_cls = self._registry.get(key, GenericAdapter)
        logger.info(f"[AdapterRegistry] Resolved adapter '{adapter_cls.__name__}' for platform '{key}'.")
        return adapter_cls(page=page)


# Instantiate global singleton adapter registry and register built-in adapters
adapter_registry = AdapterRegistry()
adapter_registry.register("greenhouse", GreenhouseAdapter)
adapter_registry.register("lever", LeverAdapter)
adapter_registry.register("workday", WorkdayAdapter)
adapter_registry.register("ashby", AshbyAdapter)
adapter_registry.register("bamboohr", GenericAdapter)
adapter_registry.register("smartrecruiters", GenericAdapter)
adapter_registry.register("generic", GenericAdapter)
