"""SmartSplit - download source videos (YouTube/Twitch) and turn long landscape
videos into vertical 9:16 clips with face tracking and burned-in subtitles."""

import logging
import warnings

# Keep output clean: silence numpy (matmul) and Hugging Face Hub warnings.
warnings.filterwarnings("ignore")
for _name in ("faster_whisper", "huggingface_hub"):
    logging.getLogger(_name).setLevel(logging.ERROR)

try:
    import numpy as _np
    _np.seterr(all="ignore")
except ImportError:
    pass

__version__ = "0.2.0"
