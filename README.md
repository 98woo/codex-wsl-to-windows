# Codex Session Bridge

WSL에서 생성된 로컬 Codex 세션 메타데이터를 Windows 네이티브 Codex App이 읽을 수 있도록 Windows 경로 기준으로 변환하는 도구입니다.

이 도구는 **OpenAI 공식 마이그레이션 도구가 아닙니다.** Codex App 내부 로컬 상태 파일 구조에 의존하므로 Codex 버전에 따라 동작하지 않을 수 있습니다. 실행 전 Codex App과 WSL에서 실행 중인 Codex를 모두 종료하고, 반드시 dry-run 결과를 먼저 확인하세요.

## 무엇을 바꾸나

기본 대상은 현재 Windows 사용자의 `%USERPROFILE%\.codex`입니다. 다른 위치의 Codex DB를 변환해야 하면 `--db`로 `state_5.sqlite` 경로를 명시하세요.

- `state_5.sqlite`의 thread `cwd`, `rollout_path`, `sandbox_policy`
- `sessions` / `archived_sessions` 아래 rollout JSONL의 경로 메타데이터
- `.codex-global-state.json`의 workspace root, heartbeat permission root

주요 변환 예시는 다음과 같습니다.

```text
/mnt/c/Users/<UserName>/.codex/... -> C:\Users\<UserName>\.codex\...
/mnt/d/workspace/project           -> D:\workspace\project
/home/<LinuxUser>/project          -> \\wsl.localhost\Ubuntu\home\<LinuxUser>\project
```

## 하지 않는 것

이 도구는 다음 항목을 설치하거나 수정하지 않습니다.

- Codex App 설치
- OpenAI 계정 또는 인증 토큰
- Chrome 플러그인
- native pipe bridge
- MCP 서버 설정
- Windows/WSL 간 파일 복사

이 도구는 로컬 세션 메타데이터의 경로 문자열만 변환합니다.

## 요구 사항

- Windows에서 실행
- Python 3 사용 가능
  - `py -3` 또는 `python` 명령이 PATH에서 실행되어야 합니다.
- Codex App과 WSL Codex를 모두 종료한 상태
- 기본 Codex 데이터 위치가 `%USERPROFILE%\.codex`이거나 `--db`로 명시 가능해야 합니다.

## 처음 사용하는 방법

아래 순서대로 진행하세요. 예시는 PowerShell 기준입니다.

### 1. 폴더 준비

GitHub에서 받은 파일을 원하는 위치에 압축 해제하거나 clone합니다. 예를 들어 다음 위치에 폴더가 있다고 가정합니다.

```text
C:\Users\<UserName>\Downloads\codex-session-bridge
```

폴더 안에는 최소한 다음 파일이 있어야 합니다.

```text
codex-session-bridge-all.cmd
codex-session-bridge-all.ps1
README.md
tools\
```

일반 사용자는 `tools` 안의 Python 파일을 직접 실행하지 말고 `codex-session-bridge-all.cmd`만 실행하면 됩니다.

### 2. PowerShell 열기

방법 A: 파일 탐색기에서 실행

1. `codex-session-bridge` 폴더를 파일 탐색기로 엽니다.
2. 주소창에 `powershell`을 입력합니다.
3. Enter를 누르면 해당 폴더에서 PowerShell이 열립니다.

방법 B: 명령으로 이동

```powershell
cd "C:\Users\<UserName>\Downloads\codex-session-bridge"
```

경로에 공백이 있으면 반드시 따옴표로 감싸세요.

### 3. Python 확인

아래 명령 중 하나가 버전을 출력해야 합니다.

```powershell
py -3 --version
```

또는:

```powershell
python --version
```

둘 다 실패하면 Python 3을 설치하고 다시 실행하세요. Windows용 Python을 설치할 때는 PATH에 등록되도록 설정하는 것이 좋습니다.

### 4. Codex 종료

