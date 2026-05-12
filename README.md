# Codex Session Bridge

WSL에서 생성된 로컬 Codex 세션 메타데이터를 Windows 네이티브 Codex App이 읽을 수 있도록 Windows 경로 기준으로 변환하는 도구입니다.

이 도구는 OpenAI 공식 마이그레이션 도구가 아닙니다. 실행 전 Codex App과 WSL에서 실행 중인 Codex를 모두 종료하고, 반드시 dry-run 결과를 먼저 확인하세요.

## 무엇을 바꾸나

기본 대상은 현재 Windows 사용자의 `%USERPROFILE%\.codex`입니다. 다른 위치의 Codex DB를 변환해야 하면 `--db`로 `state_5.sqlite` 경로를 명시하세요.

- `state_5.sqlite`의 thread `cwd`, `rollout_path`, `sandbox_policy`
- `sessions` / `archived_sessions` 아래 rollout JSONL의 경로 문자열
- `.codex-global-state.json`의 workspace root, heartbeat permission root

주요 변환 예시는 다음과 같습니다.

```text
/mnt/c/Users/<UserName>/.codex/... -> C:\Users\<UserName>\.codex\...
/mnt/d/workspace/project           -> D:\workspace\project
/home/<LinuxUser>/project          -> \\wsl.localhost\Ubuntu\home\<LinuxUser>\project
```

## 요구 사항

- Windows에서 실행
- Python 3 사용 가능
  - `py -3` 또는 `python` 명령이 PATH에서 실행되어야 합니다.
- Codex App과 WSL Codex를 모두 종료한 상태
- 기본 Codex 데이터 위치가 `%USERPROFILE%\.codex`이거나 `--db`로 명시 가능해야 합니다.

## 빠른 실행

먼저 dry-run을 실행합니다. 이 명령은 실제 파일을 수정하지 않고 리포트만 만듭니다.

```bat
codex-session-bridge-all.cmd migrate-all --include-archived
```

결과를 확인한 뒤 실제 적용합니다.

```bat
codex-session-bridge-all.cmd migrate-all --include-archived --yes
```

적용 시 백업 폴더가 자동 생성됩니다.

```text
codex-session-bridge-backups\YYYYMMDD-HHMMSS-all-sessions
```

## 롤백

마이그레이션 직전에 생성된 백업 폴더를 지정합니다.

먼저 dry-run:

```bat
codex-session-bridge-all.cmd rollback --backup "codex-session-bridge-backups\YYYYMMDD-HHMMSS-all-sessions"
```

실제 롤백:

```bat
codex-session-bridge-all.cmd rollback --backup "codex-session-bridge-backups\YYYYMMDD-HHMMSS-all-sessions" --yes
```

## 옵션

전역 옵션:

```text
--db PATH              기본값: %USERPROFILE%\.codex\state_5.sqlite
--backup-root PATH     백업 생성 위치
--distro NAME          /home/... 경로를 UNC로 바꿀 때 사용할 WSL 배포판 이름. 기본값: Ubuntu
--force-non-windows    비 Windows 환경 실행 제한을 우회
```

`migrate-all` 옵션:

```text
--include-archived     archived_sessions rollout도 변환
--report PATH          dry-run/apply 리포트 JSON 경로
--yes                  실제 수정
```

`rollback` 옵션:

```text
--backup PATH          복원할 백업 폴더
--yes                  실제 복원
```

## 주의할 점

이 마이그레이션은 Windows 네이티브 Codex App에서 WSL 세션을 이어 보는 것을 우선합니다. 적용 후에는 WSL Codex 쪽에서 기존 세션이 보이지 않을 수 있습니다. 그 경우 생성된 백업으로 롤백하거나, Windows용/WSL용 세션 카탈로그를 분리해서 운용해야 합니다.

이 도구는 Chrome 플러그인, native pipe bridge, MCP 서버 설정을 설치하거나 고치지 않습니다. 경로 메타데이터만 변환합니다.

## 배포 파일

최소 배포 구조는 다음과 같습니다.

```text
codex-session-bridge/
  .gitignore
  codex-session-bridge-all.cmd
  codex-session-bridge-all.ps1
  LICENSE
  README.md
  tools/
    codex_session_path_bridge_all_win.py
```

이 저장소에는 리포트와 백업 파일을 커밋하지 마세요.
