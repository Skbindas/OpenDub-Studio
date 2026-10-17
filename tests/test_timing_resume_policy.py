from backend.pipeline import timing_fit_matches_policy


def test_stricter_slowdown_does_not_reuse_a_more_stretched_completed_take():
    unit={'duration_sec':1.,'timing':{'fit_policy_version':2,'target_duration_sec':1.,
          'status':'completed','applied_tempo':.82}}
    assert not timing_fit_matches_policy(unit,1.15,.9)
    unit['timing']['applied_tempo']=.98
    assert timing_fit_matches_policy(unit,1.15,.9)
    del unit['timing']['applied_tempo']
    assert not timing_fit_matches_policy(unit,1.15,.9)


def test_review_checkpoint_reuses_only_the_same_bound_policy():
    unit={'duration_sec':1.,'timing':{'fit_policy_version':2,'target_duration_sec':1.,
          'status':'needs_review','applied_tempo':1.25,'max_speedup':1.25,'max_slowdown':.82}}
    assert timing_fit_matches_policy(unit,1.25,.82)
    assert not timing_fit_matches_policy(unit,1.3,.82)
    assert not timing_fit_matches_policy(unit,1.15,.9)