실제 적용 전에는 다음을 모두 종료하세요.

- Windows Codex App
- WSL 터미널에서 실행 중인 Codex
- VS Code나 터미널 안에서 실행 중인 Codex 세션

dry-run은 읽기 중심이지만, 실제 적용(`--yes`)은 Codex 로컬 상태 파일을 수정하므로 Codex를 종료한 상태에서 실행하는 것이 안전합니다.

### 5. 먼저 dry-run 실행

dry-run은 실제 파일을 수정하지 않습니다. 무엇이 바뀔지 분석하고 report만 생성합니다.

```powershell
.\codex-session-bridge-all.cmd migrate-all --include-archived
```

정상 실행되면 대략 이런 형태의 결과가 나옵니다.

```json
{
  "report": "...\codex-session-bridge-all-report.json",
  "counters": {
    "db_threads_seen": 10,
    "db_threads_changed": 8,
    "rollout_files_seen": 10,
    "rollout_files_changed": 8,
    "global_state_changed": true,
    "json_string_paths_changed": 100,
    "unmapped_paths": 0
  },
  "db_changes": 8,
  "rollout_changes": 8,
  "global_state_changed": true
}
DRY RUN only. 전체 변환하려면 같은 명령에 --yes를 추가하세요.
```

중요하게 볼 값은 다음입니다.

- `db_threads_changed`: Windows 경로로 바뀔 세션 수
- `rollout_files_changed`: Windows 경로로 바뀔 대화 로그 파일 수
- `unmapped_paths`: 변환하지 못한 경로 수. 가능하면 `0`이 좋습니다.
- `json_key_collisions`: JSON key 충돌 수. 실제 적용 시 충돌이 있으면 중단됩니다.
- `report`: 상세 리포트 파일 위치

### 6. 결과가 괜찮으면 실제 적용

dry-run 결과를 확인한 뒤 같은 명령에 `--yes`를 추가합니다.

```powershell
.\codex-session-bridge-all.cmd migrate-all --include-archived --yes
```

적용이 끝나면 백업 폴더가 출력됩니다.

```text
MIGRATED ALL
BACKUP: C:\...\codex-session-bridge-backups\YYYYMMDD-HHMMSS-all-sessions
```

이 `BACKUP:` 경로는 롤백할 때 필요하므로 지우지 마세요.

### 7. Codex App에서 확인

1. Windows Codex App을 다시 실행합니다.
2. Windows native 실행 엔진을 사용합니다.
3. 기존 WSL 세션이 있던 프로젝트 폴더를 Windows 경로로 엽니다.
   - 예: `/mnt/d/work/project`였으면 `D:\work\project`
4. 이전 대화가 보이는지 확인합니다.

## 자주 쓰는 명령

기본 dry-run:

```powershell
.\codex-session-bridge-all.cmd migrate-all --include-archived
```

기본 실제 적용:

```powershell
.\codex-session-bridge-all.cmd migrate-all --include-archived --yes
```

WSL 배포판 이름이 `Ubuntu`가 아닐 때:

```powershell
.\codex-session-bridge-all.cmd --distro Ubuntu-24.04 migrate-all --include-archived
```

WSL 배포판 이름에 공백이 있을 때:

```powershell
.\codex-session-bridge-all.cmd --distro "Ubuntu 22-0.4" migrate-all --include-archived
```

Codex DB가 기본 위치가 아닐 때:

```powershell
.\codex-session-bridge-all.cmd --db "D:\somewhere\.codex\state_5.sqlite" migrate-all --include-archived
```

백업 위치를 직접 지정할 때:

```powershell
.\codex-session-bridge-all.cmd --backup-root "D:\codex-backups" migrate-all --include-archived --yes
```

도구 버전 확인:

```powershell
.\codex-session-bridge-all.cmd --version
```

도움말 보기:

