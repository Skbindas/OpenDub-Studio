import json
import wave
import subprocess
import os
import shutil
import tempfile
import asyncio
import edge_tts
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')

proj = Path('runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917')

# All 28 segments with verified Chinese source and culturally refined, concise Hindi
dialogue_specs = [
    {
        "index": 0,
        "speaker_id": "SPEAKER_02",
        "character": "नेहा (Neha - सहेली)",
        "source_zh": "我问你个事。",
        "hindi_text": "एक बात पूछूँ?",
        "voice": "hi-IN-SwaraNeural", "pitch": "+8Hz", "rate": "+4%",
        "orig_start": 0.32, "orig_end": 1.07
    },
    {
        "index": 1,
        "speaker_id": "SPEAKER_02",
        "character": "नेहा (Neha - सहेली)",
        "source_zh": "我怎么才能让喜欢的男生知道我对他有意思啊？",
        "hindi_text": "अपने क्रश को कैसे बताऊँ कि मैं उसे पसंद करती हूँ?",
        "voice": "hi-IN-SwaraNeural", "pitch": "+8Hz", "rate": "+4%",
        "orig_start": 1.59, "orig_end": 4.28
    },
    {
        "index": 2,
        "speaker_id": "SPEAKER_01",
        "character": "प्रिया (Priya)",
        "source_zh": "这还不简单。",
        "hindi_text": "कितना आसान है!",
        "voice": "hi-IN-SwaraNeural", "pitch": "-4Hz", "rate": "-2%",
        "orig_start": 4.83, "orig_end": 5.53
    },
    {
        "index": 3,
        "speaker_id": "SPEAKER_02",
        "character": "नेहा (Neha - सहेली)",
        "source_zh": "怎么说？",
        "hindi_text": "कैसे?",
        "voice": "hi-IN-SwaraNeural", "pitch": "+8Hz", "rate": "+4%",
        "orig_start": 5.80, "orig_end": 6.18
    },
    {
        "index": 4,
        "speaker_id": "SPEAKER_01",
        "character": "प्रिया (Priya)",
        "source_zh": "男生都很自作多情，待会他跑累了过来，你就给他递瓶水。",
        "hindi_text": "लड़के बड़े इमोशनल होते हैं, वो थक कर आए तो पानी दे देना!",
        "voice": "hi-IN-SwaraNeural", "pitch": "-4Hz", "rate": "-2%",
        "orig_start": 6.59, "orig_end": 10.51
    },
    {
        "index": 5,
        "speaker_id": "SPEAKER_02",
        "character": "नेहा (Neha - सहेली)",
        "source_zh": "然后呢？",
        "hindi_text": "फिर क्या?",
        "voice": "hi-IN-SwaraNeural", "pitch": "+8Hz", "rate": "+4%",
        "orig_start": 11.18, "orig_end": 11.58
    },
    {
        "index": 6,
        "speaker_id": "SPEAKER_01",
        "character": "प्रिया (Priya)",
        "source_zh": "你一直盯着他看，再给他眨眨眼。",
        "hindi_text": "बस उसे देखती रहना, और आँख मार देना!",
        "voice": "hi-IN-SwaraNeural", "pitch": "-4Hz", "rate": "-2%",
        "orig_start": 11.83, "orig_end": 14.07
    },
    {
        "index": 7,
        "speaker_id": "SPEAKER_01",
        "character": "प्रिया (Priya)",
        "source_zh": "就这样，相信我。",
        "hindi_text": "बस, भरोसा रख!",
        "voice": "hi-IN-SwaraNeural", "pitch": "-4Hz", "rate": "-2%",
        "orig_start": 14.67, "orig_end": 15.65
    },
    {
        "index": 8,
        "speaker_id": "SPEAKER_01",
        "character": "प्रिया (Priya)",
        "source_zh": "快去。",
        "hindi_text": "जा, जल्दी!",
        "voice": "hi-IN-SwaraNeural", "pitch": "-4Hz", "rate": "-2%",
        "orig_start": 16.20, "orig_end": 16.53
    },
    {
        "index": 9,
        "speaker_id": "SPEAKER_02",
        "character": "नेहा (Neha - सहेली)",
        "source_zh": "同学，跑累了吧？",
        "hindi_text": "दौड़ते हुए थक गए ना?",
        "voice": "hi-IN-SwaraNeural", "pitch": "+8Hz", "rate": "+4%",
        "orig_start": 21.09, "orig_end": 22.09
    },
    {
        "index": 10,
        "speaker_id": "SPEAKER_02",
        "character": "नेहा (Neha - सहेली)",
        "source_zh": "给你水。",
        "hindi_text": "ये लो पानी!",
        "voice": "hi-IN-SwaraNeural", "pitch": "+8Hz", "rate": "+4%",
        "orig_start": 22.38, "orig_end": 22.92
    },
    {
        "index": 11,
        "speaker_id": "SPEAKER_03",
        "character": "रोहन (Rohan - छात्र)",
        "source_zh": "谢谢。",
        "hindi_text": "शुक्रिया!",
        "voice": "hi-IN-MadhurNeural", "pitch": "+0Hz", "rate": "+0%",
        "orig_start": 23.95, "orig_end": 24.36
    },
    {
        "index": 12,
        "speaker_id": "SPEAKER_03",
        "character": "रोहन (Rohan - छात्र)",
        "source_zh": "同学，你眼睛是不是不太舒服？",
        "hindi_text": "तुम्हारी आँखें ठीक तो हैं ना?",
        "voice": "hi-IN-MadhurNeural", "pitch": "+0Hz", "rate": "+0%",
        "orig_start": 35.03, "orig_end": 37.03
    },
    {
        "index": 13,
        "speaker_id": "SPEAKER_03",
        "character": "रोहन (Rohan - छात्र)",
        "source_zh": "要不我送你去医务室？",
        "hindi_text": "मेडिकल रूम चलें?",
        "voice": "hi-IN-MadhurNeural", "pitch": "+0Hz", "rate": "+0%",
        "orig_start": 37.52, "orig_end": 38.60
    },
    {
        "index": 14,
        "speaker_id": "SPEAKER_02",
        "character": "नेहा (Neha - सहेली)",
        "source_zh": "你才眼睛不舒服，你全家眼睛都不舒服。",
        "hindi_text": "तुम्हारी आँखें खराब हैं, तुम्हारे पूरे परिवार की!",
        "voice": "hi-IN-SwaraNeural", "pitch": "+8Hz", "rate": "+4%",
        "orig_start": 38.93, "orig_end": 41.40
    },
    {
        "index": 15,
        "speaker_id": "SPEAKER_03",
        "character": "रोहन (Rohan - छात्र)",
        "source_zh": "真奇怪。",
        "hindi_text": "बड़ी अजीब है!",
        "voice": "hi-IN-MadhurNeural", "pitch": "+0Hz", "rate": "+0%",
        "orig_start": 44.38, "orig_end": 45.02
    },
    {
        "index": 16,
        "speaker_id": "SPEAKER_02",
        "character": "नेहा (Neha - सहेली)",
        "source_zh": "你这办法不行啊，闺蜜。",
        "hindi_text": "तेरा तरीका फ्लॉप हो गया, सहेली!",
        "voice": "hi-IN-SwaraNeural", "pitch": "+8Hz", "rate": "+4%",
        "orig_start": 47.78, "orig_end": 49.03
    },
    {
        "index": 17,
        "speaker_id": "SPEAKER_01",
        "character": "प्रिया (Priya)",
        "source_zh": "不应该啊。",
        "hindi_text": "ऐसा तो नहीं होना चाहिए था!",
        "voice": "hi-IN-SwaraNeural", "pitch": "-4Hz", "rate": "-2%",
        "orig_start": 49.94, "orig_end": 51.10
    },
    {
        "index": 18,
        "speaker_id": "SPEAKER_01",
        "character": "प्रिया (Priya)",
        "source_zh": "有了。",
        "hindi_text": "आइडिया!",
        "voice": "hi-IN-SwaraNeural", "pitch": "-4Hz", "rate": "-2%",
        "orig_start": 51.98, "orig_end": 52.28
    },
    {
        "index": 19,
        "speaker_id": "SPEAKER_01",
        "character": "प्रिया (Priya)",
        "source_zh": "待会他跑回来，肯定满头都是汗。",
        "hindi_text": "वो दौड़कर वापस आएगा, तो पसीने से लथपथ होगा!",
        "voice": "hi-IN-SwaraNeural", "pitch": "-4Hz", "rate": "-2%",
        "orig_start": 55.67, "orig_end": 58.33
    },
    {
        "index": 20,
        "speaker_id": "SPEAKER_01",
        "character": "प्रिया (Priya)",
        "source_zh": "你拿这个，帮他擦汗。",
        "hindi_text": "तू इससे उसका पसीना पोंछ देना!",
        "voice": "hi-IN-SwaraNeural", "pitch": "-4Hz", "rate": "-2%",
        "orig_start": 58.33, "orig_end": 59.98
    },
    {
        "index": 21,
        "speaker_id": "SPEAKER_02",
        "character": "नेहा (Neha - सहेली)",
        "source_zh": "直接帮他擦。",
        "hindi_text": "सीधा पोंछ दूँ?",
        "voice": "hi-IN-SwaraNeural", "pitch": "+8Hz", "rate": "+4%",
        "orig_start": 61.32, "orig_end": 62.16
    },
    {
        "index": 22,
        "speaker_id": "SPEAKER_01",
        "character": "प्रिया (Priya)",
        "source_zh": "对。",
        "hindi_text": "हाँ!",
        "voice": "hi-IN-SwaraNeural", "pitch": "-4Hz", "rate": "-2%",
        "orig_start": 62.83, "orig_end": 63.04
    },
    {
        "index": 23,
        "speaker_id": "SPEAKER_02",
        "character": "नेहा (Neha - सहेली)",
        "source_zh": "靠谱吗？",
        "hindi_text": "पक्का?",
        "voice": "hi-IN-SwaraNeural", "pitch": "+8Hz", "rate": "+4%",
        "orig_start": 63.95, "orig_end": 64.38
    },
    {
        "index": 24,
        "speaker_id": "SPEAKER_01",
        "character": "प्रिया (Priya)",
        "source_zh": "偶像剧都是这么演的，嗯。",
        "hindi_text": "रोमांटिक सीरियल में यही तो दिखाते हैं!",
        "voice": "hi-IN-SwaraNeural", "pitch": "-4Hz", "rate": "-2%",
        "orig_start": 64.99, "orig_end": 66.77
    },
    {
        "index": 25,
        "speaker_id": "SPEAKER_02",
        "character": "नेहा (Neha - सहेली)",
        "source_zh": "你出了好多汗。",
        "hindi_text": "कितना पसीना आ गया!",
        "voice": "hi-IN-SwaraNeural", "pitch": "+8Hz", "rate": "+4%",
        "orig_start": 70.45, "orig_end": 71.41
    },
    {
        "index": 26,
        "speaker_id": "SPEAKER_03",
        "character": "रोहन (Rohan - छात्र)",
        "source_zh": "跑步当然会出汗。",
        "hindi_text": "दौड़ने पर तो पसीना आएगा ही!",
        "voice": "hi-IN-MadhurNeural", "pitch": "+0Hz", "rate": "+0%",
        "orig_start": 71.97, "orig_end": 73.16
    },
    {
        "index": 27,
        "speaker_id": "SPEAKER_02",
        "character": "नेहा (Neha - सहेली)",
        "source_zh": "闺蜜，这是真有用啊。",
        "hindi_text": "सहेली, ये तो सच में काम कर गया!",
        "voice": "hi-IN-SwaraNeural", "pitch": "+8Hz", "rate": "+4%",
        "orig_start": 81.57, "orig_end": 83.71
    }
]

with open('runtime/projects/53ba81b5-cc7c-4a68-944e-ff553456a917/analysis/dialogue_manifest_phase22_planned.json', 'w', encoding='utf-8') as f:
    json.dump(dialogue_specs, f, indent=2, ensure_ascii=False)

print("Saved dialogue_manifest_phase22_planned.json with all 28 dialogue specs.")
