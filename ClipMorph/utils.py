import os

def delete_file(filepath):
    """Delete a file if it exists."""
    try:
        os.remove(filepath)
        print(f"Deleted file: {filepath}")
    except FileNotFoundError:
        print(f"File not found: {filepath}")
    except Exception as e:
        print(f"Error deleting file {filepath}: {e}")
