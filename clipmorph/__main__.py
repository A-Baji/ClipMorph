import logging
import os

from dotenv import load_dotenv

from clipmorph.cli import parse_args_with_parser
from clipmorph.cli import separate_args_by_category
from clipmorph.ffmpeg import configure_ffmpeg  # Add this import
from clipmorph.job import JobManifest


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


def _run_preflight(args, enabled_platforms, ffmpeg_runner):
    from clipmorph.preflight import PreflightValidator

    warnings = PreflightValidator(ffmpeg_runner).validate(
        input_path=args.input_path,
        output_dir=args.output_dir,
        no_conversion=args.no_conversion,
        no_upload=args.no_upload,
        enabled_platforms=enabled_platforms,
        title=args.title,
        cam_x=args.cam_x,
        cam_y=args.cam_y,
        cam_width=args.cam_width,
        cam_height=args.cam_height,
        platform_overrides=args.platform_overrides)
    for warning in warnings:
        logging.warning("Preflight: %s", warning)
    return warnings


def main():
    load_dotenv()

    # Parse arguments and get both args and parser for automatic separation
    args, parser = parse_args_with_parser()

    # --help and --init do not need media-processing dependencies.
    if args is None:
        return

    # Configure FFmpeg only when a conversion or upload workflow is requested.
    configure_ffmpeg()

    # Extract main control arguments
    no_confirm = getattr(args, "no_confirm", False)
    clean = getattr(args, "clean", False)
    no_conversion = getattr(args, "no_conversion", False)
    no_upload = getattr(args, "no_upload", False)
    upload_to = getattr(args, "upload_to", None)
    skip = getattr(args, "skip", None)
    enabled_platforms = _determine_enabled_platforms(upload_to, skip)

    from clipmorph.ffmpeg import FFmpegRunner
    ffmpeg_runner = FFmpegRunner()
    _run_preflight(args, enabled_platforms, ffmpeg_runner)
    if args.dry_run:
        print("Preflight passed. No conversion or upload was performed.")
        return

    configuration = {key: value for key, value in vars(args).items()
                     if key not in {'input_path', 'resume'}}
    if args.resume:
        manifest = JobManifest.load(args.resume)
        if manifest.source_path != os.path.abspath(args.input_path):
            raise ValueError("Resume job source does not match input_path")
    else:
        manifest = JobManifest.create(args.input_path, configuration)
    manifest.set_status("preflighted")

    # Automatically separate conversion and upload args based on argument groups
    conversion_args, upload_args = separate_args_by_category(args, parser)
    conversion_args['strict'] = args.strict

    # Handle conversion or direct upload
    if args.resume and manifest.artifact_path and os.path.exists(
            manifest.artifact_path):
        conversion_output = manifest.artifact_path
        logging.info("Resuming from existing artifact: %s", conversion_output)
    elif no_conversion:
        # Use input video directly
        conversion_output = conversion_args['input_path']
        manifest.set_artifact(conversion_output)
        print(
            f"Skipping conversion, using input video directly: {conversion_output}"
        )
    else:
        # Lazy import heavy dependencies only when needed
        from clipmorph.conversion_pipeline import ConversionPipeline

        # Add no_confirm to conversion_args so the pipeline can access it
        conversion_args['no_confirm'] = no_confirm

        manifest.set_status("converting")
        conversion_pipeline = ConversionPipeline(**conversion_args)
        conversion_output = conversion_pipeline.run()
        manifest.set_artifact(conversion_output)
        for warning in conversion_pipeline.warnings:
            logging.warning("Conversion warning: %s", warning)

    # Check if upload should be skipped
    if no_upload:
        manifest.set_status("completed")
        print("Upload skipped (--no-upload flag).")
        return

    completed_platforms = {
        platform.lower()
        for platform, result in manifest.platforms.items()
        if result.get("success")
    }
    enabled_platforms = [platform for platform in enabled_platforms
                         if platform not in completed_platforms]
    if not enabled_platforms:
        manifest.set_status("published")
        print("All requested platforms are already complete for this job.")
        return

    # Determine enabled platforms
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
        manifest.record_platform(platform, result)
        if result['success']:
            successful_uploads += 1
            print(f"✓ {platform}: Success - {result['result']}")
        else:
            print(f"✗ {platform}: Failed - {result['error']}")

    print(
        f"\nCompleted: {successful_uploads}/{len(upload_results)} platforms successful"
    )
    print("=" * 60)

    if successful_uploads != len(upload_results):
        raise SystemExit(1)

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
