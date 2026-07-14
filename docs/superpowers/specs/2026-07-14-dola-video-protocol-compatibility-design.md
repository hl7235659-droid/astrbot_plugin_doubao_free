# Dola Video Protocol Compatibility Design

## Goal

Restore successful `dola-video` generation through the existing OpenAI-compatible gateway after Dola changed its web video ability protocol.

Success means an authenticated `POST /v1/videos/generations` request is accepted, yields a conversation identifier, completes polling, and returns a reachable video URL without submitting the same prompt twice.

## Evidence

- Gateway authentication, `/health`, and `/v1/models` were working before Docker Desktop stopped.
- Two accounts that failed video submission still returned valid Dola account profiles, so the failure is not caused by expired cookies.
- Both accounts failed at the same boundary with `视频受理未返回 conversation_id`.
- Historical gateway records include successful videos on 2026-07-10, while the latest request failed immediately on 2026-07-14.
- The current Dola frontend uses outer skill type `SkillVideoGeneration = 17` and nested ability type `VIDEO_GENERATE = 50`.
- The gateway currently sends only a flat `chat_ability.ability_type = 17` payload.

## Chosen Approach

Use the current Dola protocol without automatically retrying the legacy protocol.

The outgoing video ability marker will be encoded as:

```json
{
  "ability_type": 17,
  "ability_param": "{\"ability_type\":50,\"ability_param\":{\"ratio\":\"1:1\",\"duration\":5}}"
}
```

The outer value remains the Dola video skill type. The nested value selects the current video generation ability. The public gateway continues accepting `ratio` and `duration`; the upstream model is left to Dola's current default rather than sending the stale `seedance_v2.0` identifier.

The existing message block format and request endpoint remain unchanged because captured Dola requests show that boundary still being accepted. The existing `input_skill` marker remains skill type 17 but drops the obsolete ratio variable.

## Components

### Request Builder

`DolaClient._build_video_body` will use named constants for the outer skill and nested ability identifiers. A small helper will build the nested ability payload so the wire format is independently testable.

### ACK Parsing

A focused helper will extract `conversation_id` from:

- the current `SSE_ACK.ack_client_meta.conversation_id` location;
- an ACK wrapped in a `data` object;
- a directly supplied `conversation_id` on an ACK event.

Extraction will remain limited to ACK-shaped data so unrelated conversation identifiers cannot be mistaken for the submitted job.

### Diagnostics

When no conversation identifier is found, the error will include only event names and top-level field names. It will not include event values, request URLs, cookies, tokens, or response bodies.

### Compatibility Policy

The gateway will not submit a second legacy request automatically. A missing ACK can occur after the upstream accepted a job, so fallback submission could create duplicate videos and consume quota twice.

## Tests

Unit tests will verify:

1. The outer skill type is 17 and the nested video ability type is 50.
2. Ratio and duration survive JSON encoding in the nested parameter.
3. The stale upstream model identifier is absent.
4. `input_skill` identifies skill 17 without legacy variables.
5. Conversation identifiers are extracted from each supported ACK shape.
6. Missing-ACK diagnostics expose structure only.
7. Existing video acceptance and rejection marker tests continue to pass.

## Runtime Verification

After unit tests pass:

1. Start Docker Desktop if it is not running.
2. Rebuild and recreate the gateway container from the current project directory.
3. Verify authenticated `/health` and `/v1/models` requests.
4. Submit one 5-second, text-only video job through the public API.
5. Poll until completion or a specific upstream failure.
6. Probe the returned URL without printing the API key or cookie values.

The live test intentionally uses one request only to avoid duplicate quota consumption.

## Scope

This change is limited to `dola_client.py` and focused tests. It does not alter cookie storage, API-key handling, account rotation, image generation, chat, the gateway database, or the DolaNoCard desktop application.
