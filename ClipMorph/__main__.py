import logging
import os

from dotenv import load_dotenv

from clipmorph.cli import parse_args_with_parser
from clipmorph.cli import separate_args_by_category


def _determine_enabled_platforms(upload_to, skip):
    """Determine which platforms should be enabled based on CLI arguments."""
    enabled_platforms = ['youtube', 'instagram', 'tiktok', 'twitter']

    # If --upload-to is specified, only enable those platforms
    if upload_to:
        return upload_to

    # If --skip is specified, disable those platforms
    elif skip:
        for platform in skip:
            enabled_platforms.remove(platform)

    return enabled_platforms


def main():
    load_dotenv()

    # Parse arguments and get both args and parser for automatic separation
    args, parser = parse_args_with_parser()

    # Extract main control arguments
    no_confirm = getattr(args, "no_confirm", False)
    clean = getattr(args, "clean", False)
    no_conversion = getattr(args, "no_conversion", False)
    no_upload = getattr(args, "no_upload", False)
    upload_to = getattr(args, "upload_to", None)
    skip = getattr(args, "skip", None)

    # Automatically separate conversion and upload args based on argument groups
    conversion_args, upload_args = separate_args_by_category(args, parser)

    # Handle conversion or direct upload
    if no_conversion:
        # Use input video directly
        conversion_output = conversion_args['input_path']
        print(
            f"Skipping conversion, using input video directly: {conversion_output}"
        )
    else:
        # Lazy import heavy dependencies only when needed
        from clipmorph.conversion_pipeline import ConversionPipeline

        # Add no_confirm to conversion_args so the pipeline can access it
        conversion_args['no_confirm'] = no_confirm

        conversion_output = ConversionPipeline(**conversion_args).run()

    # Check if upload should be skipped
    if no_upload:
        print("Upload skipped (--no-upload flag).")
        return

    # Determine enabled platforms
    enabled_platforms = _determine_enabled_platforms(upload_to, skip)
    if not enabled_platforms:
        print("No platforms selected for upload.")
        return

    # Confirm upload
    if not no_confirm and not no_conversion:
        platform_list = ", ".join(enabled_platforms)
        confirm = input(
            f"\nUpload to {platform_list}? (y/n): ").strip().lower()
        if confirm != 'y':
            logging.info("Aborted upload.")
            return

    # Upload to selected platforms in parallel
    print("\n" + "=" * 60)
    print(
        f"Starting parallel uploads to {len(enabled_platforms)} platforms...")
    print("=" * 60)

    # Lazy import upload pipeline only when needed
    from clipmorph.upload_pipeline import UploadPipeline

    upload_pipeline = UploadPipeline(
        **{key: True
           for key in enabled_platforms})

    # Merge platform overrides into upload_args
    if 'platform_overrides' in upload_args and upload_args[
            'platform_overrides']:
        platform_overrides = upload_args.pop('platform_overrides')
        upload_args.update(platform_overrides)

    upload_results = upload_pipeline.run(video_path=conversion_output,
                                         **upload_args)

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

    # Cleanup if requested (but don't delete original input file)
    if clean and not no_conversion:
        try:
            os.remove(conversion_output)
            logging.debug(f"Deleted file: {conversion_output}")
        except FileNotFoundError:
            logging.warning(f"File not found: {conversion_output}")
        except Exception as e:
            logging.error(f"Error deleting file {conversion_output}: {e}")
    elif clean and no_conversion:
        print(
            "Cleanup skipped: cannot delete original input file when using --no-conversion"
        )


if __name__ == "__main__":
    main()
