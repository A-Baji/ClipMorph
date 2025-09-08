import logging
import os
import warnings

from dotenv import load_dotenv

# Suppress various library warnings and debug logs
warnings.filterwarnings("ignore", category=UserWarning, module="pyannote")
warnings.filterwarnings("ignore", category=UserWarning, module="speechbrain")
warnings.filterwarnings("ignore", category=UserWarning, module="torch")

# Suppress specific library loggers
logging.getLogger("speechbrain").setLevel(logging.ERROR)
logging.getLogger("pyannote").setLevel(logging.ERROR)
logging.getLogger("torch").setLevel(logging.ERROR)

from clipmorph.cli import parse_args
from clipmorph.conversion_pipeline import ConversionPipeline
from clipmorph.upload_pipeline import UploadPipeline


def main():
    load_dotenv()
    args = parse_args()

    input_path = getattr(args, "input_path")

    pipeline_args = vars(args).copy()
    no_confirm = pipeline_args.pop("no_confirm", False)
    clean = pipeline_args.pop("clean", False)

    pipeline_args.pop("input_path", None)
    final_output = ConversionPipeline(input_path, **pipeline_args).run()

    # Confirm upload
    if not getattr(args, 'no_confirm', False):
        confirm = input("\nUpload to all platforms? (y/n): ").strip().lower()
        if confirm != 'y':
            logging.info("Aborted upload.")
            return

    # Upload to all platforms
    # print("----------------")
    # upload_to_youtube(final_output)
    # print("----------------")
    # upload_to_instagram(final_output)
    # print("----------------")
    # upload_to_tiktok(final_output)
    # print("----------------")
    # upload_to_twitter(final_output)

    # Cleanup if requested
    if getattr(args, 'clean', False):
        try:
            os.remove(final_output)
            logging.debug(f"Deleted file: {final_output}")
        except FileNotFoundError:
            logging.warning(f"File not found: {final_output}")
        except Exception as e:
            logging.error(f"Error deleting file {final_output}: {e}")


if __name__ == "__main__":
    main()
