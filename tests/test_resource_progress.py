import pytest
from backend.resource_plan import plan_resources
from backend.work_progress import record_work, read_work

GIB = 1024**3

def report(ram=8, disk=100, cuda=False, vram=4096):
    return {"system":{"logical_cpu_count":12,"physical_cpu_count":6},"memory":{"available_bytes":ram*GIB},"disk":{"free_bytes":disk*GIB},"gpu":{"available":True,"devices":[{"vram_free_mb":vram}]},"acceleration":{"asr_cuda":cuda,"separation_cuda":cuda}}

def test_detected_gpu_without_runtime_is_not_used():
    plan = plan_resources(report(), duration_sec=18000)
    assert plan["asr_device"] == "cpu"
    assert plan["separation_device"] == "cpu"
    assert plan["heavy_workers"] <= 2
    assert plan["cpu_threads_per_worker"] * plan["heavy_workers"] <= 10

def test_small_gpu_admits_one_heavy_worker():
    plan = plan_resources(report(cuda=True))
    assert plan["asr_device"] == "cuda"
    assert plan["heavy_workers"] == 1

def test_low_resources_block_new_work():
    assert not plan_resources(report(ram=1))["admitted"]
    assert not plan_resources(report(disk=5), duration_sec=18000)["admitted"]


def test_completed_analysis_does_not_require_asr_ram_for_timing_resume():
    plan = plan_resources(report(ram=4), duration_sec=84, workload='speech')
    assert plan['admitted']
    assert plan['required_available_ram_bytes'] < 4 * GIB
    assert plan['speech_workers'] == 1
    assert not plan_resources(report(ram=1), workload='speech')['admitted']

def test_unknown_resources_do_not_claim_capacity():
    assert not plan_resources({})["admitted"]


def test_fit_resume_uses_clip_memory_without_loading_speech_models():
    plan = plan_resources(report(ram=2.1), duration_sec=3906.816, workload='fit')
    assert plan['admitted']
    assert plan['required_available_ram_bytes'] <= 2 * GIB
    assert plan['heavy_workers'] == 0
    assert not plan_resources(report(ram=.5), workload='fit')['admitted']

def test_separation_workload_admits_with_bounded_ram():
    plan = plan_resources(report(ram=2.5), duration_sec=3906.816, workload='separation')
    assert plan['admitted']
    assert plan['required_available_ram_bytes'] == 2 * GIB
    assert plan['heavy_workers'] == 1
    assert plan['speech_workers'] == 0
    assert not plan_resources(report(ram=1.5), workload='separation')['admitted']


def test_long_duration_and_large_model_include_memory_headroom():
    long_plan = plan_resources(report(ram=6), duration_sec=18000)
    assert not long_plan["admitted"]
    assert long_plan["required_available_ram_bytes"] > 6 * GIB
    assert not plan_resources(report(ram=8), model_size="large-v3")["admitted"]
    assert plan_resources(report(ram=16), duration_sec=18000)["admitted"]

def test_live_progress_and_eta_are_measured_and_resume_does_not_rewind(tmp_path):
    record_work(tmp_path,"transcription",0,10,now=100)
    assert read_work(tmp_path)["eta_seconds"] is None
    record_work(tmp_path,"transcription",5,10,now=110)
    middle=read_work(tmp_path)
    assert 10 < middle["overall_percent"] < 30
    assert middle["eta_seconds"] == 10
    record_work(tmp_path,"fit",23,46,now=120)
    previous=read_work(tmp_path)["overall_percent"]
    record_work(tmp_path,"synthesis",0,46,now=130)
    assert read_work(tmp_path)["overall_percent"] >= previous


def test_separation_parallel_capacity_scales_and_clamps_custom_count():
    small=plan_resources(report(ram=16,cuda=True,vram=4096),workload='separation',requested_workers=20)
    assert small['heavy_workers']==1
    large=report(ram=128,cuda=True,vram=81920)
    large['system']['logical_cpu_count']=64
    plan=plan_resources(large,workload='separation',requested_workers=20)
    assert plan['heavy_workers']==20 and len(plan['separation_slots'])==20
    assert plan['cpu_threads_per_worker']*20<=62


def test_multiple_cuda_cards_get_independent_worker_slots():
    data=report(ram=32,cuda=True)
    data['gpu']['devices']=[{'vram_free_mb':4096,'uuid':'GPU-first'},{'vram_free_mb':8192,'uuid':'GPU-second'}]
    plan=plan_resources(data,workload='separation')
    assert plan['heavy_workers']==3
    assert [slot['cuda_device'] for slot in plan['separation_slots']]==['GPU-first','GPU-second','GPU-second']


def test_extra_workers_are_limited_by_host_ram_even_with_large_gpu():
    data=report(ram=4,cuda=True,vram=81920)
    data['system']['logical_cpu_count']=64
    plan=plan_resources(data,workload='separation',requested_workers=20)
    assert plan['heavy_workers']<20


def test_resume_speech_and_fit_do_not_reserve_analysis_storage_again():
    data=report(ram=8,cuda=True)
    data['disk']['free_bytes']=6*1024**3
    for workload in ('speech','fit'):
        plan=plan_resources(data,3907,350*1024**2,workload=workload)
        assert plan['admitted'],plan['reasons']
        assert plan['required_free_disk_bytes']>=4*1024**3
