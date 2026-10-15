"""공식 배포 파일 고정값. 버전 변경 시 URL, SHA-256, 크기를 함께 갱신한다.

CUDA: https://pypi.org/pypi/<package>/<version>/json (Windows x64)
Whisper: https://huggingface.co/Systran/faster-whisper-large-v3/tree/edaa852ec7e145841d8ffdb056a99866b5f0a478
2026-10-15 확인. model.bin은 게시된 LFS SHA-256, 나머지는 실제 파일 SHA-256.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DownloadAsset:
    name: str
    url: str
    sha256: str
    size: int


CUDA_WHEELS = (
    DownloadAsset('nvidia_cublas_cu12-12.8.4.1-py3-none-win_amd64.whl',
                  'https://files.pythonhosted.org/packages/70/61/7d7b3c70186fb651d0fbd35b01dbfc8e755f69fd58f817f3d0f642df20c3/nvidia_cublas_cu12-12.8.4.1-py3-none-win_amd64.whl',
                  '47e9b82132fa8d2b4944e708049229601448aaad7e6f296f630f2d1a32de35af', 567544208),
    DownloadAsset('nvidia_cudnn_cu12-9.8.0.87-py3-none-win_amd64.whl',
                  'https://files.pythonhosted.org/packages/39/6a/5e9910b2b2c9dcddee9aaef372b3db0f08b9f7eaf1d462f859461a79caf9/nvidia_cudnn_cu12-9.8.0.87-py3-none-win_amd64.whl',
                  'b4b5cfddc32aa4180f9d390ee99e9a9f55a89e7087329b41aba4319327e22466', 684630375),
)

WHISPER_REVISION = "edaa852ec7e145841d8ffdb056a99866b5f0a478"
WHISPER_FILES = (
    DownloadAsset('config.json',
                  'https://huggingface.co/Systran/faster-whisper-large-v3/resolve/edaa852ec7e145841d8ffdb056a99866b5f0a478/config.json',
                  'a9306624f5ec14270a014b647e5c316b6e03a662c369758d1b90697a7b0655b9', 2394),
    DownloadAsset('model.bin',
                  'https://huggingface.co/Systran/faster-whisper-large-v3/resolve/edaa852ec7e145841d8ffdb056a99866b5f0a478/model.bin',
                  '69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1', 3087284237),
    DownloadAsset('preprocessor_config.json',
                  'https://huggingface.co/Systran/faster-whisper-large-v3/resolve/edaa852ec7e145841d8ffdb056a99866b5f0a478/preprocessor_config.json',
                  '7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711', 340),
    DownloadAsset('tokenizer.json',
                  'https://huggingface.co/Systran/faster-whisper-large-v3/resolve/edaa852ec7e145841d8ffdb056a99866b5f0a478/tokenizer.json',
                  '6d8cbd7cd0d8d5815e478dac67b85a26bbe77c1f5e0c6d76d1ce2abc0e5f21ca', 2480617),
    DownloadAsset('vocabulary.json',
                  'https://huggingface.co/Systran/faster-whisper-large-v3/resolve/edaa852ec7e145841d8ffdb056a99866b5f0a478/vocabulary.json',
                  'c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1', 1068114),
)
