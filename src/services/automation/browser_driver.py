import os
import time
import logging
from typing import Optional
from playwright.sync_api import sync_playwright, Playwright, BrowserContext, Page

from src.config import Config

logger = logging.getLogger(__name__)

class BrowserDriver:
    """
    Encapsulated Playwright Chromium Browser Driver for persistent context,
    popup multi-tab handling, anti-detection flags, and audit screenshots.
    """
    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.session_id: Optional[str] = None
        self.pages_list: list[Page] = []

    def _cleanup_profile_locks(self, profile_dir: str):
        """
        Cleans legacy Chromium SingletonLock files to prevent profile locking crashes.
        """
        try:
            lock_file = os.path.join(profile_dir, "SingletonLock")
            if os.path.exists(lock_file) or os.path.islink(lock_file):
                logger.info(f"[BrowserDriver] Removing stale profile lock file: {lock_file}")
                os.remove(lock_file)
        except Exception as e:
            logger.warning(f"[BrowserDriver] Could not remove profile lock file: {e}")

    def _on_new_page(self, new_page: Page):
        """
        Event listener triggered when job application opens new tabs or popups (target='_blank').
        """
        logger.info(f"[BrowserDriver] New tab/popup detected: {new_page.url or 'about:blank'}")
        if new_page not in self.pages_list:
            self.pages_list.append(new_page)
        self.page = new_page

    def start(self, session_id: str = None) -> "BrowserDriver":
        """
        Starts Playwright and launches persistent Chromium context.
        """
        Config.ensure_directories()
        self.session_id = session_id or f"session_{int(time.time())}"
        
        profile_dir = str(Config.BROWSER_PROFILE_DIR)
        self._cleanup_profile_locks(profile_dir)

        logger.info(f"[BrowserDriver] Starting Playwright Chromium context (Headless: {Config.HEADLESS_MODE})...")
        
        self.playwright = sync_playwright().start()
        
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox"
        ]
        
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=Config.HEADLESS_MODE,
            viewport={"width": 1280, "height": 800},
            args=launch_args,
            timeout=Config.APPLICATION_TIMEOUT * 1000
        )
        
        # Attach popup multi-tab event listener
        self.context.on("page", self._on_new_page)

        # Set default active page
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = self.context.new_page()
            
        self.pages_list = list(self.context.pages)
        logger.info("[BrowserDriver] Chromium context initialized successfully.")
        return self

    def get_page(self) -> Page:
        """
        Returns active application browser tab page.
        """
        if not self.page or self.page.is_closed():
            if self.context and self.context.pages:
                self.page = self.context.pages[-1]
            elif self.context:
                self.page = self.context.new_page()
            else:
                raise RuntimeError("BrowserDriver context is not initialized. Call start() first.")
        return self.page

    def navigate(self, url: str, wait_until: str = "domcontentloaded") -> Page:
        """
        Navigates active page to target URL using fast DOM content loaded strategy.
        """
        page = self.get_page()
        timeout_ms = Config.APPLICATION_TIMEOUT * 1000
        logger.info(f"[BrowserDriver] Navigating to: {url}")
        page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        return page

    def screenshot(self, step_name: str, session_id: str = None) -> str:
        """
        Captures full-page PNG screenshot to Config.SCREENSHOT_DIR and returns file path.
        """
        page = self.get_page()
        sid = session_id or self.session_id or "session"
        clean_step = str(step_name).replace(" ", "_").lower()
        filename = f"{sid}_{clean_step}_{int(time.time())}.png"
        filepath = os.path.join(str(Config.SCREENSHOT_DIR), filename)
        
        try:
            page.screenshot(path=filepath, full_page=True)
            logger.info(f"[BrowserDriver] Saved screenshot artifact: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"[BrowserDriver] Failed to capture screenshot: {e}")
            return ""

    def close(self):
        """
        Safely tears down browser pages, persistent context, and Playwright instance.
        """
        logger.info("[BrowserDriver] Closing browser context and Playwright instance...")
        try:
            if self.context:
                self.context.close()
        except Exception as e:
            logger.warning(f"[BrowserDriver] Error closing context: {e}")
        finally:
            self.context = None

        try:
            if self.playwright:
                self.playwright.stop()
        except Exception as e:
            logger.warning(f"[BrowserDriver] Error stopping Playwright: {e}")
        finally:
            self.playwright = None
            self.page = None

    def __enter__(self) -> "BrowserDriver":
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