```powershell
.\codex-session-bridge-all.cmd --help
.\codex-session-bridge-all.cmd migrate-all --help
.\codex-session-bridge-all.cmd rollback --help
```

## safe mode와 aggressive mode

기본값은 **safe mode**입니다.

safe mode는 JSON 전체에서 경로처럼 보이는 문자열을 무작정 바꾸지 않고, `cwd`, `rollout_path`, `writableRoots`, `active-workspace-roots`, `project-order`, `path` 같은 메타데이터 key 중심으로 변환합니다. 이 방식은 rollout JSONL 안에 들어 있는 대화 원문, 로그, 코드 블록이 의도치 않게 변경되는 위험을 줄입니다.

필요한 경우 기존처럼 경로처럼 보이는 문자열을 더 넓게 변환할 수 있습니다.

```powershell
.\codex-session-bridge-all.cmd migrate-all --include-archived --aggressive
```

`--aggressive`는 대화 원문이나 로그 문자열까지 변경할 수 있으므로 먼저 dry-run 리포트를 확인하세요.

## 롤백

문제가 생기면 적용 시 출력된 `BACKUP:` 폴더를 사용해 되돌릴 수 있습니다.

예를 들어 적용 시 아래처럼 출력됐다면:

```text
BACKUP: C:\Users\<UserName>\Downloads\codex-session-bridge\codex-session-bridge-backups\20260513-101500-all-sessions
```

그 경로를 `--backup`에 넣습니다.

먼저 dry-run:

```powershell
.\codex-session-bridge-all.cmd rollback --backup "C:\Users\<UserName>\Downloads\codex-session-bridge\codex-session-bridge-backups\20260513-101500-all-sessions"
```

실제 롤백:

```powershell
.\codex-session-bridge-all.cmd rollback --backup "C:\Users\<UserName>\Downloads\codex-session-bridge\codex-session-bridge-backups\20260513-101500-all-sessions" --yes
```

## 옵션

옵션은 위치가 중요합니다.

```text
전역 옵션: codex-session-bridge-all.cmd 뒤, migrate-all/rollback 앞
명령 옵션: migrate-all 또는 rollback 뒤
```

예:

```powershell
.\codex-session-bridge-all.cmd --distro Ubuntu-24.04 migrate-all --include-archived --yes
```

여기서 `--distro`는 전역 옵션이고, `--include-archived`, `--yes`는 `migrate-all` 옵션입니다.

### 전역 옵션

```text
--version              도구 버전 출력
--db PATH              기본값: %USERPROFILE%\.codex\state_5.sqlite
--backup-root PATH     백업 생성 위치
--distro NAME          /home/... 경로를 UNC로 바꿀 때 사용할 WSL 배포판 이름. 기본값: Ubuntu
--force-non-windows    비 Windows 환경 실행 제한을 우회
```

언제 쓰는지:

| 옵션 | 언제 사용하나 |
| --- | --- |
| `--version` | 설치된 도구 버전만 확인하고 싶을 때 |
| `--db PATH` | Codex 상태 DB가 `%USERPROFILE%\.codex\state_5.sqlite`가 아닐 때 |
| `--backup-root PATH` | 백업을 도구 폴더가 아니라 다른 드라이브/폴더에 저장하고 싶을 때 |
| `--distro NAME` | `/home/...` 세션을 변환해야 하고 WSL 배포판 이름이 `Ubuntu`가 아닐 때 |
| `--force-non-windows` | 테스트나 개발 목적으로 Windows가 아닌 환경에서 강제로 실행할 때. 일반 사용자는 쓰지 마세요. |

### `migrate-all` 옵션

```text
--include-archived     archived_sessions rollout도 변환
--report PATH          dry-run/apply 리포트 JSON 경로
--aggressive           경로처럼 보이는 모든 JSON 문자열을 더 넓게 변환
--yes                  실제 수정
```

언제 쓰는지:

