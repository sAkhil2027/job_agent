import sys
import json
import unittest
sys.path.insert(0, '.')

from src.services.automation.browser_driver import BrowserDriver
from src.services.automation.form_inspector import FormInspector

class TestFormInspector(unittest.TestCase):
    def test_dom_form_inspection(self):
        print("--- 1. Initializing Playwright BrowserDriver ---")
        with BrowserDriver() as driver:
            page = driver.get_page()

            print("--- 2. Navigating to Test Job Application HTML ---")
            test_html = """
            data:text/html,<html>
            <head><title>Job Portal Form Test</title></head>
            <body>
                <div class="step-indicator">Step 2 of 4</div>
                <form id="job-form">
                    <fieldset id="work-history-section">
                        <legend>Work Experience</legend>
                        <div class="form-group">
                            <label for="first_name">First Name *</label>
                            <input type="text" id="first_name" name="first_name" required placeholder="John">
                        </div>
                        <button id="add-exp">Add Work Experience</button>
                    </fieldset>
                    <div class="form-group">
                        <label for="email">Email Address *</label>
                        <input type="email" id="email" name="email" required>
                    </div>
                    <div class="form-group">
                        <label for="resume">Attach Resume PDF *</label>
                        <input type="file" id="resume" name="resume" accept=".pdf" required>
                    </div>
                    <div class="form-group">
                        <label for="experience_years">Years of Experience</label>
                        <select id="experience_years" name="experience">
                            <option value="1-3">1-3 Years</option>
                            <option value="3-5">3-5 Years</option>
                            <option value="5+">5+ Years</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Are you authorized to work in the US?</label>
                        <div role="combobox" id="work_auth" aria-label="Work Authorization">
                            <div role="option">Yes</div>
                            <div role="option">No</div>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="cover_note">Cover Note</label>
                        <textarea id="cover_note" name="cover_note" placeholder="Write a note..."></textarea>
                    </div>
                    <button id="next-btn" type="submit">Next</button>
                </form>
            </body>
            </html>
            """
            driver.navigate(test_html)

            print("--- 3. Running FormInspector.inspect(page) ---")
            schema = FormInspector.inspect(page)
            schema_dict = schema.to_dict()
            print("Extracted Form Schema:", json.dumps(schema_dict, indent=2))

            fields = schema_dict["fields"]
            self.assertGreaterEqual(len(fields), 5, f"Expected at least 5 fields, got {len(fields)}")
            
            # Verify first_name field
            fn_field = next(f for f in fields if "first" in f["field_id"] or "first" in f["name"])
            self.assertTrue(fn_field["required"])
            self.assertIn("First Name", fn_field["label"])
            
            # Verify file upload
            self.assertTrue(schema.has_file_upload)
            
            # Verify custom question detection (work auth)
            self.assertTrue(schema.has_custom_questions)
            
            # Verify select dropdown options
            select_field = next(f for f in fields if f["field_type"] == "select")
            self.assertEqual(len(select_field["options"]), 3)
            self.assertIn("1-3 Years", select_field["options"])

            # Verify Section Repeatable Detection
            self.assertGreaterEqual(len(schema.sections), 1)
            exp_section = schema.sections[0]
            self.assertEqual(exp_section.section_type, "experience")
            self.assertTrue(exp_section.is_repeatable)

            # Verify Multi-Step Wizard Tracking
            self.assertIsNotNone(schema.multi_step)
            self.assertTrue(schema.multi_step.is_multi_step)
            self.assertEqual(schema.multi_step.current_step, 2)
            self.assertEqual(schema.multi_step.total_steps, 4)
            self.assertIsNotNone(schema.multi_step.next_button_selector)

        print("[OK] FormInspector unit tests passed 100% successfully!")

if __name__ == "__main__":
    unittest.main()
