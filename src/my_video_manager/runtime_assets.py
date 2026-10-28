"""공식 배포 파일 고정값. 버전 변경 시 URL, SHA-256, 크기를 함께 갱신한다.

CUDA: https://pypi.org/pypi/<package>/<version>/json (Windows x64)
Whisper: https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo/tree/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf
CUDA는 2026-10-15, Whisper는 2026-10-28 확인.
model.bin은 게시된 LFS SHA-256, 나머지는 실제 파일 SHA-256.
"""

from dataclasses import dataclass


def preparation_download_label():
    return f'약 {sum(asset.size for asset in CUDA_WHEELS + WHISPER_FILES) / 1_000_000_000:.1f} GB'


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

WHISPER_MODEL = "large-v3-turbo"
WHISPER_REPOSITORY = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
WHISPER_REVISION = "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
WHISPER_FILES = (
    DownloadAsset('config.json',
                  f'https://huggingface.co/{WHISPER_REPOSITORY}/resolve/{WHISPER_REVISION}/config.json',
                  'b0253ea6c0d3bea6b1e19e91a02acfd3b53f4467362efcb5a3e6b16c9b3a9b7e', 2263),
    DownloadAsset('model.bin',
                  f'https://huggingface.co/{WHISPER_REPOSITORY}/resolve/{WHISPER_REVISION}/model.bin',
                  'e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da', 1617884929),
    DownloadAsset('preprocessor_config.json',
                  f'https://huggingface.co/{WHISPER_REPOSITORY}/resolve/{WHISPER_REVISION}/preprocessor_config.json',
                  '7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711', 340),
    DownloadAsset('tokenizer.json',
                  f'https://huggingface.co/{WHISPER_REPOSITORY}/resolve/{WHISPER_REVISION}/tokenizer.json',
                  '297b13372ac43916285644fb9687add3cc62ee2a1adb60da3dc25cc94c1871fd', 2710337),
    DownloadAsset('vocabulary.json',
                  f'https://huggingface.co/{WHISPER_REPOSITORY}/resolve/{WHISPER_REVISION}/vocabulary.json',
                  'c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1', 1068114),
)
