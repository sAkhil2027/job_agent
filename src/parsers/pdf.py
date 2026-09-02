import io
from pypdf import PdfReader
from src.parsers.base import BaseParser

class PDFParser(BaseParser):
    def extract_text(self, file_source) -> str:
        """
        Extracts raw text from a PDF file path or a bytes-like object (e.g. BytesIO).
        """
        if isinstance(file_source, bytes):
            reader = PdfReader(io.BytesIO(file_source))
        elif isinstance(file_source, io.BytesIO):
            reader = PdfReader(file_source)
        else:
            # Assume it's a file path string or Path object
            reader = PdfReader(file_source)
        
        full_text = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                full_text.append(text)
        
        # Extract hyperlink annotations
        links = []
        for page in reader.pages:
            if "/Annots" in page:
                for annot in page["/Annots"]:
                    try:
                        annot_obj = annot.get_object()
                        if annot_obj and annot_obj.get("/Subtype") == "/Link":
                            action = annot_obj.get("/A")
                            if action and "/URI" in action:
                                uri = action["/URI"]
                                links.append(uri)
                    except Exception:
                        pass
        
        if links:
            full_text.append("\n\nExtracted Hyperlinks:\n" + "\n".join(links))
            
        return "\n".join(full_text)
