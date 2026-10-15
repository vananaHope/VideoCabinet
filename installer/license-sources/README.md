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
