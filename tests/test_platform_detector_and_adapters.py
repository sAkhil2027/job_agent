import sys
import unittest
sys.path.insert(0, '.')

from src.services.automation.platform_detector import ApplicationPlatformDetector
from src.services.automation.adapters import adapter_registry, GreenhouseAdapter, LeverAdapter, WorkdayAdapter, GenericAdapter

class TestPlatformDetectorAndAdapters(unittest.TestCase):
    def test_platform_detection_urls(self):
        gh_res = ApplicationPlatformDetector.detect("https://boards.greenhouse.io/company/jobs/12345")
        self.assertEqual(gh_res["platform"], "greenhouse")
        self.assertEqual(gh_res["confidence"], 0.98)

        lever_res = ApplicationPlatformDetector.detect("https://jobs.lever.co/company/abc-123")
        self.assertEqual(lever_res["platform"], "lever")
        self.assertEqual(lever_res["confidence"], 0.98)

        wd_res = ApplicationPlatformDetector.detect("https://company.myworkdayjobs.com/en-US/careers/job/123")
        self.assertEqual(wd_res["platform"], "workday")
        self.assertTrue(wd_res["is_multi_step"])

        generic_res = ApplicationPlatformDetector.detect("https://careers.company.com/apply")
        self.assertEqual(generic_res["platform"], "generic")

    def test_dom_signature_detection(self):
        custom_dom_html = "<html><body><form id='application_form' class='grnhse_app'></form></body></html>"
        res = ApplicationPlatformDetector.detect("https://careers.customcompany.com/job/1", html_content=custom_dom_html)
        self.assertEqual(res["platform"], "greenhouse")
        self.assertEqual(res["detection_method"], "dom_signature")

    def test_adapter_registry(self):
        adapter = adapter_registry.get("greenhouse")
        self.assertIsInstance(adapter, GreenhouseAdapter)

        wd_adapter = adapter_registry.get("workday")
        self.assertIsInstance(wd_adapter, WorkdayAdapter)

        gen_adapter = adapter_registry.get("unknown_platform")
        self.assertIsInstance(gen_adapter, GenericAdapter)

if __name__ == "__main__":
    unittest.main()
