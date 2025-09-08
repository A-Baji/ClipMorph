import logging
import os
import warnings

# Suppress various library warnings and debug logs BEFORE any heavy imports
warnings.filterwarnings("ignore", category=UserWarning, module="pyannote")
warnings.filterwarnings("ignore", category=UserWarning, module="speechbrain") 
warnings.filterwarnings("ignore", category=UserWarning, module="torch")

# Suppress specific library loggers
logging.getLogger("speechbrain").setLevel(logging.ERROR)
logging.getLogger("pyannote").setLevel(logging.ERROR)
logging.getLogger("torch").setLevel(logging.ERROR)
logging.getLogger("speechbrain.utils.torch_audio_backend").setLevel(logging.ERROR)

from dotenv import load_dotenv
from clipmorph.cli import parse_args


def _determine_enabled_platforms(args):
    """Determine which platforms should be enabled based on CLI arguments."""
    all_platforms = {
        'youtube_enabled': True,
        'instagram_enabled': True, 
        'tiktok_enabled': True,
        'twitter_enabled': True
    }
    
    # If --upload-to is specified, only enable those platforms
    if getattr(args, 'upload_to', None):
        all_platforms = {f'{platform}_enabled': False for platform in ['youtube', 'instagram', 'tiktok', 'twitter']}
        for platform in args.upload_to:
            all_platforms[f'{platform}_enabled'] = True
    
    # If --skip is specified, disable those platforms
    elif getattr(args, 'skip', None):
        for platform in args.skip:
            all_platforms[f'{platform}_enabled'] = False
    
    return all_platforms


def main():
    load_dotenv()
    args = parse_args()

    input_path = getattr(args, "input_path")

    pipeline_args = vars(args).copy()
    no_confirm = pipeline_args.pop("no_confirm", False)
    clean = pipeline_args.pop("clean", False)

    # Lazy import heavy dependencies only when needed
    from clipmorph.conversion_pipeline import ConversionPipeline
    
    pipeline_args.pop("input_path", None)
    final_output = ConversionPipeline(input_path, **pipeline_args).run()

    # Check if upload should be skipped
    if getattr(args, 'no_upload', False):
        print("Upload skipped (--no-upload flag).")
        return
    
    # Determine enabled platforms
    enabled_platforms = _determine_enabled_platforms(args)
    if not enabled_platforms:
        print("No platforms selected for upload.")
        return
    
    # Confirm upload
    if not no_confirm:
        platform_list = ", ".join(enabled_platforms.keys())
        confirm = input(f"\nUpload to {platform_list}? (y/n): ").strip().lower()
        if confirm != 'y':
            logging.info("Aborted upload.")
            return

    # Upload to selected platforms in parallel
    print("\n" + "=" * 60)
    print(f"Starting parallel uploads to {len(enabled_platforms)} platforms...")
    print("=" * 60)

    # Lazy import upload pipeline only when needed
    from clipmorph.upload_pipeline import UploadPipeline
    
    upload_pipeline = UploadPipeline(**enabled_platforms)
    
    # Prepare upload parameters from args  
    upload_args = vars(args).copy()
    upload_args.pop("input_path", None)
    upload_args.pop("no_confirm", None)
    upload_args.pop("clean", None)
    upload_args.pop("no_upload", None)
    upload_args.pop("upload_to", None)
    upload_args.pop("skip", None)
    upload_args.pop("config", None)
    
    # Add platform overrides
    upload_args.update(args.platform_overrides)
    
    # Set defaults for common parameters
    upload_args.setdefault('title', 'Short Form Content')
    upload_args.setdefault('description', 'Generated content') 
    upload_args.setdefault('tags', ['gaming', 'content', 'video', 'social'])
    
    upload_results = upload_pipeline.run(
        video_path=final_output,
        **upload_args
    )

    # Summary of results
    print("\n" + "=" * 60)
    print("Upload Results Summary:")
    print("=" * 60)
    successful_uploads = 0
    for platform, result in upload_results.items():
        if result['success']:
            successful_uploads += 1
            print(f"✓ {platform}: Success - {result['result']}")
        else:
            print(f"✗ {platform}: Failed - {result['error']}")

    print(
        f"\nCompleted: {successful_uploads}/{len(upload_results)} platforms successful"
    )
    print("=" * 60)

    # Cleanup if requested
    if clean:
        try:
            os.remove(final_output)
            logging.debug(f"Deleted file: {final_output}")
        except FileNotFoundError:
            logging.warning(f"File not found: {final_output}")
        except Exception as e:
            logging.error(f"Error deleting file {final_output}: {e}")


if __name__ == "__main__":
    main()
