# Third-party notices: nexus-voice worker

The worker (`voice/`) is an optional, separately installed local process. The NEXUS core
backend does not import or link any package listed here; it only talks to the worker over a
loopback WebSocket.

| Component | Licence | Source |
|-----------|---------|--------|
| piper-tts 1.8.0 (TTS engine) | GPL-3.0-or-later (package metadata and `COPYING`) | https://github.com/OHF-voice/piper1-gpl |
| faster-whisper 1.2.1 | MIT | https://github.com/SYSTRAN/faster-whisper |
| Systran/faster-whisper-medium (STT weights) | MIT | https://huggingface.co/Systran/faster-whisper-medium |
| Silero VAD v6 (bundled in faster-whisper) | MIT | https://github.com/snakers4/silero-vad |
| onnxruntime 1.30.0 | MIT | https://github.com/microsoft/onnxruntime |
| numpy 2.4.6 | BSD-3-Clause and others (see its metadata) | https://github.com/numpy/numpy |
| fastapi, uvicorn, websockets, PyJWT | MIT / BSD-3-Clause | PyPI project pages |
| nvidia-cublas-cu12, nvidia-cudnn-cu12 | NVIDIA proprietary (redistribution terms apply) | https://pypi.org/project/nvidia-cudnn-cu12/ |
| en_US-ljspeech-medium (default English voice) | Public domain (LJ Speech dataset) | https://huggingface.co/rhasspy/piper-voices |
| Windows System.Speech voices | Installed by Windows; Microsoft terms apply | not distributed by NEXUS |

Piper is GPL-3.0-or-later. Anyone who **distributes** the worker environment with
`piper-tts` installed must offer the corresponding source and the GPL text
(`piper_tts-1.8.0.dist-info/licenses/COPYING`) under the GPL's terms. The exact source for the
pinned version is the `piper1-gpl` repository at the `v1.8.0` tag. Non-commercial voices are
not downloaded unless the operator opts in and carry their own licences (see
`src/nexus_voice/manifest.json`).
