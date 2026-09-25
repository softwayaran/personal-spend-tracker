"""Main processing pipeline orchestrator."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from budget_parser.config.settings import Settings
from budget_parser.core.models import Transaction
from budget_parser.database.db import upsert_transactions
from budget_parser.extractors.pdf_extractor import PDFExtractor
from budget_parser.extractors.llm_extractor import LLMExtractor
from budget_parser.extractors.regex_extractor import RegexExtractor
from budget_parser.validators.transaction_validator import TransactionValidator
from budget_parser.filters.keyword_filter import KeywordFilter
from budget_parser.file_manager.manager import FileManager
from budget_parser.utils.date_utils import infer_years
from budget_parser.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing a PDF file."""
    pdf_file: Path
    raw_transactions: int
    validated_transactions: int
    filtered_transactions: int
    exported_transactions: int
    success: bool
    error: Optional[str] = None


class Pipeline:
    """Main processing pipeline that orchestrates all components."""

    def __init__(self, settings: Settings, year: Optional[int] = None, db_path: str = "budget.db"):
        """
        Initialize pipeline with configuration.

        Args:
            settings: Application settings
            year: Statement year used to convert MM/DD dates to YYYY-MM-DD
            db_path: Path to the SQLite database
        """
        self.settings = settings
        self.year = year
        self.db_path = db_path

        # Initialize components
        self.pdf_extractor = PDFExtractor(lines_per_chunk=settings.lines_per_chunk)
        self.llm_extractor = LLMExtractor(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            top_p=settings.llm_top_p,
            num_predict=settings.llm_num_predict
        )
        self.regex_extractor = RegexExtractor()
        self.validator = TransactionValidator()

        # Initialize filters (chain of responsibility pattern)
        self.filters = [
            KeywordFilter("RewardsFilter", settings.rewards_keywords),
            KeywordFilter("PaymentFilter", settings.payment_keywords),
            KeywordFilter("AggregateFilter", settings.aggregate_keywords),
        ]

        self.file_manager = FileManager(
            todo_folder=settings.todo_folder,
            done_folder=settings.done_folder
        )

    def run(self) -> List[ProcessingResult]:
        """
        Run the complete processing pipeline.

        Returns:
            List of processing results for each PDF
        """
        logger.info("=" * 60)
        logger.info("Budget Parser - Starting Processing")
        logger.info("=" * 60)

        # Ensure folders exist
        self.file_manager.ensure_folders_exist()

        # Get PDF files to process
        pdf_files = self.file_manager.get_pending_pdfs()

        if not pdf_files:
            logger.warning("No PDF files found to process")
            return []

        logger.info(f"Found {len(pdf_files)} PDF file(s) to process")

        # Process each PDF
        results = []
        for pdf_file in pdf_files:
            result = self.process_pdf(pdf_file)
            results.append(result)

        # Summary
        logger.info("=" * 60)
        logger.info("Processing Summary")
        logger.info("=" * 60)

        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        total_exported = sum(r.exported_transactions for r in results if r.success)

        logger.info(f"Total PDFs processed: {len(results)}")
        logger.info(f"Successful: {successful}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Total transactions exported: {total_exported}")

        return results

    def process_pdf(self, pdf_path: Path) -> ProcessingResult:
        """
        Process a single PDF file.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Processing result
        """
        logger.info(f"\nProcessing: {pdf_path.name}")
        logger.info("-" * 60)

        try:
            # Extract and validate transactions
            validated_transactions = self._extract_and_validate(pdf_path)

            # Apply filters
            filtered_transactions = self._apply_filters(validated_transactions)

            # Convert MM/DD dates to YYYY-MM-DD (with year-boundary detection) and insert into DB
            iso_dates = infer_years(filtered_transactions, self.year)
            tx_dicts = [
                {"date": iso_date, "description": tx.description, "amount": tx.amount}
                for tx, iso_date in zip(filtered_transactions, iso_dates)
            ]
            stats = upsert_transactions(self.db_path, self.year, tx_dicts)
            exported_count = stats["inserted"]

            # Move to done folder if enabled
            if self.settings.move_to_done:
                self.file_manager.move_to_done(pdf_path)

            logger.info(f"Successfully processed {pdf_path.name}")

            return ProcessingResult(
                pdf_file=pdf_path,
                raw_transactions=len(validated_transactions),
                validated_transactions=len(validated_transactions),
                filtered_transactions=len(filtered_transactions),
                exported_transactions=exported_count,
                success=True
            )

        except Exception as e:
            error_msg = f"Error processing {pdf_path.name}: {str(e)}"
            logger.error(error_msg)

            return ProcessingResult(
                pdf_file=pdf_path,
                raw_transactions=0,
                validated_transactions=0,
                filtered_transactions=0,
                exported_transactions=0,
                success=False,
                error=str(e)
            )

    def _extract_and_validate(self, pdf_path: Path) -> List[Transaction]:
        """
        Extract text, extract transactions, and validate them.

        Args:
            pdf_path: Path to PDF file

        Returns:
            List of validated transactions
        """
        # Extract full text for validation
        full_text = self.pdf_extractor.extract_full_text(pdf_path)

        # Extract chunks for processing
        chunks = self.pdf_extractor.extract_text_chunks(pdf_path)

        all_transactions = []

        for i, chunk in enumerate(chunks, 1):
            logger.info(f"Processing chunk {i}/{len(chunks)}...")

            # Try LLM extraction first
            raw_transactions = self.llm_extractor.extract(chunk)

            # Validate against source text
            validated = self.validator.validate(raw_transactions, chunk)

            # Fallback to regex if LLM found nothing and fallback is enabled
            if len(validated) == 0 and self.settings.enable_regex_fallback:
                logger.info("LLM found no transactions, trying regex fallback...")
                regex_transactions = self.regex_extractor.extract(chunk)
                validated = self.validator.validate(regex_transactions, chunk)

                if len(validated) > 0:
                    logger.info(f"Regex fallback extracted {len(validated)} transactions")

            all_transactions.extend(validated)

        logger.info(f"Total validated transactions: {len(all_transactions)}")
        return all_transactions

    def _apply_filters(self, transactions: List[Transaction]) -> List[Transaction]:
        """
        Apply chain of filters to remove unwanted transactions.

        Args:
            transactions: List of transactions to filter

        Returns:
            Filtered list of transactions
        """
        logger.info("Applying filters...")

        filtered = transactions
        for filter_obj in self.filters:
            filtered = filter_obj.filter(filtered)

        logger.info(f"Filtering complete: {len(filtered)}/{len(transactions)} transactions kept")
        return filtered
