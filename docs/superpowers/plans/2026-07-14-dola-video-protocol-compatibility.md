# Dola Video Protocol Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the Dola video request protocol so authenticated gateway calls produce a conversation ID and complete one video without duplicate upstream submissions.

**Architecture:** Keep the public gateway and Dola polling flow unchanged. Replace the stale flat video marker with the current nested skill/ability marker, then isolate ACK extraction and structural diagnostics in small helpers that can be unit tested without network access.

**Tech Stack:** Python 3.12, `unittest`, `aiohttp`, FastAPI/Uvicorn, Docker Compose, Windows PowerShell 5.1.

## Global Constraints

- Preserve all existing user changes in the dirty worktree; never reset, restore, or rewrite unrelated hunks.
- Do not print or commit `.env`, `cookies.txt`, API keys, session IDs, Cookie values, or raw upstream bodies.
- Do not automatically retry the legacy video submission protocol.
- Keep `/v1/videos/generations`, `ratio`, and `duration` backward compatible.
- Submit at most one live video job during runtime verification.
- Do not commit implementation files because `dola_client.py` and `tests/` already contain user-owned uncommitted work; report the final scoped diff instead.

---

### Task 1: Encode the Current Video Ability Protocol

**Files:**
- Create: `tests/test_video_protocol_compatibility.py`
- Modify: `dola_client.py:27-31`
- Modify: `dola_client.py:945-1040`

**Interfaces:**
- Consumes: `DolaClient._build_video_body(prompt: str, ratio: str, duration: int, image_uris: Optional[List[str]] = None) -> dict`
- Produces: `build_video_chat_ability(ratio: str, duration: int) -> dict`
- Produces: constants `DOLA_VIDEO_SKILL_TYPE: int` and `DOLA_VIDEO_ABILITY_TYPE: int`

- [ ] **Step 1: Write the failing request-shape test**

Create `tests/test_video_protocol_compatibility.py` with:

```python
import json
import unittest

from dola_client import DolaClient


class VideoProtocolCompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.client = DolaClient("sessionid=test-session; s_v_web_id=test-fp")

    def test_video_body_uses_nested_current_ability(self):
        body = self.client._build_video_body(
            "固定镜头中的蓝色圆形",
            ratio="1:1",
            duration=5,
        )

        self.assertEqual(17, body["chat_ability"]["ability_type"])
        nested = json.loads(body["chat_ability"]["ability_param"])
        self.assertEqual(50, nested["ability_type"])
        self.assertEqual(
            {"ratio": "1:1", "duration": 5},
            nested["ability_param"],
        )
        self.assertNotIn("seedance_v2.0", body["chat_ability"]["ability_param"])

        input_skill = json.loads(body["ext"]["input_skill"])
        self.assertEqual({"skill_id": "17", "skill_type": 17}, input_skill)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify the current implementation fails**

Run:

```powershell
python -m unittest tests.test_video_protocol_compatibility.VideoProtocolCompatibilityTest.test_video_body_uses_nested_current_ability -v
```

Expected: `ERROR` or `FAIL` because the current `ability_param` has no nested `ability_type=50` and still contains `seedance_v2.0`.

- [ ] **Step 3: Add named protocol constants and the minimal encoder**

Add beside the existing Dola constants in `dola_client.py`:

```python
DOLA_VIDEO_SKILL_TYPE = 17
DOLA_VIDEO_ABILITY_TYPE = 50
```

Add before `class DolaClient`:

```python
def build_video_chat_ability(ratio: str, duration: int) -> dict:
    nested = {
        "ability_type": DOLA_VIDEO_ABILITY_TYPE,
        "ability_param": {
            "ratio": ratio,
            "duration": int(duration),
        },
    }
    return {
        "ability_type": DOLA_VIDEO_SKILL_TYPE,
        "ability_param": json.dumps(nested, separators=(",", ":")),
    }
