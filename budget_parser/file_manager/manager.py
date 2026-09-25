"""File management for PDF processing."""

import shutil
from pathlib import Path
from typing import List

from budget_parser.utils.logger import get_logger

logger = get_logger(__name__)


class FileManager:
    """Manages PDF files and folders."""

    def __init__(self, todo_folder: str, done_folder: str):
        """
        Initialize file manager.

        Args:
            todo_folder: Folder containing PDFs to process
            done_folder: Folder for processed PDFs
        """
        self.todo_folder = Path(todo_folder)
        self.done_folder = Path(done_folder)

    def ensure_folders_exist(self):
        """Create necessary folders if they don't exist."""
        self.done_folder.mkdir(parents=True, exist_ok=True)
        self.todo_folder.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Ensured folders exist: {self.todo_folder}, {self.done_folder}")

    def get_pending_pdfs(self) -> List[Path]:
        """
        Get list of PDF files in todo folder.

        Returns:
            List of PDF file paths
        """
        if not self.todo_folder.exists():
            logger.warning(f"Todo folder does not exist: {self.todo_folder}")
            return []

        pdf_files = list(self.todo_folder.glob("*.pdf"))
        logger.info(f"Found {len(pdf_files)} PDF file(s) in {self.todo_folder}")

        return pdf_files

    def move_to_done(self, pdf_path: Path) -> Path:
        """
        Move processed PDF to done folder.

        Args:
            pdf_path: Path to PDF file

        Returns:
            New path in done folder

        Raises:
            FileNotFoundError: If PDF file doesn't exist
            PermissionError: If file cannot be moved
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        # Ensure done folder exists
        self.done_folder.mkdir(parents=True, exist_ok=True)

        # Destination path
        dest_path = self.done_folder / pdf_path.name

        # Handle duplicate filenames
        if dest_path.exists():
            base_name = pdf_path.stem
            suffix = pdf_path.suffix
            counter = 1

            while dest_path.exists():
                dest_path = self.done_folder / f"{base_name}_{counter}{suffix}"
                counter += 1

            logger.warning(f"File already exists, using: {dest_path.name}")

        # Move file
        shutil.move(str(pdf_path), str(dest_path))
        logger.info(f"Moved {pdf_path.name} to {self.done_folder}")

        return dest_path
