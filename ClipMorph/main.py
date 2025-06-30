from clipmorph.cli import parse_args
from clipmorph.convert import convert_to_short_form
from clipmorph.upload_youtube import upload_to_youtube
from clipmorph.upload_instagram import upload_to_instagram
from clipmorph.upload_tiktok import upload_to_tiktok
from clipmorph.utils import delete_file

from dotenv import load_dotenv

def main():
    load_dotenv()
    args = parse_args()

    # Convert video
    output_path = convert_to_short_form(
        input_path=args.input_path,
        include_cam=args.include_cam,
        cam_x=args.cam_x,
        cam_y=args.cam_y,
        cam_width=args.cam_width,
        cam_height=args.cam_height
    )



    # Cleanup if requested
    if getattr(args, 'clean', False):
        delete_file(output_path)

if __name__ == "__main__":
    main()
