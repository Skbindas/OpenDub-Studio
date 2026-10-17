# JANTA GARAGE voice bank: measured audit status

3 October 2026. All 42 catalog entries now have genuine Hindi auditions. Catalog labels are not verified actor identities or a count of 42 unique speakers.

23 original-reference auditions and 32 repaired-speaker auditions are retained. 42/42 entries have at least one hash-verified candidate with no substantial speech omission detected by local ASR. This is supporting content evidence, not a pronunciation or voice-similarity certificate.

The current char_01, char_03 and char_09 auditions were accepted by the user and preserved by exact output hashes. No default bank switch or deletion of legacy voices has occurred.

## Per-entry delivery evidence

| ID | Original duration | Original audit | Original auditions | Repaired auditions | Content candidates* | Listening acceptance |
|---|---:|---|---:|---:|---:|---|
| char_01_sathyam_mohanlal | 9.4s | single_speaker_candidate | 1 | 0 | 1 | accepted take retained |
| char_02_anand_jr_ntr | 10.5s | single_speaker_candidate | 0 | 1 | 1 | pending |
| char_03_anand_action_ntr | 9.2s | single_speaker_candidate | 1 | 0 | 1 | accepted take retained |
| char_04_shankar_brahmaji | 11.5s | single_speaker_candidate | 0 | 1 | 1 | pending |
| char_05_bose_ajay | 9.2s | rejected_no_speech | 0 | 1 | 1 | pending |
| char_06_suresh_suresh | 4.0s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_07_shiva_rahman | 11.2s | single_speaker_candidate | 0 | 1 | 1 | pending |
| char_08_bujji_samantha | 11.7s | single_speaker_candidate | 0 | 1 | 1 | pending |
| char_09_anu_nithya_menen | 7.2s | single_speaker_candidate | 1 | 0 | 1 | accepted take retained |
| char_10_padma_devayani | 8.5s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_11_mother_sithara | 8.5s | single_speaker_candidate | 1 | 1 | 1 | pending |
| char_12_anu_mother_anitha | 10.3s | multiple_speakers | 0 | 3 | 3 | pending |
| char_13_riya_rana_vidisha | 5.9s | needs_review | 0 | 1 | 1 | pending |
| char_14_dinesh_mother_rajitha | 8.5s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_15_vikas_wife_meena | 12.4s | single_speaker_candidate | 0 | 1 | 1 | pending |
| char_16_bangaram_kajal | 11.0s | single_speaker_candidate | 0 | 2 | 2 | pending |
| char_17_mukesh_rana_sachin | 6.6s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_18_raghava_unni_mukundan | 17.2s | single_speaker_candidate | 0 | 1 | 1 | pending |
| char_19_satpal_yadav_john_kokken | 6.5s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_20_saidulu_banerjee | 6.2s | multiple_speakers | 0 | 5 | 5 | pending |
| char_21_home_minister_sharath | 7.4s | single_speaker_candidate | 1 | 1 | 1 | pending |
| char_22_partner_ashish_vidyarthi | 6.4s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_23_dinesh_kumar_ravi_prakash | 4.5s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_24_seena_aathma | 11.0s | needs_review | 0 | 2 | 2 | pending |
| char_25_henchman_sravan | 5.0s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_26_commissioner_sai_kumar | 10.5s | single_speaker_candidate | 0 | 1 | 1 | pending |
| char_27_dgp_chalapathi_rao | 8.5s | needs_review | 0 | 2 | 2 | pending |
| char_28_cm_vijayakumar | 6.4s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_29_ias_collector_appaji | 6.8s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_30_reddy_contractor_raghu | 3.0s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_31_vikas_mdo_rajiv | 10.2s | single_speaker_candidate | 0 | 1 | 1 | pending |
| char_32_ram_prasad_rao_ramesh | 11.9s | single_speaker_candidate | 0 | 1 | 1 | pending |
| char_33_surya_relative_surya | 4.7s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_34_corporate_boss_jeeva | 10.0s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_35_pyarelal_vennela_kishore | 3.3s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_36_college_narrator_friend | 11.1s | single_speaker_candidate | 0 | 1 | 1 | pending |
| char_37_vidhya_college_friend | 8.9s | single_speaker_candidate | 1 | 1 | 1 | pending |
| char_38_syed_sohel_classmate | 4.0s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_39_hospital_doctor_consultant | 7.7s | single_speaker_candidate | 1 | 0 | 1 | pending |
| char_40_garage_client_victim | 13.6s | single_speaker_candidate | 0 | 1 | 1 | pending |
| char_41_garage_elder_adviser | 8.5s | single_speaker_candidate | 1 | 1 | 1 | pending |
| char_42_police_inspector_officer | 7.4s | needs_review | 0 | 1 | 1 | pending |

