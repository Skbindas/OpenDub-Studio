# OpenDub Studio: Voice Bank Evidence Ledger

Last updated: 3 October 2026.
Invariants followed: [.agents/rules/opendub-evidence.md](file:///mnt/c/Users/su936/OneDrive/Desktop/OpenDub-Studio/.agents/rules/opendub-evidence.md) and [<USER_HOME>/.gemini/GEMINI.md](file:///mnt/c/Users/su936/.gemini/GEMINI.md).
Acceptance gates strictly governed by [`backend/voice_bank_quality.py`](file:///mnt/c/Users/su936/OneDrive/Desktop/OpenDub-Studio/backend/voice_bank_quality.py).

---

## Important Distinction: Character vs. Voice Performer
This is a **Hindi-dubbed theatrical film** (*Janatha Garage*).
- **On-Screen Character**: The role and visual actor appearing in the scene (e.g. Sathyam / Mohanlal, Anand / Jr NTR, Anu / Nithya Menen, Saidulu / Banerjee, Anu's Mother / Anitha Chowdary).
- **Voice Performer**: The Hindi dubbing voice artist whose voice was recorded in the Hindi soundtrack.
Identifying the on-screen actor does not certify who the voice performer was. Character identity in this ledger refers to the character role in the Hindi-dubbed version, and voice fidelity evaluates reproduction of that Hindi voice performer.

---

## Acceptance Standards & Gate Definitions

1. `single_speaker`: Verified single human voice without competing background speaker voices.
2. `speech_present`: Clear, intelligible Hindi speech present throughout reference.
3. `background_clean`: No audible music bleed, heavy room reverberation, or Foley contamination.
4. `identity_confirmed`: Voice verified to belong to the designated character/role in the film's Hindi soundtrack.
5. `clone_identity_passed`: Cloned audition acoustically matches the reference speaker identity.
6. `naturalness_passed`: Natural cadence, pitch contour, and absence of metallic/robotic artifacts.
7. `dialogue_content_passed`: Requested Hindi test sentence fully delivered without omissions or garbling.

---

## Batch 1: Target Entries (char_01, char_03, char_09, char_12, char_20)

### 1. `char_01_sathyam_mohanlal`
- **Character Role**: Sathyam (सत्यम) — Janatha Garage Chief Patriarch
- **On-Screen Actor**: Mohanlal | **Voice Performer**: Hindi Dubbing Artist (uncredited in local metadata)
- **Movie Scene & Timecode**: `66:53 - 67:03` (4013.6s – 4023.0s). Emotional appeal in Janatha Garage workshop.
- **Reference Audio**: [`storage/default_voice_bank/candidate_voices/char_01_sathyam_mohanlal.wav`](file:///mnt/c/Users/su936/OneDrive/Desktop/OpenDub-Studio/storage/default_voice_bank/candidate_voices/char_01_sathyam_mohanlal.wav)
  - **Ref SHA256**: `3b2befb6d51065c1e2fa3ca4f7f86be374d7107d1b873795e8afeec97326a944`
  - **Duration**: 9.4s (Passes 3–10s gate)
  - **Spoken Text**: "मैं अपने और तकलीफ में पड़े उन सारे लोगों की तरफ से"
- **Audition Audio (Accepted Take)**: [`runtime/voice-bank-audit/clones/char_01_sathyam_mohanlal.wav`](file:///mnt/c/Users/su936/OneDrive/Desktop/OpenDub-Studio/runtime/voice-bank-audit/clones/char_01_sathyam_mohanlal.wav)
  - **Audition SHA256**: `304efe5af6f9c56377c60f5c38c6362c504adea4199f8f50941cf370b881012f`
  - **Requested Text**: "आज हम मिलकर एक नई शुरुआत करेंगे। आपकी बात सुनकर मुझे बहुत खुशी हुई।"
  - **ASR Transcript**: "आज हम मेंकर एक नहीं शुवात करेंगे आपकी बाद सुनकर मुझे बहुत खुशी हूँई" (No substantial omission)
- **Objective Checks Passed**:
  - [x] Reference duration within range (9.4s)
  - [x] Reference file & audition file hash verified
  - [x] ASR content omission check passed
  - [x] Single speaker turn detected by diarization (SPEAKER_00, 3.66s–7.10s)
- **Current Status**:
  - Gates 5–7 (Clone similarity, Naturalness, Dialogue content): **Accepted by user** in Voice Library.
  - Gates 1–4 (Single speaker, Speech present, Background clean, Character identity): **Identity & background unverified**.
- **Separate Review Questions**:
  - *Q1.1 (Background & Speaker)*: Listening to the reference at 66:53, is it clean of background music/noise and strictly a single speaker?
  - *Q1.2 (Character Identity)*: Does this voice correspond to Sathyam's character in the Hindi dub?

---

### 2. `char_03_anand_action_ntr`
- **Character Role**: Anand - Furious Action Mode (आनंद - आक्रोश)
- **On-Screen Actor**: Jr NTR | **Voice Performer**: Hindi Dubbing Artist (theatrical dub)
- **Movie Scene & Timecode**: `61:57 - 62:06` (3717.6s – 3726.8s). Monologue warning at construction site.
- **Reference Audio**: [`storage/default_voice_bank/candidate_voices/char_03_anand_action_ntr.wav`](file:///mnt/c/Users/su936/OneDrive/Desktop/OpenDub-Studio/storage/default_voice_bank/candidate_voices/char_03_anand_action_ntr.wav)
  - **Ref SHA256**: `7745cb1b573d872175b3119148ceb167f2cd69eea1431fd6f933f555c6f32994`
  - **Duration**: 9.2s (Passes 3–10s gate)
  - **Spoken Text**: "दो मिनट का टाइम देता हूँ। अपने ट्रक, टेम्पो, क्रेन साइट से हटाओ और दफा हो जाओ।"
- **Audition Audio (Accepted Take)**: [`runtime/voice-bank-audit/clones/char_03_anand_action_ntr.wav`](file:///mnt/c/Users/su936/OneDrive/Desktop/OpenDub-Studio/runtime/voice-bank-audit/clones/char_03_anand_action_ntr.wav)
  - **Audition SHA256**: `3fc5506e3c2b8ffa613c69bab58126ee0d5c1f6315b066b3f1e140d0c270e989`
  - **Requested Text**: "आज हम मिलकर एक नई शुरुआत करेंगे। आपकी बात सुनकर मुझे बहुत खुशी हुई।"
  - **ASR Transcript**: "अज हम मिलकर एक नहीं शुर्वाद करेंगे, अपकी बाद सुनकर मुझे बहुत खुषी हूँई" (No substantial omission)
- **Objective Checks Passed**:
  - [x] Reference duration within range (9.2s)
  - [x] Reference file & audition file hash verified
  - [x] ASR content omission check passed
  - [x] Single speaker turn detected by diarization (SPEAKER_00, 4.57s–9.26s)
- **Current Status**:
  - Gates 5–7 (Clone similarity, Naturalness, Dialogue content): **Accepted by user** in Voice Library.
  - Gates 1–4 (Single speaker, Speech present, Background clean, Character identity): **Identity & background unverified**.
- **Separate Review Questions**:
  - *Q2.1 (Background & Speaker)*: Listening to the reference at 61:57, is it free of action/site sound effects and music bleed?
  - *Q2.2 (Character Identity)*: Does this voice match Anand's action dialogue delivery in the Hindi dub?

---

### 3. `char_09_anu_nithya_menen`
- **Character Role**: Anu (अनु) — Second Female Lead
- **On-Screen Actor**: Nithya Menen | **Voice Performer**: Hindi Dubbing Artist
- **Movie Scene & Timecode**: `92:51 - 92:58` (5571.0s – 5578.2s). Conversational dialogue outside the house.
- **Reference Audio**: [`storage/default_voice_bank/candidate_voices/char_09_anu_nithya_menen.wav`](file:///mnt/c/Users/su936/OneDrive/Desktop/OpenDub-Studio/storage/default_voice_bank/candidate_voices/char_09_anu_nithya_menen.wav)
  - **Ref SHA256**: `73186fe8d02c84c3e27e8c9fe75c7f9b237ddc596da2aae4f06b0a0f3dde2ea4`
  - **Duration**: 7.2s (Passes 3–10s gate)
  - **Spoken Text**: "जनता गराज वाला हर प्रॉब्लम सॉल्व करता है। मेरी भी प्रॉब्लम है। वो तभी सॉल्व होगी जब"
- **Audition Audio (Accepted Take)**: [`runtime/voice-bank-audit/clones/char_09_anu_nithya_menen.wav`](file:///mnt/c/Users/su936/OneDrive/Desktop/OpenDub-Studio/runtime/voice-bank-audit/clones/char_09_anu_nithya_menen.wav)
  - **Audition SHA256**: `b3b0f316f9a90a20da0db744b21776d712d66c0288fc52ebdf74b28765462fd8`
  - **Requested Text**: "आज हम मिलकर एक नई शुरुआत करेंगे। आपकी बात सुनकर मुझे बहुत खुशी हुई।"
  - **ASR Transcript**: "आज हम मिलकर एक नहीं शुर्वात करेंगे आपकी बाद सुनकर मुझे बहुत खॉशी हूँई" (No substantial omission)
- **Objective Checks Passed**:
  - [x] Reference duration within range (7.2s)
  - [x] Reference file & audition file hash verified
  - [x] ASR content omission check passed
  - [x] Single speaker verified across all 3 speech segments
- **Current Status**:
  - Gates 5–7 (Clone similarity, Naturalness, Dialogue content): **Accepted by user** in Voice Library.
  - Gates 1–4 (Single speaker, Speech present, Background clean, Character identity): **Identity & background unverified**.
- **Separate Review Questions**:
  - *Q3.1 (Background & Speaker)*: Listening to the reference at 92:51, is the background clean of ambient or music bleed?
  - *Q3.2 (Character Identity)*: Does this voice belong to Anu in the Hindi dub?

---

### 4. `char_12_anu_mother_anitha`
- **Character Role**: Anu's Mother (अनु की माँ)
- **On-Screen Actor**: Anitha Chowdary | **Voice Performer**: Hindi Dubbing Artist
- **Movie Scene & Timecode**: `93:16 - 93:26` (5596.4s – 5606.7s). Interior of commissioner's residence.
- **Original Audit Finding**: `multiple_speakers` (Commissioner interrupts; individual turns < 2.5s).
- **Previous Automatic Repairs (Identity Unverified / Mismatched)**:
  - *Candidate 0* (`context-30`, `SPEAKER_00`): Male voice ("वहां पोलिटिकल प्रेशर बहुत ज्यादा था सर..."). **Identity unverified / not Anu's mother**.
  - *Candidate 1* (`context-30`, `SPEAKER_02`): Younger female voice outside ("लोग कहते हैं कि जनता गराज वाला..."). **Identity unverified / likely Anu (`char_09`)**.
  - *Candidate 2* (`context-8`, `SPEAKER_01`): Same male voice.
- **Newly Prepared Clean Slice (Candidate 3)**:
  - **File**: [`runtime/voice-bank-audit/repairs/char_12_anu_mother_anitha/18f90471dd23-exclusive-speaker01/SPEAKER_01-reference-1010-5650.wav`](file:///mnt/c/Users/su936/OneDrive/Desktop/OpenDub-Studio/runtime/voice-bank-audit/repairs/char_12_anu_mother_anitha/18f90471dd23-exclusive-speaker01/SPEAKER_01-reference-1010-5650.wav)
  - **Ref SHA256**: `feb7d3840e943d38e7e21109b530ebe92da72275b9a1ba72997b8dd9d2c24051`
  - **Duration**: 4.64s (within 3–10s range)
  - **Spoken Text**: "मुझे लगा नैना कॉफ़ी लेकर आएगी... उसे बुलाइए ना सर..."
  - **Context**: Sliced from 1.01s to 5.65s of the original excerpt, ending immediately before the Commissioner speaks.
- **Current Status**: Candidate prepared for review; no audition synthesized yet; identity provisional.
- **Separate Review Questions**:
  - *Q4.1 (Reference Listening)*: Listening to the newly sliced reference (`SPEAKER_01-reference-1010-5650.wav`), is it strictly a single speaker with clean background?
  - *Q4.2 (Character Confirmation)*: Does this voice belong to Anu's mother in that scene?

---

### 5. `char_20_saidulu_banerjee`
- **Character Role**: Saidulu (सैदुलु) — Antagonist Partner / Builder
- **On-Screen Actor**: Banerjee | **Voice Performer**: Hindi Dubbing Artist
- **Movie Scene & Timecode**: `6:03.6 - 6:13.6` (363.6s – 373.6s). Heated debate in CM / Minister's office regarding slum project.
- **Candidate 3 (`1d26be8ed835-context-30`, `SPEAKER_03`)**:
  - **Ref Audio**: [`runtime/voice-bank-audit/repairs/char_20_saidulu_banerjee/1d26be8ed835-context-30/SPEAKER_03-reference-26018-36018.wav`](file:///mnt/c/Users/su936/OneDrive/Desktop/OpenDub-Studio/runtime/voice-bank-audit/repairs/char_20_saidulu_banerjee/1d26be8ed835-context-30/SPEAKER_03-reference-26018-36018.wav)
  - **Ref SHA256**: `d7df7902e4d0d0c3eb1bc7e8e50b73c4dfbfb597753e839e94ce6992d9d1b0f5` (10.0s)
  - **Ref Spoken Text**: "इस बात को हमें यही ख़तन करना बड़ेगा बाकी किसी को कोई प्रोडम नहीं और आप एक मेकनिक की बात सुनके प्रोजेक लोज कर रहे हैं..."
  - **Audition Audio**: [`runtime/voice-bank-audit/repairs/char_20_saidulu_banerjee/1d26be8ed835-context-30/SPEAKER_03-reference-26018-36018-clone.wav`](file:///mnt/c/Users/su936/OneDrive/Desktop/OpenDub-Studio/runtime/voice-bank-audit/repairs/char_20_saidulu_banerjee/1d26be8ed835-context-30/SPEAKER_03-reference-26018-36018-clone.wav)
  - **Audition SHA256**: `f081b6bd97584c7b8d810a9058b885da812f85764d99436dafd24fa10e3eb536`
- **Candidate 4 (`1d26be8ed835-context-8`, `SPEAKER_00`)**:
  - **Ref Audio**: [`runtime/voice-bank-audit/repairs/char_20_saidulu_banerjee/1d26be8ed835-context-8/SPEAKER_00-reference-4030-14030.wav`](file:///mnt/c/Users/su936/OneDrive/Desktop/OpenDub-Studio/runtime/voice-bank-audit/repairs/char_20_saidulu_banerjee/1d26be8ed835-context-8/SPEAKER_00-reference-4030-14030.wav)
  - **Ref SHA256**: `0fd9a9fc0cfd93cf0e6d601b3ebc9c1b72a4c28f08a554a93c9d7499aa375a02` (10.0s)
  - **Ref Spoken Text**: Same turn isolated in 8s context window.
  - **Audition Audio**: [`runtime/voice-bank-audit/repairs/char_20_saidulu_banerjee/1d26be8ed835-context-8/SPEAKER_00-reference-4030-14030-clone.wav`](file:///mnt/c/Users/su936/OneDrive/Desktop/OpenDub-Studio/runtime/voice-bank-audit/repairs/char_20_saidulu_banerjee/1d26be8ed835-context-8/SPEAKER_00-reference-4030-14030-clone.wav)
  - **Audition SHA256**: `03c91ba0d22e756855ddfe6235b2e3f5cb684c1737e6f6cb56ecdbcf9ef961e9`
- **Current Status**: Both candidates provisionally represent Saidulu's dialogue turn; identity unverified pending listening.
- **Separate Review Questions**:
  - *Q5.1 (Character Confirmation)*: Does the reference dialogue at 6:03–6:13 match the character Saidulu in the Hindi dub?
  - *Q5.2 (Candidate Comparison)*: Comparing the auditions for Candidate 3 and Candidate 4, which take produces better acoustic fidelity and natural delivery?
