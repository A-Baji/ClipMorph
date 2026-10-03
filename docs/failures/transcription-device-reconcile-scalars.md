# Transcription failure after a clean transcript

Fixed by commit `17fbadf` ("Fix the transcription failures that follow a clean
transcript"). Record a new entry here when the same failure mode recurs, or when
a change touches the guarded paths below.

## Symptoms

- `job create` fails the transcript stage immediately after a clean, successful
  transcription.
- The running transcript is marked `interrupted_by_restart` and the transcript
  session save fails with `stale checkpoint revision`.
- On CUDA machines, alignment crashes with a CPU-input/CUDA-weights mismatch.

## Root causes

Three independent causes produced the same symptom:

1. **Import-time device constant.** Whisper alignment and diarization loaded
   their models on CUDA from an import-time device constant, ignoring the
   configured `transcription_device`. A configured CPU session still loaded
   CUDA weights, so alignment crashed with a CPU-input/CUDA-weights mismatch.
2. **Nested in-process `JobService` reconciliation.** The workflow constructs a
   nested `JobService` to save the transcript session. Its startup
   reconciliation scan saw the job its own worker thread was already running,
   marked the running transcript `interrupted_by_restart`, and the save failed
   with `stale checkpoint revision`.
3. **Non-native scalars at the session boundary.** Some models return numpy
   timestamps (`np.float64`). They pass the JSON transcript-session write
   because `np.float64` subclasses `float`, but crash the manifest's YAML dump
   with `cannot represent an object` right after the clean transcription.

## Detection

Tests added in `17fbadf` pin each cause:

- The configured-device test: alignment/diarization follow the configured
  `transcription_device`, not the import-time constant.
- The nesting test: in-process `JobService` constructions run with
  `reconcile=False` and do not reconcile against a job their own thread runs.
- The scalar-coercion test: `create_edit_session` coerces every scalar to a
  native Python type at the session boundary.

## Constraints for future changes

- Transcription device resolution must flow through the configured
  `transcription_device`; never reintroduce a module-level device constant for
  alignment or diarization.
- Nested in-process `JobService` constructions must pass `reconcile=False`;
  startup reconciliation is only for restarts, not for in-flight work in the
  same process.
- Anything written across the transcript-session / manifest boundary must be
  coerced to native Python types (JSON tolerates numpy scalars; YAML does not).
