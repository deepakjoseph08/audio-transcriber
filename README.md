# audio-transcriber

Transcribe a recording of any size from your phone, then get a detailed breakdown from Claude.

```
 PHONE                          CLOUD SESSION (Claude Code)
 ─────                          ───────────────────────────
 1. Upload recording ──► Google Drive (any size)
 2. Share: "Anyone with link"
 3. Open Claude app ► Code ► this repo
    type: /transcribe <link>  ──►  download
                                    │
                                    ▼
                                 ffmpeg: 16 kHz mono  (45 MB ► 7 MB)
                                    │
                                    ▼
                                 cut into ~10 min chunks at pauses
                                    │
                                    ▼
                                 Whisper on each chunk (cached, resumable)
                                    │
                                    ▼
                                 transcript.md with [hh:mm:ss] stamps
                                    │
 4. Read summary, decisions,  ◄──  Claude reads it, writes breakdown
    action items, timestamps
```

## Use it from your phone

1. Upload the recording to Google Drive.
2. In Drive: Share > General access > **Anyone with the link**. Copy the link.
3. Claude app > Code > start a session on this repo.
4. Type: `/transcribe <paste link>` (or just "transcribe this: <link>").
5. When done, you can switch the Drive file back to Restricted.

## Engines

| Engine | Needs | Speed (1 hr audio) | Cost |
|---|---|---|---|
| local (default) | nothing | ~9 min on 4-core cloud box (measured: 43 min audio in 6 min 16 s) | free |
| groq | `GROQ_API_KEY` in environment settings | seconds | $0.04 per hour of audio |
| openai | `OPENAI_API_KEY` | ~1-2 min | per OpenAI pricing |

The script picks Groq if its key exists, else OpenAI, else local.

## Run it directly

```bash
bash .claude/skills/transcribe/scripts/setup.sh
python3 .claude/skills/transcribe/scripts/transcribe.py <file-or-link> --out transcripts/my-call
```

Output in `transcripts/my-call/`: `transcript.md` (timestamped), `transcript.txt` (plain), `segments.json` (every line with start/end time). If it stops halfway, run the same command again; finished chunks are reused.
