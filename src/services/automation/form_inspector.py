import logging
import re
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from playwright.sync_api import Page

logger = logging.getLogger(__name__)

@dataclass
class FormField:
    field_id: str
    name: str
    field_type: str  # text, email, tel, file, select, textarea, radio, checkbox, combobox
    label: str
    required: bool
    placeholder: str = ""
    options: List[str] = field(default_factory=list)
    selector: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class FormSection:
    section_id: str
    section_type: str  # "experience", "education", "custom_questions", "general"
    title: str
    is_repeatable: bool
    add_more_selector: Optional[str] = None
    fields: List[FormField] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_id": self.section_id,
            "section_type": self.section_type,
            "title": self.title,
            "is_repeatable": self.is_repeatable,
            "add_more_selector": self.add_more_selector,
            "fields": [f.to_dict() for f in self.fields]
        }

@dataclass
class MultiStepState:
    is_multi_step: bool = False
    current_step: int = 1
    total_steps: Optional[int] = None
    step_title: str = ""
    next_button_selector: Optional[str] = None
    prev_button_selector: Optional[str] = None
    submit_button_selector: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class FormSchema:
    fields: List[FormField] = field(default_factory=list)
    sections: List[FormSection] = field(default_factory=list)
    multi_step: Optional[MultiStepState] = None
    has_file_upload: bool = False
    has_custom_questions: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fields": [f.to_dict() for f in self.fields],
            "sections": [s.to_dict() for s in self.sections],
            "multi_step": self.multi_step.to_dict() if self.multi_step else None,
            "has_file_upload": self.has_file_upload,
            "has_custom_questions": self.has_custom_questions
        }

