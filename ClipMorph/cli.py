# Handles CLI argument parsing, user prompts, and workflow orchestration

import argparse
import json
from pathlib import Path


def parse_args_with_parser():
    """Parse arguments and return both args and parser for automatic categorization."""
    parser = _create_parser()
    args = parser.parse_args()

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
    parser.add_argument("input_path", help="Path to the input video file.")
    parser.add_argument("--no-confirm",
                        "-y",
                        action="store_true",
                        help="Bypass upload confirmation prompt.")
    parser.add_argument("--clean",
                        "-c",
                        action="store_true",
                        help="Delete output video after upload.")

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
        'input_path', 'no_confirm', 'clean', 'no_upload', 'upload_to', 'skip'
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