```

In `_build_video_body`, replace the current `chat_ability` object with:

```python
"chat_ability": build_video_chat_ability(ratio, duration),
```

Replace `ext["input_skill"]` with:

```python
"input_skill": json.dumps(
    {
        "skill_id": str(DOLA_VIDEO_SKILL_TYPE),
        "skill_type": DOLA_VIDEO_SKILL_TYPE,
    },
    separators=(",", ":"),
),
```

Update the module description from flat `ability_type:17` wording to `skill_type:17 + ability_type:50`.

- [ ] **Step 4: Run the focused request test**

Run:

```powershell
python -m unittest tests.test_video_protocol_compatibility.VideoProtocolCompatibilityTest.test_video_body_uses_nested_current_ability -v
```

Expected: one test passes.

- [ ] **Step 5: Review the scoped diff without committing user-owned changes**

Run:

```powershell
git status --short -- dola_client.py tests/test_video_protocol_compatibility.py
git diff -- dola_client.py
Get-Content -Encoding UTF8 -LiteralPath 'tests\test_video_protocol_compatibility.py'
git diff --check -- dola_client.py
```

Expected: only the protocol constants, encoder, request marker replacement, and new test appear; `git diff --check` exits 0.

---

### Task 2: Extract ACK Conversation IDs and Emit Safe Diagnostics

**Files:**
- Modify: `tests/test_video_protocol_compatibility.py`
- Modify: `dola_client.py:867-913`

**Interfaces:**
- Consumes: parsed SSE events as `list[tuple[str, dict]]`
- Produces: `DolaClient._extract_video_conversation_id(events: list) -> str`
- Produces: `DolaClient._summarize_sse_events(events: list) -> str`

- [ ] **Step 1: Add failing tests for supported ACK shapes and redaction**

Add these methods to `VideoProtocolCompatibilityTest`:

```python
    def test_extracts_video_conversation_id_from_supported_ack_shapes(self):
        cases = [
            [("SSE_ACK", {"ack_client_meta": {"conversation_id": "conv-direct"}})],
            [("SSE_ACK", {"data": {"ack_client_meta": {"conversation_id": "conv-wrapped"}}})],
            [("SSE_ACK", {"conversation_id": "conv-top-level"})],
        ]

        self.assertEqual(
            ["conv-direct", "conv-wrapped", "conv-top-level"],
            [self.client._extract_video_conversation_id(events) for events in cases],
        )

    def test_sse_summary_contains_structure_not_values(self):
        events = [
            (
                "SSE_ACK",
                {
                    "ack_client_meta": {"conversation_id": "secret-conversation"},
                    "credential": "secret-cookie-value",
                },
            )
        ]

        summary = self.client._summarize_sse_events(events)

        self.assertIn("SSE_ACK", summary)
        self.assertIn("ack_client_meta", summary)
        self.assertIn("credential", summary)
        self.assertNotIn("secret-conversation", summary)
        self.assertNotIn("secret-cookie-value", summary)
```

- [ ] **Step 2: Run the ACK tests and verify they fail**

Run:

```powershell
python -m unittest `
  tests.test_video_protocol_compatibility.VideoProtocolCompatibilityTest.test_extracts_video_conversation_id_from_supported_ack_shapes `
  tests.test_video_protocol_compatibility.VideoProtocolCompatibilityTest.test_sse_summary_contains_structure_not_values `
  -v
```

Expected: both tests error because the helper methods do not exist.

- [ ] **Step 3: Implement limited ACK extraction and structural summaries**

Add to `DolaClient` near the existing SSE helpers:

```python
    @staticmethod
    def _extract_video_conversation_id(events: list) -> str:
        for event_name, event_data in events:
            if event_name != "SSE_ACK" or not isinstance(event_data, dict):
                continue
            candidates = [event_data]
            wrapped = event_data.get("data")
            if isinstance(wrapped, dict):
                candidates.append(wrapped)
            for candidate in candidates:
                ack_meta = candidate.get("ack_client_meta")
                if isinstance(ack_meta, dict) and ack_meta.get("conversation_id"):
                    return str(ack_meta["conversation_id"])
                if candidate.get("conversation_id"):
                    return str(candidate["conversation_id"])
        return ""

    @staticmethod
    def _summarize_sse_events(events: list) -> str:
        parts = []
        for event_name, event_data in events[:12]:
            keys = sorted(str(key) for key in event_data)[:12] if isinstance(event_data, dict) else []
            parts.append(f"{event_name or '<unnamed>'}[{','.join(keys)}]")
        return ";".join(parts)[:500] or "<none>"
```

Replace the inline ACK loop in `generate_video` with:

```python
        conv_id = self._extract_video_conversation_id(events)
        if not conv_id:
            summary = self._summarize_sse_events(events)
            raise Exception(f"视频受理未返回 conversation_id; events={summary}")
```

- [ ] **Step 4: Run all unit tests**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: six tests pass: the three existing marker tests and the three new compatibility tests.

- [ ] **Step 5: Compile the runtime modules**

Run:

```powershell
python -m py_compile dola_client.py gateway_server.py
```

Expected: exit code 0 and no output.

- [ ] **Step 6: Review the final implementation diff without committing**

Run:

```powershell
git status --short -- dola_client.py tests/test_video_protocol_compatibility.py
git diff --check -- dola_client.py
git diff --stat -- dola_client.py
Get-Content -Encoding UTF8 -LiteralPath 'tests\test_video_protocol_compatibility.py'
```

