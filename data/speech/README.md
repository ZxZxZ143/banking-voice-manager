# Synthetic structured speech fixtures

`structured_utterances.json` contains 100 positive values (20 phones, 20 IINs,
20 plates, 15 policies, 10 claims, 15 regions) and 12 invalid/ambiguous negatives.
All values are synthetic; expected labels never enter STT prompts or keywords.
Rebuild with `python scripts/build_structured_speech_dataset.py`.

RU, KK and mixed labels describe the intended utterance, including shared Latin
letter names. Styles cover digit groups, individual digits, fillers, letters and
literal ASR artifacts. The main corpus's fast/slow labels are nominal; its audio
was generated with the ordinary moderate-pace profile. Use the separate 24-case
`--paced` pilot for explicit fast/slow TTS instructions: six kinds × RU/KK × two
requested paces, identical text/voice within each pair. TTS pacing remains variable;
only seven of twelve measured slow versions were longer than their fast partner.
Neither set is real customer speech or a human-annotated acoustic benchmark.

Audio, local model downloads, browser evidence and resumable result JSON stay in
ignored `work/structured-speech/`. Windows commands, metrics, model pins/licenses,
limitations and the unmet precision gate are in
`docs/STRUCTURED_SPEECH_RECOGNITION_VALIDATION.md`.
