// Compare parsed identity inputs with the build-validated reference document.
// No installed executable, shell, external JSON library or runtime is executed.
// The canonical form is internal to this parser, not the fingerprint hash format.
// my-video-manager.iss의 [Code] 섹션 안에서 #include되므로 여기서 [Code] 헤더를 다시 열지 않는다.
function GetFileAttributes(Filename: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

procedure JsonSpace(const Text: String; var P: Integer);
begin
  while P <= Length(Text) do begin
    if Pos(Text[P], ' ' + #9 + #10 + #13) = 0 then Break;
    P := P + 1;
  end;
end;

function JsonString(const Text: String; var P: Integer): String;
var C: Char; I, N, Digit: Integer;
begin
  Result := '';
  if (P > Length(Text)) or (Text[P] <> '"') then RaiseException('Expected JSON string');
  P := P + 1;
  while P <= Length(Text) do begin
    C := Text[P];
    P := P + 1;
    if C = '"' then Exit;
    if Ord(C) < 32 then RaiseException('Invalid JSON string');
    if C = '\' then begin
      if P > Length(Text) then RaiseException('Truncated JSON escape');
      C := Text[P];
      P := P + 1;
      case C of
        '"', '\', '/': Result := Result + C;
        'b': Result := Result + #8;
        'f': Result := Result + #12;
        'n': Result := Result + #10;
        'r': Result := Result + #13;
        't': Result := Result + #9;
        'u': begin
          N := 0;
          for I := 1 to 4 do begin
            if P > Length(Text) then RaiseException('Truncated Unicode escape');
            Digit := Pos(Lowercase(Text[P]), '0123456789abcdef') - 1;
            if Digit < 0 then RaiseException('Invalid Unicode escape');
            N := N * 16 + Digit;
            P := P + 1;
          end;
          Result := Result + Chr(N);
        end;
      else RaiseException('Invalid JSON escape');
      end;
    end else Result := Result + C;
  end;
  RaiseException('Unterminated JSON string');
end;

function JsonToken(const Value: String): String;
begin
  Result := IntToStr(Length(Value)) + ':' + Value;
end;

function JsonValue(const Text: String; var P: Integer; Depth: Integer): String;
var C, Closing: Char; Key, Value: String; Entries, Keys: TStringList; I, Start: Integer;
begin
  if Depth > 32 then RaiseException('JSON nesting limit');
  JsonSpace(Text, P);
  if P > Length(Text) then RaiseException('Missing JSON value');
  C := Text[P];
  if C = '"' then begin
    Result := 's' + JsonToken(JsonString(Text, P));
    Exit;
  end;
  if (C = '{') or (C = '[') then begin
    Result := C;
    if C = '{' then Closing := '}' else Closing := ']';
    Entries := TStringList.Create;
    Keys := TStringList.Create;
    try
      Keys.CaseSensitive := True;
      Entries.CaseSensitive := True;
      P := P + 1;
      JsonSpace(Text, P);
      if (P <= Length(Text)) and (Text[P] <> Closing) then begin
        while True do begin
          Key := '';
          if C = '{' then begin
            Key := JsonString(Text, P);
            if Keys.IndexOf(Key) >= 0 then RaiseException('Duplicate JSON key');
            Keys.Add(Key);
            JsonSpace(Text, P);
            if (P > Length(Text)) or (Text[P] <> ':') then RaiseException('Missing colon');
            P := P + 1;
          end;
          Value := JsonValue(Text, P, Depth + 1);
          // Root metadata is explanatory; identity consists of these three fields.
          if (Depth <> 0) or (Key = 'schema_version') or (Key = 'inputs') or (Key = 'fingerprint') then
            Entries.Add(JsonToken(Key) + JsonToken(Value));
          JsonSpace(Text, P);
          if P > Length(Text) then RaiseException('Truncated JSON');
          if Text[P] = Closing then Break;
          if Text[P] <> ',' then RaiseException('Missing comma');
          P := P + 1;
          JsonSpace(Text, P);
        end;
      end;
      if (P > Length(Text)) or (Text[P] <> Closing) then RaiseException('Missing closing bracket');
      P := P + 1;
      if C = '{' then Entries.Sort;
      for I := 0 to Entries.Count - 1 do Result := Result + Entries[I];
      Result := Result + Closing;
    finally
      Entries.Free;
      Keys.Free;
    end;
    Exit;
  end;
  // Fingerprint schema has only nonnegative integer numbers (schema_version).
  Start := P;
  while P <= Length(Text) do begin
    if Pos(Text[P], '0123456789') = 0 then Break;
    P := P + 1;
  end;
  if P = Start then RaiseException('Unsupported JSON value');
  if (P - Start > 1) and (Text[Start] = '0') then RaiseException('Invalid JSON integer');
  Result := 'n' + Copy(Text, Start, P - Start);
end;

function ReadIdentity(const Filename: String): String;
var Text: AnsiString; Decoded: String; P: Integer;
begin
  if not LoadStringFromFile(Filename, Text) then RaiseException('Cannot read runtime identity');
  if Length(Text) > 1048576 then RaiseException('Runtime identity too large');
  Decoded := UTF8Decode(Text);
  P := 1;
  JsonSpace(Decoded, P);
  if (P > Length(Decoded)) or (Decoded[P] <> '{') then RaiseException('Expected identity object');
  Result := JsonValue(Decoded, P, 0);
  JsonSpace(Decoded, P);
  if P <= Length(Decoded) then RaiseException('Trailing JSON content');
end;

function NoReparsePoints(const Directory: String): Boolean;
var Entry: TFindRec;
begin
  Result := False;
  if (GetFileAttributes(Directory) and $400) <> 0 then Exit;
  if FindFirst(AddBackslash(Directory) + '*', Entry) then begin
    try
      repeat
        if (Entry.Name <> '.') and (Entry.Name <> '..') then begin
          if (Entry.Attributes and $400) <> 0 then Exit;
          if (Entry.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
            if not NoReparsePoints(AddBackslash(Directory) + Entry.Name) then Exit;
        end;
      until not FindNext(Entry);
    finally
      FindClose(Entry);
    end;
  end;
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '호환되는 기존 설치본을 확인할 수 없습니다. 전체 설치 파일을 사용하세요.';
  try
    if not FileExists(ExpandConstant('{app}\my-video-manager.exe')) then Exit;
    if not NoReparsePoints(ExpandConstant('{app}')) then Exit;
    ExtractTemporaryFile('patch-expected.json');
    if ReadIdentity(ExpandConstant('{app}\runtime-fingerprint.json')) <>
       ReadIdentity(ExpandConstant('{tmp}\patch-expected.json')) then Exit;
    Result := '';
  except
    Log('Patch identity validation failed: ' + GetExceptionMessage);
  end;
  if Result <> '' then Log(Result);
end;
