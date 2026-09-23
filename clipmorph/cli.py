# Handles CLI argument parsing, user prompts, and workflow orchestration

import argparse
import json
from pathlib import Path
import shutil

import yaml


SUPPORTED_PLATFORMS = {'youtube', 'instagram', 'tiktok', 'twitter'}
CONFIG_SECTIONS = {'general', 'conversion', 'upload', 'content', 'platforms'}


def build_platform_default_config():
    """Return the canonical platform defaults shared by runtime logic and examples."""
    return {
        'youtube': {
            'category': '22',
            'privacy_status': 'public',
        },
        'instagram': {
            'share_to_feed': True,
            'thumb_offset': 0,
        },
        'tiktok': {
            'privacy_level': 'PUBLIC_TO_EVERYONE',
        },
        'twitter': {},
    }


def summarize_runtime_configuration(runtime_values=None):
    """Merge runtime overrides with canonical defaults for display and dry-run output."""
    defaults = build_platform_default_config()
    runtime_values = runtime_values or {}

    for key, value in runtime_values.items():
        if not isinstance(key, str):
            continue
        if key.startswith('youtube_'):
            defaults['youtube'][key[len('youtube_'):]] = value
        elif key.startswith('instagram_'):
            defaults['instagram'][key[len('instagram_'):]] = value
        elif key.startswith('tiktok_'):
            defaults['tiktok'][key[len('tiktok_'):]] = value
        elif key.startswith('twitter_'):
            defaults.setdefault('twitter', {})[key[len('twitter_'):]] = value

    return defaults


def _load_config_data(config_path):
    """Load and validate the supported YAML/JSON configuration shape."""
    if not config_path:
        return {}

    path = Path(config_path)
    if not path.exists():
        raise ValueError(f"Configuration file does not exist: {path}")

    try:
        with open(path, 'r', encoding='utf-8') as config_file:
            data = (yaml.safe_load(config_file)
                    if path.suffix.lower() in {'.yml', '.yaml'} else
                    json.load(config_file))
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as error:
        raise ValueError(f"Unable to read configuration file {path}: {error}")

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Configuration root must be an object")

    unknown_sections = set(data) - CONFIG_SECTIONS
    if unknown_sections:
        raise ValueError(
            f"Unknown configuration section(s): {', '.join(sorted(unknown_sections))}"
        )
    return data


def _flatten_config_values(config):
    """Convert the documented nested configuration into CLI destinations."""
    values = {}
    values.update(config.get('general', {}))
    values.update(config.get('upload', {}))
    values.update(config.get('content', {}))

    conversion = config.get('conversion', {})
    if conversion:
        values.update({key: value for key, value in conversion.items()
                       if key != 'camera'})
        camera = conversion.get('camera', {})
        for key in ('x', 'y', 'width', 'height'):
            if key in camera:
                values[f'cam_{key}'] = camera[key]
        if 'no_cam' in conversion:
            values['include_cam'] = not conversion['no_cam']

    platforms = config.get('platforms', {})
    if not isinstance(platforms, dict):
        raise ValueError("Configuration 'platforms' must be an object")
    unknown_platforms = set(platforms) - SUPPORTED_PLATFORMS
    if unknown_platforms:
        raise ValueError(
            f"Unknown platform(s): {', '.join(sorted(unknown_platforms))}")
    for platform, params in platforms.items():
        if not isinstance(params, dict):
            raise ValueError(f"Configuration for {platform} must be an object")
        for param, value in params.items():
            values[f'{platform}_{param}'] = value

    return values


