import os
import logging


def delete_file(filepath):
    """Delete a file if it exists."""
    try:
        os.remove(filepath)
        logging.debug(f"Deleted file: {filepath}")
    except FileNotFoundError:
        logging.warning(f"File not found: {filepath}")
    except Exception as e:
        logging.error(f"Error deleting file {filepath}: {e}")
