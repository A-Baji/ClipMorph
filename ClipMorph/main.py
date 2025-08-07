import logging

from dotenv import load_dotenv

from clipmorph.cli import parse_args
from clipmorph.generate_video.pipeline import ConversionPipeline
from clipmorph.platforms.instagram.upload import upload_to_instagram
from clipmorph.platforms.tiktok.upload import upload_to_tiktok
from clipmorph.platforms.twitter.upload import upload_to_twitter
from clipmorph.platforms.youtube.upload import upload_to_youtube
from clipmorph.utils import delete_file


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
        delete_file(final_output)


if __name__ == "__main__":
    main()
