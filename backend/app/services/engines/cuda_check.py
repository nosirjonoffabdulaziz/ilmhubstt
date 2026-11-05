"""GPU sinovi — alohida jarayonda ishga tushiriladi (yiqilsa server yiqilmaydi).
python -m app.services.engines.cuda_check <model_yo'li> <compute_type>"""
import sys

from .cuda_dll import add_nvidia_dll_dirs


def main() -> int:
    add_nvidia_dll_dirs()
    import numpy as np
    from faster_whisper import WhisperModel

    model = WhisperModel(sys.argv[1], device="cuda", compute_type=sys.argv[2])
    segments, _ = model.transcribe(np.zeros(16000 * 2, dtype=np.float32), language="en", beam_size=1,
                                   vad_filter=False, without_timestamps=True)
    list(segments)
    print("CUDA_OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
