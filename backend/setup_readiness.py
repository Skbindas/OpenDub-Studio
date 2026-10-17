"""Explain prerequisites without equating installed files with model success."""


def setup_status(report: dict, *, clone_environment: bool, separator_files: bool,
                 translation_configured: bool, owned_voices: int) -> dict:
    checks=[]
    def add(key,title,available,action):
        checks.append({'key':key,'title':title,'status':'available' if available else 'action_required',
                       'action':action})
    add('media','Video tools',all(report.get(k,{}).get('status')=='ok' for k in ('ffmpeg','ffprobe')),
        'Install FFmpeg and FFprobe, then reopen the launcher.')
    add('asr','Speech transcription',report.get('optional_modules',{}).get('faster_whisper',False),
        'Install the transcription dependencies in the Studio environment; model download/access is checked when used.')
    add('speakers','Speaker model access',report.get('integrations',{}).get('diarization_ready',False),
        'Use your own Hugging Face account to accept Community-1 conditions and configure access. Open System check for details.')
    add('clone','Local voice environment',clone_environment,
        'Set up the isolated cloning environment using the documented optional requirements, or deliberately choose Kaggle.')
    add('separator','Separator files',separator_files,
        'Acquire the documented separator checkpoint with its applicable terms. File presence is not a loaded-model test.')
    add('translation','Natural dialogue provider',translation_configured,
        'Configure your supported translation provider locally. Credentials are not part of this report.')
    add('voices','Your recording pack',owned_voices>0,
        'Add your own or permission-cleared recording in the voice library. Private movie examples are not a public default pack.')
    available=report.get('memory',{}).get('available_bytes')
    return {'status':'preview_required' if all(x['status']=='available' for x in checks) else 'setup_required',
            'checks':checks,'recommended_asr':'small','owned_reference_count':owned_voices,
            'available_ram_bytes':available,'gpu_allocation_verified':False,'model_loaded_verified':False,
            'notice':'Local prerequisite checklist. Installed files and account setup do not prove loaded models or quality. Kaggle has a separate explicit account/upload choice; run and listen to a short real preview.'}
