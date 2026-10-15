# 로컬 TLS 테스트 전용

`localhost-cert.pem`과 `localhost-key.pem`은 테스트 서버용 공개 fixture다.
실제 서비스나 자격 증명 저장에 사용하지 않는다. 인증서는 localhost DNS 이름만 포함하며,
테스트 클라이언트의 명시적인 신뢰 설정 안에서만 신뢰한다. 시스템 인증서 저장소에는 등록하지 않는다.

생성 명령 (OpenSSL은 생성 때만 필요하며 테스트 실행에는 필요하지 않음):

```sh
openssl req -x509 -newkey rsa:2048 -nodes -keyout localhost-key.pem -out localhost-cert.pem -days 36500 -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost'
```
