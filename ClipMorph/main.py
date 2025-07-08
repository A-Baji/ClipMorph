from clipmorph.cli import parse_args
from clipmorph.convert import convert_to_short_form
from clipmorph.platforms.youtube.upload import upload_to_youtube
from clipmorph.platforms.instagram.upload import upload_to_instagram
from clipmorph.platforms.tiktok.upload import upload_to_tiktok
from clipmorph.utils import delete_file

from dotenv import load_dotenv
import logging


def main():
    load_dotenv()
    args = parse_args()

    logging.info("Converting video to short-form format...")
    output_path = convert_to_short_form(input_path=args.input_path,
                                        include_cam=args.include_cam,
                                        cam_x=args.cam_x,
                                        cam_y=args.cam_y,
                                        cam_width=args.cam_width,
                                        cam_height=args.cam_height)
    logging.info(f"Saved converted video to {output_path}")

    # Confirm upload
    if not getattr(args, 'no_confirm', False):
        confirm = input("\nUpload to all platforms? (y/n): ").strip().lower()
        if confirm != 'y':
            logging.info("Aborted upload.")
            return

    # Upload to all platforms
    print("----------------")
    upload_to_youtube(output_path)
    print("----------------")
    upload_to_instagram(output_path)
    print("----------------")
    upload_to_tiktok(output_path)

    # Cleanup if requested
    if getattr(args, 'clean', False):
        delete_file(output_path)


if __name__ == "__main__":
    main()