Expected: no whitespace errors; changes remain limited to the approved protocol compatibility scope.

---

### Task 3: Rebuild and Verify One Live Video End to End

**Files:**
- Runtime input: `.env` (read only)
- Runtime input: `cookies.txt` (read only)
- Runtime configuration: `docker-compose.yml` (unchanged)

**Interfaces:**
- Consumes: `POST /v1/videos/generations` with Bearer authentication
- Produces: an asynchronous video job that reaches `completed` with a reachable result URL

- [ ] **Step 1: Start Docker Desktop only if the engine is unavailable**

Run:

```powershell
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Start-Process -FilePath "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe" -WindowStyle Hidden
  $deadline = [DateTime]::UtcNow.AddMinutes(3)
  do {
    Start-Sleep -Seconds 2
    docker info *> $null
  } while ($LASTEXITCODE -ne 0 -and [DateTime]::UtcNow -lt $deadline)
  if ($LASTEXITCODE -ne 0) { throw "Docker Desktop did not become ready." }
}
```

Expected: Docker engine becomes available within three minutes.

- [ ] **Step 2: Rebuild and recreate the gateway**

Run:

```powershell
docker compose up -d --build --force-recreate
docker compose ps --format json
```

Expected: `dola-gateway` state is `running`, port `8000` is published, and the cookie mount source is the current project `cookies.txt` file.

- [ ] **Step 3: Verify API-key authentication and model discovery without printing the key**

Run:

```powershell
$keyLine = Get-Content -Encoding UTF8 -LiteralPath '.env' |
  Where-Object { $_ -match '^\s*GATEWAY_API_KEY\s*=' } |
  Select-Object -First 1
$apiKey = ($keyLine -split '=', 2)[1].Trim()
$headers = @{ Authorization = "Bearer $apiKey" }
$health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -Headers $headers
$models = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/v1/models' -Headers $headers
[PSCustomObject]@{
  HealthOk = [bool]$health.ok
  CookieCount = [int]$health.cookies
  HasVideoModel = [bool](@($models.data.id) -contains 'dola-video')
}
```

Expected: `HealthOk=True`, `CookieCount` is greater than zero, and `HasVideoModel=True`.

- [ ] **Step 4: Submit exactly one five-second video job**

Run:

```powershell
$body = @{
  model = 'dola-video'
  prompt = '白色背景上的蓝色圆形缓慢旋转，固定镜头，画面简洁，无文字'
  ratio = '1:1'
  duration = 5
  wait = $false
} | ConvertTo-Json
$job = Invoke-RestMethod `
  -Method Post `
  -Uri 'http://127.0.0.1:8000/v1/videos/generations' `
  -Headers $headers `
  -ContentType 'application/json; charset=utf-8' `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
  -TimeoutSec 30
$job | Select-Object id, status, ratio, duration
```

Expected: one job ID is returned with status `queued` or `running`. Do not resubmit if polling later fails.

- [ ] **Step 5: Poll the same job to a terminal state**

Run:

```powershell
$deadline = [DateTime]::UtcNow.AddMinutes(8)
do {
  Start-Sleep -Seconds 10
  $result = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/v1/videos/generations/$($job.id)" `
    -Headers $headers `
    -TimeoutSec 15
  [PSCustomObject]@{ CheckedAt = Get-Date; Status = $result.status }
} while ($result.status -notin @('completed', 'failed') -and [DateTime]::UtcNow -lt $deadline)
if ($result.status -ne 'completed') {
  throw "Video job ended with status '$($result.status)': $($result.error)"
}
```

Expected: the same job reaches `completed` within eight minutes.

- [ ] **Step 6: Probe the result URL and inspect sanitized logs**

Run:

```powershell
$probe = Invoke-WebRequest `
  -UseBasicParsing `
  -Uri $result.url `
  -Headers @{ Range = 'bytes=0-0' } `
  -TimeoutSec 30
docker compose logs --tail 80 --no-color |
  Select-String -Pattern 'Loaded Dola gateway|POST /v1/videos|GET /v1/videos|ERROR'
[PSCustomObject]@{
  JobStatus = $result.status
  HasResultUrl = [bool]$result.url
  ResultUrlStatus = $probe.StatusCode
}
```

Expected: `JobStatus=completed`, `HasResultUrl=True`, and the URL probe returns HTTP 200 or 206. Logs contain no API key or Cookie value.

---

## Final Review

- Confirm the public API contract did not change.
- Confirm only one live video request was submitted.
- Confirm no secret values appeared in test output, logs, Git diff, or documentation.
- Report the pre-existing dirty files separately from the files changed by this implementation.