def _apply_config_defaults(args):
    """Apply config values only where the corresponding CLI option is absent."""
    config_values = _flatten_config_values(_load_config_data(
        getattr(args, 'config', None)))
    for key, value in config_values.items():
        if not hasattr(args, key):
            setattr(args, key, value)

    defaults = {
        'no_confirm': False,
        'clean': False,
        'no_conversion': False,
        'dry_run': False,
        'strict': False,
        'resume': None,
        'include_cam': True,
        'cam_x': 1420,
        'cam_y': 790,
        'cam_width': 480,
        'cam_height': 270,
        'output_dir': 'output/',
        'no_subs': False,
        'no_upload': False,
        'upload_to': None,
        'skip': None,
        'title': None,
        'description': None,
        'tags': None,
        'platform_overrides': None,
    }
    for key, value in defaults.items():
        if not hasattr(args, key):
            setattr(args, key, value)

    return args


def create_config_template(output_path=None):
    """Create a template YAML configuration file."""
    platform_defaults = build_platform_default_config()
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
            "no_subs": False,  # Skip transcription and subtitle generation
            "transcription_language": "en",  # Whisper language code or auto
            "transcription_model": "large-v3",  # Whisper model size
            "transcription_device": "auto",  # auto, cpu, cuda, or mps
            "transcription_compute_type": "float16"  # float16/int8/float32 for runtime compatibility
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
        "platforms": platform_defaults,
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
    if getattr(args, 'init', False):
        create_config_template(args.config_path)
        return None, parser

    # Validate required args for normal operation
    args = _apply_config_defaults(args)

    if not getattr(args, 'input_path', None):
        parser.error("input_path is required unless --init is specified")

    # Title is only required if uploading
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
        description="Convert and upload a video to short-form platforms.",
        argument_default=argparse.SUPPRESS)

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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the planned run without converting or uploading.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when optional transcription or subtitle processing fails.")
    parser.add_argument(
        "--resume",
        metavar="JOB_ID",
        help="Resume a previous job manifest by ID.")

    # Conversion pipeline options
    conversion_group = parser.add_argument_group('Conversion Options')
    conversion_group.add_argument(
        "--no-cam",
        dest="include_cam",
        action="store_false",
        help="Exclude the camera feed from the output.")
    conversion_group.add_argument("--cam-x",
                                  type=int,
                                  help="Top left x coordinate of camera feed.")
    conversion_group.add_argument("--cam-y",
                                  type=int,
                                  help="Top left y coordinate of camera feed.")
    conversion_group.add_argument("--cam-width",
                                  type=int,
                                  help="Width in pixels of camera feed.")
    conversion_group.add_argument("--cam-height",
                                  type=int,
                                  help="Height in pixels of camera feed.")
    conversion_group.add_argument(
        "--output-dir",
        type=str,
        help="Custom output directory for the processed video.")
    conversion_group.add_argument(
        "--no-subs",
        action="store_true",
        help="Skip transcription and subtitle generation entirely.")
    conversion_group.add_argument(
        "--transcription-language",
        default="en",
        help="Whisper language code to use for transcription, or 'auto'.")
    conversion_group.add_argument(
        "--transcription-model",
        default="large-v3",
        help="Whisper model to use: tiny, base, small, medium, large, large-v3.")
    conversion_group.add_argument(
        "--transcription-device",
        default="auto",
        choices=["auto", "cpu", "cuda", "mps"],
        help="Transcription device to prefer for Whisper inference.")
    conversion_group.add_argument(
        "--transcription-compute-type",
        default="float16",
        choices=["float16", "float32", "int8"],
        help="Runtime compute type to use when the selected model supports it.")

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
    content_group.add_argument(
        "--title",
        type=str,  # Removed required=True
        help="Title/caption for the content (required unless --no-upload).")
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
    if getattr(args, 'init', False):
        create_config_template(args.config_path)
        return None

    # Validate required args for normal operation
    args = _apply_config_defaults(args)

    if not getattr(args, 'input_path', None):
        parser.error("input_path is required unless --init is specified")

    # Title is only required if uploading
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

    config_data = _load_config_data(getattr(args, 'config', None))
    if 'platforms' in config_data:
        overrides.update(config_data['platforms'])

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
