"""PDF text extraction."""

from pathlib import Path
from typing import List
import pdfplumber

from budget_parser.core.exceptions import PDFExtractionError
from budget_parser.utils.logger import get_logger

logger = get_logger(__name__)


class PDFExtractor:
    """Extracts text content from PDF files."""

    def __init__(self, lines_per_chunk: int = 30):
        """
        Initialize PDF extractor.

        Args:
            lines_per_chunk: Number of lines per text chunk
        """
        self.lines_per_chunk = lines_per_chunk

    def extract_full_text(self, pdf_path: Path) -> str:
        """
        Extract all text from PDF for validation purposes.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Full text content of the PDF

        Raises:
            PDFExtractionError: If PDF cannot be read
        """
        try:
            full_text = []
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    text = page.extract_text()
                    if text:
                        full_text.append(text)
                        logger.debug(f"Extracted text from page {page_num}")

            result = "\n".join(full_text)
            logger.info(f"Extracted {len(result)} characters from {pdf_path.name}")
            return result

        except Exception as e:
            raise PDFExtractionError(f"Failed to extract text from {pdf_path}: {str(e)}")

    def extract_text_chunks(self, pdf_path: Path) -> List[str]:
        """
        Split PDF text into manageable chunks for processing.

        Args:
            pdf_path: Path to PDF file

        Returns:
            List of text chunks

        Raises:
            PDFExtractionError: If PDF cannot be read
        """
        try:
            all_chunks = []
            current_chunk = []

            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if not text:
                        continue

                    lines = text.split("\n")
                    for line in lines:
                        current_chunk.append(line)
                        if len(current_chunk) >= self.lines_per_chunk:
                            all_chunks.append("\n".join(current_chunk))
                            current_chunk = []

            # Add remaining lines as final chunk
            if current_chunk:
                all_chunks.append("\n".join(current_chunk))

            logger.info(f"Split PDF into {len(all_chunks)} chunks ({self.lines_per_chunk} lines each)")
            return all_chunks

        except Exception as e:
            raise PDFExtractionError(f"Failed to extract chunks from {pdf_path}: {str(e)}")
