import logging
import warnings

from clipmorph.ffmpeg import configure_ffmpeg

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Suppress various library warnings and debug logs BEFORE any heavy imports
warnings.filterwarnings("ignore", category=UserWarning, module="pyannote")
warnings.filterwarnings("ignore", category=UserWarning, module="speechbrain")
warnings.filterwarnings("ignore", category=UserWarning, module="torch")

# Configure root logger first to catch early messages
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Suppress specific library loggers
logging.getLogger("speechbrain").setLevel(logging.ERROR)
logging.getLogger("pyannote").setLevel(logging.ERROR)
logging.getLogger("torch").setLevel(logging.ERROR)
logging.getLogger("speechbrain.utils.torch_audio_backend").setLevel(
    logging.ERROR)
logging.getLogger("speechbrain.utils.checkpoints").setLevel(logging.ERROR)
logging.getLogger("speechbrain.core").setLevel(logging.ERROR)
logging.getLogger("speechbrain.utils.parameter_transfer").setLevel(
    logging.ERROR)

# Disable debug messages from speechbrain entirely
logging.getLogger("speechbrain").propagate = False

configure_ffmpeg()
