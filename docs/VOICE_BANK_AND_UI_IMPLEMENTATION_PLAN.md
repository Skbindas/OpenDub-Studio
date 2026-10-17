# OpenDub Studio: JANTA GARAGE voice bank और UI upgrade plan

दिनांक: 3 अक्टूबर 2026 (Asia/Calcutta)

**स्थिति: उपयोगकर्ता ने इस योजना का विस्तार और implementation स्वीकृत किया है। दो चरणों में काम शुरू: पहले code/files, फिर वास्तविक media validation और end-to-end tests।**

## 0. स्वीकृत विस्तार: single-speaker, quality और expressive defaults

### चरण 1: code और सुरक्षित media workflow

- सभी 42 catalog records और अतिरिक्त assets का persistent per-file audit। Single speaker, sequential multiple speakers, simultaneous overlap, no speech और unknown स्पष्ट अलग statuses होंगे। ASR/VAD और diarization evidence साथ रखेंगे; background music को speech या pitch variation को दूसरा speaker नहीं मानेंगे।
- BGM/SFX-only या silence samples cloning library के लिए reject होंगे, लेकिन source/archive files delete नहीं करेंगे। Mixed clips के उसी movie timecode को दोबारा जाँचेंगे। Sequential turns को अलग crop करेंगे; overlap को single-speaker crop बताना मना है। Overlap में alternate clean timecode प्राथमिक उपाय; usable isolation न होने पर review, guessed clean claim नहीं।
- Engine की recommendation के अनुसार 3-10 seconds usable reference; लक्ष्य 8-10 seconds साफ़ single-speaker speech। 10 seconds से अधिक clip को reviewed speech boundaries पर नया version बनाएँगे। Transcript actual selected reference से match होगा।
- आवाज़ का perceived type (masculine/feminine/unknown), pitch/resonance/heavy/light और apparent age band review fields होंगे। Exact 2/3/10/15/30/40/50/60 वर्ष audio से प्रमाणित नहीं करेंगे। Child/adolescent/young-adult/middle-aged/older/unknown अनुमान की confidence और review status रखें; identity और वास्तविक उम्र से अलग। Catalog gender/age को unverified hint ही मानेंगे।
- Clone generation केवल वास्तविक reference-conditioned model से; neural/synthetic fallback कभी successful clone नहीं होगा। Global references, model prompt, generation engine/hash और auditions versioned होंगे।
- Identity और delivery अलग रखें: neutral/angry/romantic/sad आदि emotion तथा whisper/shout/soft delivery per dialogue रहे। चुने हुए provider की actual capabilities और audible pilot से तय होगा कि कौन-सा expression समर्थित है। Unsupported expression को silently applied न दिखाएँ। Same-speaker emotional variants को अलग व्यक्ति न बनाएँ।
- White UI में review/library cards, clean reference और generated clone audition, demographic review और actual readiness दिखेगी। पुरानी entries false verified labels नहीं दिखाएँगी।

### चरण 2: media परीक्षण, repair और promotion

- पहले सभी candidates की automated ASR/VAD/diarization जाँच, source timecode comparison और quality report; अच्छी references reuse, खराब references selective repair। Engine/model resource admission और एक-एक worker से laptop responsiveness रखें।
- पहले 2 distinct speakers का genuine clone pilot और expression/timing test, फिर eligible records के auditable jobs। Resume completed hashes/versions reuse करेगा। इसी measured pilot से total duration estimate निकालेंगे: remaining voices × median per-voice generation time + required repair/review/download time। अभी निश्चित “42 voices में X मिनट” दावा नहीं है।
- हर candidate का `verified / repair / rejected-no-speech / mixed-speaker / needs-review` परिणाम और अलग clone status होगा। 42 catalog entries को 42 unique voices होने का प्रमाण नहीं मानेंगे; duplicate identities या insufficient speech सामने आने पर actual count report करेंगे।
- सभी target voices वास्तविक listening/identity/expression checks में सफल होने के बाद approved bank को defaults में promote करेंगे। Extra पुराने defaults पहले recoverable archive में रखकर active selection से हटेंगे; existing project assignments और source originals नहीं मिटेंगे। Promotion से पहले removal नहीं होगा।
- आखिरी में regression tests, embedded-browser workflow, new-project/restart persistence, mix/export QA और GitHub workflows। विकास के छोटे correctness checks final media testing के विकल्प नहीं होंगे।