*Content candidates passed the bounded omission check, not all review gates. The 23 original auditions include four suspect outputs kept for history/comparison; each of these entries now also has a repaired audition without that omission signal.

## Source repairs and content handling

- Original audit: 35 provisional single-speaker, 2 multiple-speaker, 1 no reliable speech, 4 requiring review. 14 original references were too long for the selected engine. All 42 original movie excerpts are retained.
- Real UVR separation and non-exclusive speaker analysis produced versioned 3–10 second exclusive speaker references. Competing speaker intervals are excluded. Different context versions remain available without overwriting originals; local speaker numbers do not establish actor identity.
- Four original auditions showed substantial missing dialogue. One bounded generation retry was insufficient. New separated references from expanded movie context produced complete two-sentence auditions under the same check; suspect originals remain preserved.
- Unicode-safe Hindi checks preserve vowel signs. Minor phonetic ASR differences are advisory; substantial missing speech blocks project publication while preserving the previous successful clip.
- Genuine auditions contain vocals. Final movie mixing uses the preserved original background stem at the original timeline. Auditions alone do not prove a feature-length cloned render or expression matching.

## Review and saved reuse

In Voice library, Load library and search an ID. Compare original movie excerpt, repaired reference and genuine repaired audition. Select Reference to review only after identifying the speaker. Review every requested word, reference cleanliness, similarity and naturalness. Exact reference transcript can be corrected; that invalidates stale clone eligibility until a matching audition is generated.

Selecting a repaired reference keeps its previous reference and clone in history, resets old review flags, and saves the selected reference for later voice assignment. Defaults require all seven review gates plus genuine generation and matching physical hashes/transcript. 0 verified defaults remain; legacy voices are retained until the entire target set passes.

## Runtime and measured time

OmniVoice 0.2.1 runs in an isolated CUDA environment; its audio tokenizer remains on CPU. One heavy worker and one reusable model load limit GPU/RAM pressure. The first warm batch generated 20 new auditions in 303 seconds and retained the three accepted takes. Source separation and speaker/ASR repairs take additional minutes per context; human review and expressive variants have no verified completion estimate.

## Verification and evidence

- Local regression: 305 Python tests passed, 2 skipped, 1 feature-length test deselected. A subsequently added selected-reference retention test passed in its focused suite. 7 Node frontend tests passed, including actual JSON review submission.
- Embedded browser: 42-entry library, repaired playback controls, reference selection/transcript changes, review guard and saved three-audition acceptance checked. Review without identity confirmation is rejected rather than replacing the reference.
- Private reports/media: runtime/voice-bank-audit/delivery-report.json, records/, repairs/, clones/, clones/history/. Exact media hashes and manifests remain local.
- Reproducible helpers: audit_movie_voice_bank.py, repair_voice_reference.py, clone_voice_batch_worker.py, clone_repaired_bank_worker.py, validate_clone_auditions.py --model small --include-repairs, retry_voice_bank_content.py. Completed clips resume by physical hash; accepted takes and previously attempted bounded retries are not repeatedly regenerated.

## Remaining review boundary

Confirm source identities and deduplicate speakers/style variants, correct uncertain reference words, listen for residual background and pronunciation, validate expression with real same-speaker references, then activate the replacement default bank. Do not remove old voices until those checks pass. Whole-movie cloned render and large-list virtualization remain separate planned work.
