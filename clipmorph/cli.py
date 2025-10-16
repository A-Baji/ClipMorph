# Handles CLI argument parsing, user prompts, and workflow orchestration

import argparse
import json
from pathlib import Path
import shutil

import yaml


def create_config_template(output_path=None):
    """Create a template YAML configuration file."""
    template = {
        "general": {
            "no_confirm":
            False,  # Bypass subtitles and upload confirmation prompt
            "clean": False,  # Delete output video after upload
            "no_conversion":
            False  # Skip conversion and upload input video directly
        },
        "conversion": {
            "no_cam": False,  # Exclude the camera feed from the output
            "camera": {
                "x": 20,  # Top left x coordinate of camera feed
                "y": 20,  # Top left y coordinate of camera feed
                "width": 320,  # Width in pixels of camera feed
                "height": 240  # Height in pixels of camera feed
            },
            "output_dir":
            "output",  # Custom output directory for processed videos
            "no_subs": False  # Skip transcription and subtitle generation
        },
        "upload": {
            "no_upload": False,  # Skip all uploads
            "upload_to": [],  # List of platforms to upload to (empty = all)
            "skip": []  # List of platforms to skip
        },
        "content": {
            "title": "",  # Title/caption for the content
            "description": "",  # Description for the content
            "tags": []  # List of tags/keywords
        },
        "platforms": {
            "youtube": {
                "category": "20",  # Gaming category
                "privacy_status": "unlisted"  # public, unlisted, or private
            },
            "instagram": {
                "share_to_feed":
                False,  # Don't share to main feed (story only)
                "thumb_offset": 3000  # Thumbnail at 3 seconds
            },
            "tiktok": {
                "privacy_level":
                "MUTUAL_FOLLOW_FRIENDS"  # PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS, or SELF_ONLY
            },
            "twitter": {
            }  # Twitter uses account-level privacy, no platform-specific options currently
        }
    }

    # If no output path specified, use default
    if not output_path:
        output_path = Path.cwd() / "clipmorph.yaml"
    else:
        output_path = Path(output_path)

    # Check if file already exists
    if output_path.exists():
        backup_path = output_path.with_suffix(output_path.suffix + ".backup")
        shutil.copy2(output_path, backup_path)
        print(f"Existing config file backed up to: {backup_path}")

    # Write the template with comments preserved
    with open(output_path, 'w') as f:
        yaml.dump(template, f, sort_keys=False, default_flow_style=False)
        print(f"Created config template at: {output_path}")


def parse_args_with_parser():
    """Parse arguments and return both args and parser for automatic categorization."""
    parser = _create_parser()
    args = parser.parse_args()

    # Handle init command
    if args.init:
        create_config_template(args.config_path)
        return None, parser

    # Validate required args for normal operation
    if not args.input_path:
        parser.error("input_path is required unless --init is specified")

    if not args.no_upload and not args.title:
        parser.error("--title is required unless --no-upload is specified")

    # Process platform overrides
    args.platform_overrides = _process_platform_overrides(args)

    # Process tags
    if args.tags:
        args.tags = [tag.strip() for tag in args.tags.split(',')]

    return args, parser


def _create_parser():
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description="Convert and upload a video to short-form platforms.")

    # Input and basic options (neither conversion nor upload specific)
    parser.add_argument("input_path",
                        nargs='?',
                        help="Path to the input video file.")
    parser.add_argument(
        "--init",
        action="store_true",
        help="Create a template configuration file in the current directory.")
    parser.add_argument(
        "--config-path",
        type=str,
        help="Custom path for the generated config file when using --init.")
    parser.add_argument(
        "--no-confirm",
        "-y",
        action="store_true",
        help="Bypass subtitles and upload confirmation prompt.")
    parser.add_argument("--clean",
                        "-c",
                        action="store_true",
                        help="Delete output video after upload.")
    parser.add_argument(
        "--no-conversion",
        action="store_true",
        help="Skip conversion and upload input video directly.")

    # Conversion pipeline options
    conversion_group = parser.add_argument_group('Conversion Options')
    conversion_group.add_argument(
        "--no-cam",
        dest="include_cam",
        action="store_false",
        help="Exclude the camera feed from the output.")
    conversion_group.add_argument("--cam-x",
                                  type=int,
                                  default=1420,
                                  help="Top left x coordinate of camera feed.")
    conversion_group.add_argument("--cam-y",
                                  type=int,
                                  default=790,
                                  help="Top left y coordinate of camera feed.")
    conversion_group.add_argument("--cam-width",
                                  type=int,
                                  default=480,
                                  help="Width in pixels of camera feed.")
    conversion_group.add_argument("--cam-height",
                                  type=int,
                                  default=270,
                                  help="Height in pixels of camera feed.")
    conversion_group.add_argument(
        "--output-dir",
        type=str,
        default="output/",
        help="Custom output directory for the processed video.")
    conversion_group.add_argument(
        "--no-subs",
        action="store_true",
        help="Skip transcription and subtitle generation entirely.")

    # Upload control options
    upload_group = parser.add_argument_group('Upload Control')
    upload_group.add_argument("--no-upload",
                              action="store_true",
                              help="Skip all uploads.")
    upload_group.add_argument(
        "--upload-to",
        nargs="+",
        choices=["youtube", "instagram", "tiktok", "twitter"],
        help="Only upload to specified platforms.")
    upload_group.add_argument(
        "--skip",
        nargs="+",
        choices=["youtube", "instagram", "tiktok", "twitter"],
        help="Skip specified platforms.")

    # Common upload parameters
    content_group = parser.add_argument_group('Content Options')
    content_group.add_argument("--title",
                               required=True,
                               type=str,
                               help="Title/caption for the content.")
    content_group.add_argument("--description",
                               type=str,
                               help="Description for the content.")
    content_group.add_argument("--tags",
                               type=str,
                               help="Comma-separated tags/keywords.")

    # Platform overrides
    override_group = parser.add_argument_group('Platform Overrides')
    override_group.add_argument(
        "--config",
        type=str,
        help="Path to YAML/JSON config file with platform overrides.")
    override_group.add_argument(
        "--platform-overrides",
        type=str,
        help="JSON string with platform-specific overrides.")

    return parser


