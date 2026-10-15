# npm 배포물에서 빠진 원문

`react-remove-scroll-bar@2.3.8`은 npm `package.json`에 MIT를 선언하지만
LICENSE를 싣지 않는다. 공식 저장소의 LICENSE 마지막 변경 커밋
`7301c160fda44cb8cf2b9fdfde61efad35736196`에서 원문을 가져왔다.
`npm view react-remove-scroll-bar@2.3.8 gitHead`의 커밋은 공개 저장소에서
조회되지 않아, 이를 배포 커밋의 원문이라고 주장하지 않는다.

- 출처: https://raw.githubusercontent.com/theKashey/react-remove-scroll-bar/7301c160fda44cb8cf2b9fdfde61efad35736196/LICENSE
- SHA-256: `a79aae0c0f21990d9d963bb3c5a79cdcea9a46f8523ba55c58d7fe776b6ebc84`

`scripts/bundle_licenses.py`는 이 패키지·버전에만 보완본을 적용하고 해시를
검사한다. 다른 버전에도 원문이 없으면 빌드를 중단하므로 출처를 다시 확인한다.
그 밖의 웹 production 의존성은 설치된 npm 패키지의 원문을 그대로 복사한다.

`installer/licenses/GPL-3.0.txt` 출처는 Qt `v6.10.2`의
https://raw.githubusercontent.com/qt/qtbase/v6.10.2/LICENSES/GPL-3.0-only.txt 이며
SHA-256은 `8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903`이다.

## Python 및 추가 원문

CTranslate2 4.8.3 및 tokenizers 0.23.3의 wheel 누락 원문은 공식 고정 태그에서
가져왔다. `PYTHON_SUPPLEMENTS`의 정확한 이름·버전에서만 적용하고 매 빌드
SHA-256을 검증한다. 원문 없는 새 배포물은 빈 기본 허용 목록에 의해 실패한다.

- CTranslate2: https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.3/LICENSE
  - SHA-256: `54aa79d9fe3c09e67a16dcd95b9e88676405a6ec174efda31036983cf7672ecb`
- tokenizers: https://raw.githubusercontent.com/huggingface/tokenizers/v0.23.3/LICENSE
  - SHA-256: `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`
- GPLv2: https://raw.githubusercontent.com/qt/qtbase/v6.10.2/LICENSES/GPL-2.0-only.txt
  - SHA-256: `8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643`
- shadcn/ui MIT: https://raw.githubusercontent.com/shadcn-ui/ui/6ea6856f5a1082d4d9c231559b6bc3ee73827493/LICENSE.md
  - SHA-256: `1564074e13439397221ffd522e2e504d56561994a23d371aa5e3ad43e4f5423f`

CPython은 빌드 Python의 `sys.base_prefix/LICENSE.txt`를 바이트 그대로 복사해
Windows 추가 조건까지 동봉하고 `sys.version` 및 SHA-256을 manifest에 기록한다.
Tailwind CSS와 Vite는 개발 의존성이지만 산출물에 코드가 들어가므로 수집한다.

PyAV `v17.1.0/.github/workflows/tests.yml`의 `CIBW_BEFORE_BUILD_WINDOWS`가
`scripts/ffmpeg-latest.json`을 사용하며, 그 태그의 JSON은 `8.1.1-2`를 지정한다:
https://github.com/PyAV-Org/PyAV/blob/v17.1.0/scripts/ffmpeg-latest.json
`check_bundle.py`는 실제 av.libs DLL의 `avcodec_version()` = `62.28.101`,
`av_version_info()` = `8.1.1`을 고지와 대조한다. 업데이트 시 고지·빌드 출처와
이 검사를 함께 갱신해야 한다.
