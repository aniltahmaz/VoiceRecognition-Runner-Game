# Prototype01 — voice-controlled lane runner

A runner prototype you play with your voice. Four words are shown on screen, one for each
action. Say a word out loud and the character switches lane, jumps or crouches.

Built in Unreal Engine 5.8 (Blueprints) with an offline speech recognizer running in a small
Python process next to the game.

<!-- TODO: add a gameplay GIF or video link here -->

## How it plays

| Word slot | Action |
|-----------|--------|
| Left      | Switch one lane to the left |
| Right     | Switch one lane to the right |
| Top       | Jump |
| Bottom    | Crouch |

- The character runs along splines; lanes are parallel splines it can hop between.
- Every correct word is replaced by a new one, and that slot moves up a difficulty tier
  (Easy → Medium → Hard → Hardest).
- The HUD shows the word the recognizer heard, green on the slot it matched and red otherwise.
- Obstacle types: swinging ropes, falling trees, overhead obstacles and collapsing tiles.
- The main level also has checkpoints, lives, launch zones that push the character forward,
  and a finish zone.

The word list is Polish (16 words in four difficulty tiers) and lives in the `DT_Words` data table.

## How the voice control works

```
microphone → listen.py (Vosk, offline) → OSC /voice/command over UDP :8000 → BP_ThirdPersonCharacter
```

**Python side** — [`VoiceRecognition/VoiceControl/listen.py`](VoiceRecognition/VoiceControl/listen.py)

- Uses the small Polish Vosk model, restricted to a grammar of only the game's words, which
  keeps recognition fast and avoids false matches.
- Detects speech itself instead of waiting for Vosk's endpointing: a peak threshold with
  hysteresis starts and ends an attempt, and 150 ms of pre-roll audio is kept so the first
  consonant is not cut off.
- Sends the command as soon as a partial result contains a known word, and otherwise forces a
  final result after 50 ms of silence.

**Unreal side** — `BP_ThirdPersonCharacter`

- Opens an OSC server on port 8000 at BeginPlay and handles each message in `HandleVoiceCommand`.
- `ResolveDisplayWord` maps the ASCII word from Python back to its display form in `DT_Words`.
- The word is compared against the four active slots and triggers `GoLeft`, `GoRight`,
  `JumpWithVoice` or `CrouchWithVoice`.

## Running it

1. Open `Prototype01.uproject` with Unreal Engine 5.8. The prebuilt Win64 editor module is
   included, so no compiler is needed.
2. Start the recognizer (from its own folder, the model path is relative):

   ```bash
   cd VoiceRecognition/VoiceControl
   pip install -r requirements.txt
   python listen.py
   ```

3. Press Play in the editor and say one of the words on screen.

The recognizer uses the default Windows microphone. If words are missed or triggered by
background noise, adjust `VOICE_START_THRESHOLD` and `VOICE_END_THRESHOLD` at the top of `listen.py`.

To add a word, add a row to `DT_Words` and the same ASCII spelling to `VOCABULARY` in `listen.py`.

## Project layout

```
Content/
  Art/            Level materials and the liana mesh
  Audio/          Footstep and foley sounds (MetaSounds)
  Blueprints/
    Character/    BP_ThirdPersonCharacter — voice commands, word slots
    Core/         Game mode, player controller, HUD
    Gameplay/     Checkpoint, finish zone, launch zone
    Obstacles/    BP_ObstaclesParent and its obstacle types
    Splines/      BP_SplineManager — spline movement, lane switching, checkpoints
  Characters/     Mannequin mesh and locomotion animations
  Data/           DT_Words, S_WordStruct, E_WordDifficulty
  Input/          Enhanced Input actions and mapping contexts
  Maps/           L_ButteryLevelDesign (main level), Test/ (test maps)
  UI/             WBP_MainGame
VoiceRecognition/
  VoiceControl/   listen.py and the Vosk model
```

## Team and my role

<!-- TODO: list the team and describe what you built yourself -->

## Third-party content

- Mannequin characters, animations, foley audio and level prototyping assets: Epic Games (Unreal Engine templates)
- Liana mesh: Quixel Megascans
- Heart icon: Vecteezy
- Speech model: [Vosk](https://alphacephei.com/vosk/) small Polish model