def parse_args():
    """Parse command line arguments."""
    parser = _create_parser()
    args = parser.parse_args()

    # Handle init command
    if args.init:
        create_config_template(args.config_path)
        return None

    # Validate required args for normal operation
    if not args.input_path:
        parser.error("input_path is required unless --init is specified")

    if not args.no_upload and not args.title:
        parser.error("--title is required unless --no-upload is specified")

    # Process platform overrides
    args.platform_overrides = _process_platform_overrides(args)

    # Process tags
    if args.tags:
        args.tags = [tag.strip() for tag in args.tags.split(',')]

    return args


def separate_args_by_category(args, parser):
    """
    Automatically separate arguments into conversion and upload categories
    based on their argument group assignments.
    """
    # Get argument groups and their arguments
    conversion_args = set()
    upload_args = set()

    for group in parser._action_groups:
        group_title = group.title
        if 'Conversion' in group_title:
            # Add all arguments from conversion group
            for action in group._group_actions:
                # Use dest attribute which is the actual argument name stored in args
                if action.dest and action.dest != 'help':
                    conversion_args.add(action.dest)
        elif group_title in [
                'Upload Control', 'Content Options', 'Platform Overrides'
        ]:
            # Add all arguments from upload-related groups
            for action in group._group_actions:
                # Use dest attribute which is the actual argument name stored in args
                if action.dest and action.dest != 'help':
                    upload_args.add(action.dest)

    # Special handling for positional arguments and main control args
    main_control_args = {
        'input_path', 'no_confirm', 'clean', 'no_conversion', 'no_upload',
        'upload_to', 'skip'
    }
    conversion_args.add('input_path')  # input_path goes to conversion

    # Separate the actual argument values
    args_dict = vars(args)
    conversion_dict = {}
    upload_dict = {}

    for key, value in args_dict.items():
        if key in conversion_args:
            conversion_dict[key] = value
        elif key in upload_args:
            upload_dict[key] = value
        # Main control args are handled separately in main()

    return conversion_dict, upload_dict


def _process_platform_overrides(args):
    """Process platform overrides from config file or JSON string."""
    overrides = {}

    # Load from config file if provided
    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            with open(config_path, 'r') as f:
                if config_path.suffix.lower() in ['.yml', '.yaml']:
                    try:
                        import yaml
                        config_data = yaml.safe_load(f)
                    except ImportError:
                        raise ImportError(
                            "PyYAML is required for YAML config files. Install with: pip install pyyaml"
                        )
                else:  # JSON
                    config_data = json.load(f)

                # Extract platform overrides from config
                if 'platforms' in config_data:
                    overrides.update(config_data['platforms'])
                elif any(platform in config_data for platform in
                         ['youtube', 'instagram', 'tiktok', 'twitter']):
                    # Direct platform config at root level
                    overrides.update(config_data)

    # Load from JSON string if provided (takes precedence over config file)
    if hasattr(args, 'platform_overrides') and args.platform_overrides:
        try:
            json_overrides = json.loads(args.platform_overrides)
            overrides.update(json_overrides)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in --platform-overrides: {e}")

    # Flatten the nested structure to the {platform}_{parameter} format expected by upload pipeline
    flattened = {}
    for platform, params in overrides.items():
        if isinstance(params, dict):
            for param, value in params.items():
                flattened[f"{platform}_{param}"] = value

    return flattened

    return flattened