Official engine reference (checked 3 October 2026): [OmniVoice README](https://github.com/k2-fsa/OmniVoice) recommends 3-10 second references and persistent clone prompts. Its documented Python API returns audio arrays; the previous code's `output_file` assumption must be corrected. Hindi emotion support will be measured, not inferred from voice-design marketing.

## 1. उद्देश्य और निर्णय

JANTA GARAGE की उपलब्ध आवाज़ों को सुरक्षित रखते हुए जाँचना कि कौन-सी वास्तविक speaker references हैं, कौन-सी सही clone outputs हैं और किन्हें दोबारा निकालना या generate करना आवश्यक है। सत्यापित आवाज़ों को reusable global library में रखकर अलग-अलग फिल्मों के characters को assign करना है। वेबसाइट white theme में readable, व्यवस्थित और professional रहेगी। BGM/SFX preservation, duration fitting, resume और मौजूदा सफल export को regression से बचाना है।

**अभी सभी आवाज़ों को “perfect cloned” घोषित नहीं किया जा सकता। पूरी movie या सभी samples दोबारा process करना भी अभी उचित नहीं है। पहले प्रत्येक record का evidence-based निर्णय होगा।**

पहले `docs/TIMING_AND_VOICE_BANK_PLAN.md` में voice-bank की शुरुआती योजना मौजूद थी। यह नया दस्तावेज़ उसका विस्तृत reviewable विस्तार है, जिसमें वर्तमान evidence, UI audit, क्रम और acceptance criteria शामिल हैं। पिछली timing/resume implementation इस नई योजना की approval से अलग, पूरी हो चुकी है।

## 2. इस बार read-only जाँच में क्या मिला

| जाँच | परिणाम | इससे क्या सिद्ध होता है |
| --- | --- | --- |
| `candidate_voices/char_*.json` | 42 catalog records | Catalog मौजूद है; 42 अलग audible speakers सिद्ध नहीं होते |
| Candidate folder के सभी WAV | 50 files, सभी WAV header/frame metadata पढ़े जा सके | पुराने अतिरिक्त 8 samples भी हैं; इन्हें inventory से गायब नहीं करना है |
| SHA-256 comparison | 50 अलग byte hashes | Byte copies नहीं; एक speaker के अलग snippets फिर भी हो सकते हैं |
| WAV duration | 3.0 से 17.2 seconds | सभी samples लगभग 10 seconds नहीं हैं |
| Sample rates | सभी 24 kHz | Format consistency है; इससे noise/isolation सिद्ध नहीं होती |
| पुराने audit JSON | `CLEAN` / `PERFECT_SINGLE_SPEAKER` labels हैं | Labels को source comparison और listening के बिना प्रमाण नहीं मानेंगे |
| Jr NTR catalog sample | `char_02_anand_jr_ntr`, 10.5 sec, movie timecode 1414.5-1425.0 | Source location का दावा उपलब्ध है; audible identity verify करनी है |
| Cloning implementation | OmniVoice branch और neural timbre-matched fallback दोनों मौजूद | सामान्य voice को pitch/rate बदलना identity cloning का प्रमाण नहीं |
| वर्तमान `.venv` | `omnivoice` module नहीं मिला | इस environment में उपलब्ध OmniVoice zero-shot branch चलने की पुष्टि नहीं है |
| Studio synthesis endpoint | Configured character provider में अभी Piper स्वीकार करता है | Clone library को production dubbing route से जोड़ना बाकी है |
| Live embedded browser | White UI, completed test project, pipeline, dialogue और character forms उपलब्ध | Working foundation मौजूद है; नीचे usability upgrades प्रस्तावित हैं |

महत्वपूर्ण अंतर: इस movie की file Hindi-dubbed है। स्क्रीन पर दिखने वाला actor, film character और सुनाई देने वाला Hindi dubbing artist अलग पहचान हो सकते हैं। Actor-name catalog देखकर voice identity नहीं मानेंगे। Anand का सामान्य और action sample एक ही speaker के delivery variants भी हो सकते हैं; उन्हें दो अलग लोग नहीं गिनना है।

इस turn में सभी 50 samples का सुनकर मूल्यांकन, source movie के सभी timecodes का comparison या नया clone generation नहीं हुआ। इसलिए हर voice का final pass/fail अभी लंबित है।

## 3. मौजूदा संदर्भ files

- Source movie: `C:\Users\su936\OneDrive\Desktop\JR NTR Blockbuster Action Hindi Dubbed Full Movie JANTA GARAGE  Mohanlal, Samantha, Nithya Menen - Goldmines CineHub (720p, h264).mp4`
- Catalog: `storage/default_voice_bank/candidate_voices/all_extracted_characters_summary.json`
- Existing references: `storage/default_voice_bank/candidate_voices/`
- Historic reports: `storage/default_voice_bank/audit_results.json`, `audit_results_post_fix.json`
- Extraction/catalog code: `scripts/build_full_movie_cast_voice_bank.py`, `scripts/cluster_and_catalog_movie_characters.py`
- Clone and profiles: `backend/voice_cloning.py`, `backend/voice_profiles.py`, `backend/dubbing.py`
- Studio routes: `backend/app.py`; UI: `web/index.html`, `web/studio.js`, `web/styles.css`, `web/diagnostics.js`
- Existing regression starting point: `tests/test_movie_voice_bank_and_assignments.py`, `tests/test_studio_frontend.cjs`, timing/background/resume tests.

## 4. Voice-bank implementation: क्रम और verification

### V1. सुरक्षित inventory और provenance

नई audit utility/report से सभी 50 WAV और 42 catalog records reconcile होंगे। प्रति file hash, duration, format, catalog linkage, source timecode, original/generated category, extraction method और engine evidence दर्ज होंगे। पुराने catalog/audio/report overwrite नहीं होंगे। New report की schema/version होगी। Existing generated clone outputs या engine logs जहाँ उपलब्ध हों, उन्हें source references से अलग खोजेंगे और map करेंगे।

**Verify:** Missing/orphan/mismatched paths स्पष्ट हों; original file hashes unchanged हों; हर known asset report में आए; absent engine evidence को `unknown` लिखा जाए।

### V2. Source speaker और coverage की जाँच

पहले दर्ज timecodes के छोटे excerpts compare करेंगे, पूरी movie को तुरंत दोबारा नहीं चलाएँगे। Character/actor/Hindi voice identity को अलग fields में रखेंगे। Existing speaker turns/transcripts मिलें तो reuse करेंगे। गलत labels, same-speaker variants, mixed speakers और one-time/side characters की कमी दर्ज होगी। Movie-wide coverage के लिए existing analysis की completeness जाँचेंगे; अपर्याप्त होने पर resource budget के अनुसार missing ranges की chunked diarization होगी। केवल credited cast list से “हर बोलने वाला speaker मिल गया” नहीं कहा जाएगा।

**Verify:** हर reviewed reference में सही timecode, matching speech/transcript और speaker identity का evidence हो। Unknown कलाकार के लिए neutral stable speaker ID चलेगा। Same-speaker style variants अलग identity नहीं बनेंगे। Coverage report reviewed और unreviewed ranges अलग दिखाएगी।

### V3. Reference quality और selective repair

Measured decoding, silence, clipping, speech content और multi-speaker/background leakage indicators निकालेंगे; साथ में source और reference सुनकर निर्णय होगा। करीब 8-12 seconds का clean natural speech लक्ष्य होगा, जब पर्याप्त material उपलब्ध हो। ठीक sample रहने देंगे। Unsuitable sample की नई version बनेगी: alternative clean dialogue चुनना, vocals isolation करना या अलग single-speaker snippets combine करना; अलग आवाज़ें कभी combine नहीं होंगी। छोटा लेकिन साफ़ sample चुने हुए engine के लिए usable हो तो केवल duration के कारण reject नहीं होगा।

**Verify:** Reference और source audition, पूरी speech intact, no obvious second-speaker contamination; processing artifacts और remaining BGM report हों। Noise metric अकेले identity या purity को certify नहीं करेगा। Original revisions recoverable रहें।

### V4. वास्तविक Hindi cloning engine की feasibility

Installed engine/model/cache और CPU/GPU/RAM/VRAM/storage जाँचना है। एक genuinely reference-conditioned Hindi-capable engine का documented support, license, model size, Windows compatibility और measured runtime compare करना है। Provider चुनने से पहले official documentation verify होगी; अभी इस plan में engine का final चुनाव नहीं है। छोटे verified sample से proof-of-concept होगा, फिर बाकी bank पर काम बढ़ेगा। Model downloads और workers resource plan के भीतर चलेंगे।

`backend/voice_cloning.py` में engine वास्तव में कौन चला, reference का इस्तेमाल हुआ या नहीं, failure और fallback का सत्य status persist होगा। Clone mode में stock/Piper/Edge fallback को successful clone नहीं बताया जाएगा। User द्वारा चुने हुए सामान्य voice mode को अलग label मिलेगा।

**Verify:** Reference conditioning का actual execution evidence, model/version/reference hash/output manifest हों। Unavailable/failed clone engine स्पष्ट actionable error दे और checkpoints रखे। False `completed`/`timbre_matched` assertions हटें।

### V5. Clone comparison और redo का निर्णय

पहले source-reference text और फिर नया Hindi test dialogue generate करेंगे। Reference बनाम output का audition, सही शब्द, identity similarity, naturalness, emotion और stability review होगा। Speaker embedding similarity उपलब्ध हो तो supplementary evidence होगी; universal guessed threshold से perfection घोषित नहीं करेंगे। अलग speakers के outputs में voice collapse और गलत assignments भी जाँचेंगे।

| स्थिति | कार्रवाई |
| --- | --- |
| Source reference सही, genuine clone और सुनने में सही | Reuse, फिर validated status |
| Source reference सही, clone output absent/fallback/खराब | Reference रखें; केवल clone regenerate |
| Reference गलत speaker/mixed/noisy | New reference version, फिर नया clone |
| Identity uncertain या insufficient source speech | Unverified रखें; automatic default न बनाएँ |
| Same speaker के कई delivery variants | एक identity के variants रखें; unique voice count न बढ़ाएँ |

**Verify:** हर record में pass/review/fail और concrete reason हो; पुराने assets retain हों। User audition review के बाद ही identity/naturalness approved default बने।

### V6. Global library और project assignments

Versioned global voice library में stable voice ID, verified display name, identity status, reference/hash/transcript, source provenance, provider, model/config, language, capabilities, delivery defaults और audition outputs रहें। Project character ID और global voice ID की mapping अलग persist होगी। Library edit अपने-आप पुराने project/render को न बदले। API credentials profiles में नहीं रखें। Misleading existing “Global Characters” project registry label/behavior की सीमा UI में स्पष्ट होगी।

**Verify:** Restart और new project के बाद saved voices/settings मिलें; unlimited custom characters और one-time speakers काम करें; arbitrary same-speaker aliases identity को न तोड़ें; missing reference/model पर clear error मिले।

### V7. Studio dubbing integration

`backend/app.py` synthesis provider dispatch को verified clone provider तक जोड़ना है। Per-character assignment सच में reference-conditioned output बनाए। Existing source-duration budget, measured fitting, atomic writes, resume policy, safe mixing और BGM/SFX unity-gain reuse लागू रहेगा। Provider/model/reference बदलने पर केवल dependent dialogue outputs invalidate हों; analysis/source retained रहें।

**Verify:** कम-से-कम दो अलग verified voices के साथ new-project Hindi dub; saved voice IDs/engine/output metadata match हों। Failure/restart/internet interruption के बाद completed upstream assets retained हों; fallback masquerading test fail हो; background और timing QA पास हो।

## 5. UI audit और प्रस्तावित design

Design direction: स्थानीय dubbing काम के लिए white production workspace; कम clutter, readable Hindi/English और सीमित अर्थपूर्ण रंग। Design variance 3/10, motion 2/10, density 5/10।

**वर्तमान UI का आधार सही है।** White surfaces, dark text, blue actions, teal success और red errors पहले से हैं। रंगों को messy rainbow बनाने की जरूरत नहीं। Full visual rewrite की जगह hierarchy, compact workflow और voice review को सुधारना है।

| वर्तमान स्थिति | सुधार | acceptance |
| --- | --- | --- |
| Manual workflow और Auto-Dub controls दोनों लंबे रूप में हैं | एक primary pipeline view, advanced/manual controls disclosure में | Primary action और stage/review/resume समझने के लिए duplicate workflow पढ़ना न पड़े |
| Dialogue में हर line के बहुत controls खुले हैं | Compact rows, selected-line inspector, search/filter by character/timing/review | Long movie में usable navigation; editing/revision features retained |
| छोटे clips के labels जैसे `00:00 - 00:00` | Subsecond timestamp और source/speech/fitted duration अलग दिखाएँ | Zero-duration जैसा भ्रम न हो; precision actual metadata से मिले |
| Provider settings हैं, लेकिन shared verified clone selection नहीं | Global voice library picker, Reference/Clone audition, status और capabilities | Real clone/stock/reference distinction visible; assigned voice persists |
| Names अभी generic/review-required हो सकते हैं | Character name + stable speaker ID + verified identity status | Actor guesses automatic न हों; custom names और variants स्पष्ट रहें |
| Progress में resume-run elapsed और छोटा checkpoint count दिखता है | Current attempt, retained total work और available ETA अलग label | पुराने पूरे काम का समय current resume time न लगे; unknown ETA ईमानदारी से दिखे |
| Preview अलग-अलग players में है | Matched source/reference/clone comparison controls और clear track labels | Seek/time context understandable; autoplay या fake waveforms नहीं |
| Setup और destructive actions साथ दिखाई देते हैं | Delete को secondary project menu, exact project name confirmation और recoverable archive affordance | Normal testing में delete trigger न हो; keyboard/focus से accidental deletion रोके |

### U1. रंग, typography और spacing

`web/styles.css` के existing tokens consolidate होंगे: white `#FFFFFF`, supporting surface `#F5F8FC`, primary blue `#2256C7`, success teal `#087C70`, review amber `#955A0C`, error red `#B93646`; dark readable text। Purple केवल voice-library grouping के लिए, status अर्थ न बदले। Proposed colors का actual text/control contrast मापा जाएगा। Hindi-appropriate font fallback, unclipped matras, heading/body scale और consistent spacing verify करेंगे। No OS-triggered dark theme।

**Verify:** Normal text contrast कम-से-कम 4.5:1, large text और meaningful control boundaries 3:1; focus visible; status केवल रंग पर निर्भर न हो।

### U2. Workflow layout और dialogue navigation

`web/index.html`, `web/studio.js` में compact pipeline, review counts, character filters और selected dialogue inspector बनाएँगे। Existing project data/forms/routes preserve होंगे। बड़ी lists के लिए pagination या measured virtualization चुनेंगे; unsaved edit protection और keyboard navigation साथ रखेंगे।

**Verify:** 25-line sample और generated long-list fixture पर navigation/edit/save/history काम करें; keyboard access, focus retention और no lost edits; desktop/tablet/narrow window में horizontal overflow न हो।

### U3. Library, auditions और provider states

Library UI में Verified, Review required, Reference only, Engine unavailable और Generation failed जैसी वास्तविक states होंगी। Source, reference और cloned audition स्पष्ट अलग हों। Provider/model language support दिखे; profile save को successful audio generation न समझाया जाए।

**Verify:** Search, custom names, multiple-character mapping, save/reload/new-project reuse और missing-model cases का embedded-browser test।

### U4. Measured audio graphics और motion

Existing measured spectrum रखें। Timing comparison/waveform तभी जोड़ें जब actual audio samples/metadata उपलब्ध हों। Neutral empty/loading states हों; fake progress/graphs नहीं। 120-180 ms छोटे disclosure transitions और `prefers-reduced-motion` support रखें। Heavy decorative 3D processing workspace में प्रस्तावित नहीं है: वह dubbing GPU/RAM से प्रतिस्पर्धा करेगा और इस समस्या को हल नहीं करता।

**Verify:** Reduced motion, keyboard interaction, playback में spectrum/waveform correctness और low-resource device पर responsiveness। Measured graph unavailable होने पर audio controls usable रहें।

## 6. execution order और milestones

1. **Approval received:** User ने plan update करके implementation शुरू करने को कहा; काम जारी है।
2. **Voice evidence:** V1-V3 से per-voice audit report और reuse/repair/unknown सूची।
3. **Single-engine pilot:** V4-V5 से दो अलग verified speakers के genuine Hindi clones; pilot failing होने पर bulk generation नहीं।
4. **Library integration:** V6-V7; UI का U3 इसी schema/capability के अनुसार।
5. **UI polish:** U1-U2-U4, existing white foundation preserve।
6. **End-to-end review:** वास्तविक project, logs, checkpoint retention, auditions, render QA।
7. **Delivery:** Approved implementation के tests पास होने पर GitHub push और सभी applicable workflows monitor/fix; audit में unverified voices बचें तो साफ़ report करें।

## 7. परीक्षण और सफलता की शर्तें

- Unit/integration tests: inventory reconciliation, clone/fallback truthful status, assignment persistence, dependent cache invalidation, interrupted generation और provider errors।
- Regression: वर्तमान timing, peak protection, BGM preservation, diagnostics cache, character registry और resume suites।
- केवल Codex embedded browser: pipeline, library audition, multiple characters, dialogue editing, review/resume, diagnostics और final playback। External browser नहीं।
- Viewports लगभग 1440/1024/768/390 px, keyboard-only, Hindi labels/matras, focus, overflow, reduced motion और measured contrast जाँच। Current turn का visual inspection narrow live viewport था; complete responsive accessibility certification अभी नहीं हुआ।
- Source comparison और human listening के बिना “perfect voice similarity” नहीं; automated metrics supporting evidence होंगे।
- Library में हर reviewed record का genuine engine evidence और reasoned status। सभी movie speakers covered कहने से पहले complete timeline/coverage evidence।
- New project/restart में settings और selected voice IDs बने रहें; source/previous successful assets सुरक्षित रहें।
- Final mix में dialogue coverage/timing/decode checks पास; background gain unchanged; audible artifacts अलग review किए जाएँ।

## 8. जोखिम और fallback

| जोखिम | प्रतिक्रिया |
| --- | --- |
| Catalog labels/timecodes गलत | Source evidence से relabel, original metadata revision retain |
| 42 entries unique speakers नहीं | Identity dedup और style variants; वास्तविक count report |
| Clean 10-sec speech नहीं मिलता | Engine-compatible shorter sample या safe same-speaker selection; unverified voice default नहीं |
| Clone engine unsupported/भारी | पहले छोटा measured pilot, compatible engine evaluation; clear unavailable state |
| Voice output अलग लगता है | Better reference/conditioning और regenerate only affected voice; stock substitution को clone न कहें |
| Long movie workload | Resource-budgeted chunks, one heavy worker as needed, retained manifests/resume |
| UI edits से data loss | Stable IDs, unsaved-state protection, regression और original project retained |

## 9. Implementation progress (3 October 2026)

- Phase 1 implemented: persistent audit, genuine isolated cloning worker, strict assignment/promotion checks, source comparison, versioned selective repairs and white voice-library review UI.
- Phase 2 automated audit complete: 42 references; 35 provisional single-speaker, 2 multiple-speaker, 1 no reliable speech, 4 requiring review. All 42 original movie excerpts recovered for comparison. No reference has been falsely marked verified.
- Final local regression: 305 Python tests passed, 2 skipped, 1 feature-length test deselected; a subsequently added repair-selection retention test passed in its focused suite. 7 Node tests passed, including JSON review submission. Unicode-safe content validation and publication checks pass.
- CPU pilot exposed slow CPU-only runtime. Isolated CUDA environment now passes pip check; three genuine GPU/CPU-split auditions completed, about 26-37 seconds full worker wall time. Content/identity/emotion review remains open; these are not certified defaults.
- Mixed-reference repairs are new versions; originals and completed test project remain intact. Identity, apparent demographics, clean-background listening and expression checks are still required before default activation.
- Legacy voices remain active until every target passes the promotion gate. No old voice removal or all-42-success claim has been made.
- Compact dialogue delivery disclosures, safe dialogue filtering and direct voice-library navigation implemented. All 42 catalog entries have audition coverage. Complete expressive-variant validation, larger-list virtualization and whole-movie cloned render QA remain tracked work. Commit db3215e passed GitHub workflow 37113154372; the final repair/review patch requires its own workflow verification.

See runtime/voice-bank-audit/report.json for machine findings. Reports and media remain local; this plan and implementation code can be reviewed independently.

## 10. Latest user review and batch scope

- Initial three auditions were rejected for missing words/pronunciation. Corrected reference transcripts and 64-step outputs were generated, preserving earlier versions.
- User subsequently listened to the current three and accepted their sound quality. Save that acceptance against current output hashes and retain these files; do not regenerate them.
- Hindi ASR normalization previously removed vowel signs. It now preserves Unicode letters and combining marks. Automatic transcripts remain supporting evidence, not an identity or pronunciation verdict.
- Before publishing a new project clone revision, run an offline content check; retain suspect new clips for review and preserve previous successful audio.
- Resume genuine bank auditions using one loaded model, with atomic per-voice checkpoints and no stock-voice replacement. Unsafe references remain explicit repair tasks.
- VoiceStudio review is recorded in VOICESTUDIO_COMPATIBILITY_REVIEW.md. Keep the accepted OmniVoice implementation; alternative-engine downloads are stopped because the accepted engine now satisfies the pilot.
- Vocal auditions deliberately exclude BGM. Final dubbed movies combine generated dialogue with the original preserved music/effects timeline.

## 11. Final 42-entry audition delivery and review boundary

- 23 original-reference auditions plus 32 repaired-speaker auditions are available; 42/42 catalog entries have at least one physical-hash-verified candidate with no substantial speech omission detected by local ASR. This does not establish 42 distinct actors or exact pronunciation.
- The first three accepted output hashes remain unchanged. Original references, earlier generations, suspect outputs and completed project files remain retained.
- Four original outputs still omitted dialogue after one bounded retry. Expanded movie-context separation produced new exclusive references and new auditions with both requested sentences detected. Future fixes must inspect source/reference evidence rather than loop through random seeds.
- Repaired references can be selected in the review form after explicit source identity confirmation. Previous reference state is retained; selected-reference review flags reset; subsequent saved voice assignments use the actual selected file.
- Review submission now sends application/json. Embedded-browser testing confirmed that selecting a repair updates its reference words and that saving without speaker identity confirmation is rejected without overwriting the reference.
- Hindi ASR minor phonetic differences remain supporting warnings. Missing large parts of speech block new project audio publication and preserve previously successful clips.
- Remaining manual gates: correct actor/source identity, residual background cleanliness, accurate reference transcript, similarity, naturalness, every requested word and perceived voice type/age-band review. All seven gates are required before default activation. No legacy defaults are removed before the entire replacement set passes.
- See VOICE_BANK_AUDIT_STATUS.md for per-ID evidence and VOICESTUDIO_COMPATIBILITY_REVIEW.md for the external repository decision. Media and exact hashes remain local under runtime/voice-bank-audit/delivery-report.json.
