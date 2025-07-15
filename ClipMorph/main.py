from clipmorph.cli import parse_args
from clipmorph.generate_video.pipeline import conversion_pipeline
from clipmorph.platforms.youtube.upload import upload_to_youtube
from clipmorph.platforms.instagram.upload import upload_to_instagram
from clipmorph.platforms.tiktok.upload import upload_to_tiktok
from clipmorph.platforms.twitter.upload import upload_to_twitter
from clipmorph.utils import delete_file

from dotenv import load_dotenv
import logging


def main():
    load_dotenv()
    args = parse_args()

    final_output = conversion_pipeline(args)

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
        delete_file(final_output)


if __name__ == "__main__":
    main()