class FormInspector:
    """
    DOM Form Inspector that extracts structured form schemas from Playwright active pages.
    Inspects native inputs, textareas, file uploads, selects, ARIA controls, repeatable sections,
    and multi-step form wizard indicators.
    """
    
    JS_INSPECT_SCRIPT = """
    () => {
        const fields = [];
        const sections = [];
        
        function isVisible(elem) {
            if (!elem) return false;
            const style = window.getComputedStyle(elem);
            return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && elem.offsetWidth > 0 && elem.offsetHeight > 0;
        }

        function findLabelText(elem) {
            if (elem.id) {
                const labelElem = document.querySelector(`label[for="${elem.id}"]`);
                if (labelElem && labelElem.textContent) return labelElem.textContent.trim();
            }
            const parentLabel = elem.closest('label');
            if (parentLabel && parentLabel.textContent) return parentLabel.textContent.trim();

            if (elem.getAttribute('aria-label')) return elem.getAttribute('aria-label').trim();
            if (elem.getAttribute('aria-labelledby')) {
                const lElem = document.getElementById(elem.getAttribute('aria-labelledby'));
                if (lElem && lElem.textContent) return lElem.textContent.trim();
            }

            let prev = elem.previousElementSibling;
            if (prev && prev.textContent && prev.textContent.trim().length < 100) {
                return prev.textContent.trim();
            }

            const container = elem.closest('.form-group, .field, .application-question, div[class*="field"], fieldset');
            if (container) {
                const titleElem = container.querySelector('label, .label, .field-label, span[class*="label"], legend');
                if (titleElem && titleElem.textContent) return titleElem.textContent.trim();
            }

            return elem.getAttribute('placeholder') || elem.getAttribute('name') || elem.id || '';
        }

        const elements = document.querySelectorAll('input, select, textarea, [role="combobox"], [role="listbox"]');
        
        elements.forEach((elem, idx) => {
            if (elem.type === 'hidden' || elem.type === 'submit' || elem.type === 'button') return;
            if (!isVisible(elem) && elem.type !== 'file') return;

            const elemId = elem.id || `field_${idx}`;
            const name = elem.getAttribute('name') || '';
            const type = (elem.getAttribute('type') || elem.tagName.toLowerCase() || 'text').toLowerCase();
            const placeholder = elem.getAttribute('placeholder') || '';
            
            const rawLabel = findLabelText(elem);
            const isRequired = elem.hasAttribute('required') || elem.getAttribute('aria-required') === 'true' || rawLabel.includes('*');
            const cleanLabel = rawLabel.replace(/\\*/g, '').replace(/\\s+/g, ' ').trim();

            let options = [];
            if (elem.tagName.toLowerCase() === 'select') {
                options = Array.from(elem.options).map(o => o.text.trim()).filter(t => t.length > 0);
            } else if (elem.getAttribute('role') === 'listbox' || elem.getAttribute('role') === 'combobox') {
                const optElems = elem.querySelectorAll('[role="option"], option');
                options = Array.from(optElems).map(o => o.textContent.trim()).filter(t => t.length > 0);
            }

            let selector = '';
            if (elem.id) {
                selector = `#${elem.id}`;
            } else if (name) {
                selector = `${elem.tagName.toLowerCase()}[name="${name}"]`;
            } else {
                selector = `${elem.tagName.toLowerCase()}:nth-of-type(${idx + 1})`;
            }

            fields.push({
                field_id: elemId,
                name: name,
                field_type: type,
                label: cleanLabel,
                required: isRequired,
                placeholder: placeholder,
                options: options,
                selector: selector
            });
        });

        // Dynamic Section Extraction (Experience & Education repeatable containers)
        const containerBlocks = document.querySelectorAll('fieldset, [data-automation-id*="section"], [class*="section"], [class*="experience"], [class*="education"], [id*="experience"], [id*="education"]');
        containerBlocks.forEach((block, bIdx) => {
            const headingElem = block.querySelector('h1, h2, h3, h4, legend, .section-title, [class*="title"]');
            const title = headingElem ? headingElem.textContent.trim() : `Section ${bIdx + 1}`;
            const titleLower = title.toLowerCase();

            let sType = "general";
            if (titleLower.includes("experience") || titleLower.includes("work history") || (block.className && block.className.includes("experience"))) {
                sType = "experience";
            } else if (titleLower.includes("education") || titleLower.includes("school") || (block.className && block.className.includes("education"))) {
                sType = "education";
            }

            const addBtn = Array.from(block.querySelectorAll('button, a')).find(b => {
                const txt = (b.textContent || '').toLowerCase();
                const cls = (b.className || '').toLowerCase();
                return txt.includes('add') || cls.includes('add');
            });

            let addSelector = null;
            if (addBtn) {
                addSelector = addBtn.id ? `#${addBtn.id}` : `button:has-text("${addBtn.textContent.trim()}")`;
            }

            if (sType !== "general" || addBtn) {
                sections.push({
                    section_id: block.id || `section_${sType}_${bIdx}`,
                    section_type: sType,
                    title: title,
                    is_repeatable: !!addBtn || sType !== "general",
                    add_more_selector: addSelector
                });
            }
        });

        // Multi-step Wizard Navigation State Detection
        let currentStep = 1;
        let totalSteps = null;
        let stepTitle = "";
        
        const stepIndicators = document.querySelectorAll('.step-indicator, .progress-bar, [role="progressbar"], ol[class*="step"], ul[class*="step"]');
        if (stepIndicators.length > 0) {
            const stepText = document.body.innerText.match(/step\\s+(\\d+)\\s+of\\s+(\\d+)/i);
            if (stepText) {
                currentStep = parseInt(stepText[1], 10);
                totalSteps = parseInt(stepText[2], 10);
            }
        }

        const allButtons = Array.from(document.querySelectorAll('button, input[type="submit"]'));
        const nextBtn = allButtons.find(b => {
            const txt = (b.textContent || b.value || '').toLowerCase();
            return txt.includes('next') || txt.includes('continue');
        });
        const prevBtn = allButtons.find(b => {
            const txt = (b.textContent || b.value || '').toLowerCase();
            return txt.includes('back') || txt.includes('previous');
        });
        const submitBtn = allButtons.find(b => {
            const txt = (b.textContent || b.value || '').toLowerCase();
            return txt.includes('submit');
        });

        const multiStepState = {
            is_multi_step: !!(stepIndicators.length > 0 || (nextBtn && !submitBtn) || totalSteps),
            current_step: currentStep,
            total_steps: totalSteps,
            step_title: stepTitle,
            next_button_selector: nextBtn ? (nextBtn.id ? `#${nextBtn.id}` : `button:has-text("${(nextBtn.textContent || nextBtn.value).trim()}")`) : null,
            prev_button_selector: prevBtn ? (prevBtn.id ? `#${prevBtn.id}` : `button:has-text("${(prevBtn.textContent || prevBtn.value).trim()}")`) : null,
            submit_button_selector: submitBtn ? (submitBtn.id ? `#${submitBtn.id}` : `button:has-text("${(submitBtn.textContent || submitBtn.value).trim()}")`) : null
        };

        return {
            fields: fields,
            sections: sections,
            multi_step: multiStepState
        };
    }
    """

    @classmethod
    def inspect(cls, page: Page) -> FormSchema:
        """
        Inspects the active Playwright page and returns a structured FormSchema.
        """
        if not page:
            logger.warning("[FormInspector] Page object is None. Returning empty schema.")
            return FormSchema()

        try:
            raw = page.evaluate(cls.JS_INSPECT_SCRIPT)
            raw_fields = raw.get("fields", [])
            raw_sections = raw.get("sections", [])
            raw_multi = raw.get("multi_step", {})

            fields = []
            has_file = False
            has_custom = False

            for item in raw_fields:
                field_obj = FormField(
                    field_id=item.get("field_id", ""),
                    name=item.get("name", ""),
                    field_type=item.get("field_type", "text"),
                    label=item.get("label", ""),
                    required=item.get("required", False),
                    placeholder=item.get("placeholder", ""),
                    options=item.get("options", []),
                    selector=item.get("selector", "")
                )
                fields.append(field_obj)
                
                if field_obj.field_type == "file" or "resume" in field_obj.label.lower():
                    has_file = True

                label_lower = field_obj.label.lower()
                if any(kw in label_lower for kw in ["authoriz", "sponsor", "salary", "race", "gender", "veteran", "disability", "hear about", "work auth"]):
                    has_custom = True

            sections = []
            for sec in raw_sections:
                sections.append(FormSection(
                    section_id=sec.get("section_id", ""),
                    section_type=sec.get("section_type", "general"),
                    title=sec.get("title", ""),
                    is_repeatable=sec.get("is_repeatable", False),
                    add_more_selector=sec.get("add_more_selector")
                ))

            multi_state = MultiStepState(
                is_multi_step=raw_multi.get("is_multi_step", False),
                current_step=raw_multi.get("current_step", 1),
                total_steps=raw_multi.get("total_steps"),
                step_title=raw_multi.get("step_title", ""),
                next_button_selector=raw_multi.get("next_button_selector"),
                prev_button_selector=raw_multi.get("prev_button_selector"),
                submit_button_selector=raw_multi.get("submit_button_selector")
            )

            logger.info(f"[FormInspector] Inspected form: {len(fields)} fields, {len(sections)} sections (Multi-Step: {multi_state.is_multi_step}).")
            return FormSchema(
                fields=fields,
                sections=sections,
                multi_step=multi_state,
                has_file_upload=has_file,
                has_custom_questions=has_custom
            )
        except Exception as e:
            logger.error(f"[FormInspector] Failed to inspect page DOM: {e}")
            return FormSchema()