| 옵션 | 언제 사용하나 |
| --- | --- |
| `--include-archived` | 보관 처리된 옛 세션까지 Windows App에서 보고 싶을 때. 보통 켜는 것을 권장합니다. |
| `--report PATH` | 리포트 파일을 특정 위치에 저장하고 싶을 때 |
| `--aggressive` | safe mode dry-run 후에도 필요한 경로가 덜 바뀐 것이 명확할 때. 먼저 dry-run으로만 확인하세요. |
| `--yes` | dry-run 결과를 확인했고 실제로 파일을 수정할 때 |

### `rollback` 옵션

```text
--backup PATH          복원할 백업 폴더
--yes                  실제 복원
```

언제 쓰는지:

| 옵션 | 언제 사용하나 |
| --- | --- |
| `--backup PATH` | 적용 시 출력된 `BACKUP:` 폴더를 지정할 때 |
| `--yes` | 롤백을 실제로 수행할 때. 없으면 dry-run입니다. |

## 주의할 점

이 마이그레이션은 Windows 네이티브 Codex App에서 WSL 세션을 이어 보는 것을 우선합니다. 적용 후에는 WSL Codex 쪽에서 기존 세션이 보이지 않을 수 있습니다. 그 경우 생성된 백업으로 롤백하거나, Windows용/WSL용 세션 카탈로그를 분리해서 운용해야 합니다.

`/home/...` 경로는 기본적으로 `\\wsl.localhost\Ubuntu\home\...`로 변환됩니다. 실제 WSL 배포판 이름이 `Ubuntu-24.04`, `Debian` 등이라면 `--distro`를 지정하세요.

```powershell
.\codex-session-bridge-all.cmd --distro Ubuntu-24.04 migrate-all --include-archived
```

WSL 배포판 이름은 자동 감지하지 않습니다. `/home/...` 경로 자체에는 어느 WSL 배포판에서 만들어진 세션인지 정보가 없기 때문에, 여러 배포판을 사용하는 환경에서는 사용자가 올바른 이름을 지정해야 합니다. 이름에 공백이 있으면 따옴표로 감싸세요.

```powershell
.\codex-session-bridge-all.cmd --distro "Ubuntu 22-0.4" migrate-all --include-archived
```

`/mnt/c`, `/mnt/d` 같은 Windows 드라이브 마운트 경로는 WSL 배포판 이름과 무관하게 `C:\...`, `D:\...`로 변환됩니다.

`session_index.jsonl`은 현재 백업 대상이지만 변환 대상은 아닙니다. 이 파일에 경로 정보가 포함된 Codex 버전이 확인되면 후속 버전에서 변환 대상으로 추가할 수 있습니다.

## 개인정보 주의

생성된 report와 backup에는 다음과 같은 로컬 정보가 포함될 수 있습니다.

- Windows 사용자명
- Linux 사용자명
- 프로젝트 경로
- 세션 ID
- workspace root
- sandbox permission root

GitHub Issue, Discord, 블로그 등에 공유하기 전에 반드시 내용을 확인하세요.

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
    codex_session_path_bridge_all_win_safe.py
    codex_session_path_bridge_all_win_guarded.py
```

이 저장소에는 리포트와 백업 파일을 커밋하지 마세요.

`tools/codex_session_path_bridge_all_win.py`는 호환성을 위해 남겨 둔 legacy 구현 파일입니다. 일반 사용자는 `codex-session-bridge-all.cmd`를 실행하세요. legacy 파일을 직접 실행해도 guarded 엔트리포인트로 위임됩니다.

## 개발

테스트 실행:

```bash
python -m pip install pytest
python -m pytest -q
```

문법 검사:

```bash
python -m py_compile tools/codex_session_path_bridge_all_win.py
python -m py_compile tools/codex_session_path_bridge_all_win_safe.py
python -m py_compile tools/codex_session_path_bridge_all_win_guarded.py
```
