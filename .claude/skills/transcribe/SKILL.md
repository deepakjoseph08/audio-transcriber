---
name: transcribe
description: Transcribe an audio or video recording of ANY size (30 MB, 300 MB, 3 hours, does not matter) and then give a detailed breakdown of what was said. Use whenever the user shares a recording, a voice note, a meeting/call recording, a Google Drive / Dropbox / direct link to an audio or video file, or says "transcribe", "what was said in this recording", "summarise this call", "get me the transcript", or invokes /transcribe. The file is split into chunks automatically, so never tell the user the file is too big.
---

# Transcribe any recording, any size

Claude cannot listen to audio directly, so a speech-to-text step runs first, then Claude reads the text. The script handles everything heavy: download, shrink, split at pauses, transcribe chunk by chunk, stitch. Finished chunks are cached, so if anything breaks, running the same command again resumes where it stopped.

## Step 1: Get the file

The user will give one of:
- A **Google Drive link** (most common from phone). It must be shared as "Anyone with the link can view". If download fails with a permission error, tell them exactly that.
- A **Dropbox link** or any **direct download URL**.
- A **file already in the session** (attached, or in the repo folder `inbox/`).

If they gave nothing, ask for the link in one line and stop.

## Step 2: Make sure the tools are there

Run `bash .claude/skills/transcribe/scripts/setup.sh` (safe to re-run, skips what is installed).

## Step 3: Run the transcription

```bash
python3 .claude/skills/transcribe/scripts/transcribe.py "<link-or-path>" --out transcripts/<short-name>
```

Pick `<short-name>` from the date and topic if known, e.g. `2026-10-17-client-call`.

Options:
- `--language en` or `--language hi` if the user says the language. Leave it out to auto-detect. For Hindi-English mixed talk, leave it out.
- `--engine local` forces the free CPU engine. Default `auto` uses Groq if `GROQ_API_KEY` is set (fast), else OpenAI if `OPENAI_API_KEY` is set, else local.
- `--local-model medium` for better accuracy on the local engine (about 2-3x slower than the default `small`).

Speed guide for the local engine on a 4-core cloud box: about 1 minute of work per 7 minutes of audio with `small`. A 1 hour recording takes about 9 minutes. For anything over ~20 minutes of expected run time, run it in the background and tell the user roughly how long it will take. With a Groq key, an hour of audio takes well under a minute.

If the command dies part way, run the exact same command again. It resumes.

## Step 4: Read the transcript and give the breakdown

Read `transcripts/<short-name>/transcript.md`. It has a `[hh:mm:ss]` timestamp about every minute. For long transcripts read it in parts; do not skip any part.

Then reply in this shape (simple, plain English):

1. **One-line verdict**: what this recording is about and the single most important outcome.
2. **Summary**: 5-10 bullets covering the whole recording, in order.
3. **Key points / details**: grouped by topic. Every point carries the timestamp it came from, like `[00:14:20]`, so the user can jump to it.
4. **Decisions made** (with timestamp).
5. **Action items**: who, what, by when (write "owner not said" / "no date said" rather than guessing).
6. **Open questions / unclear parts**: anything left unresolved, plus places where the audio was unclear or the transcript looks wrong (odd words, names that may be misheard).
7. **Numbers, dates, names mentioned**: a quick list.

Rules:
- Only state what is in the transcript. If you infer something, say "my reading:".
- Whisper often misspells names and Indian words. Flag likely misspellings instead of silently "fixing" them.
- Tell the user where the full transcript file is (`transcripts/<short-name>/transcript.md`) and offer to answer questions about it.
- If the user wants to keep it, commit `transcripts/<short-name>/transcript.md` (not the audio, not the chunks) and push.
