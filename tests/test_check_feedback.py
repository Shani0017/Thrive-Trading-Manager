from check_feedback import classify, new_submissions, _load_seen, _save_seen


def test_classify_bug_from_not_working_answer():
    assert classify({"What's this about?": "Something's not working right"}) == "bug"


def test_classify_bug_lowercase_variant():
    assert classify({"What's this about?": "there is a bug here"}) == "bug"


def test_classify_suggestion_from_idea_answer():
    assert classify({"What's this about?": "I have an idea / suggestion"}) == "suggestion"


def test_classify_other_for_anything_else():
    assert classify({"What's this about?": "Something else"}) == "other"


def test_classify_missing_field_defaults_to_other():
    assert classify({}) == "other"


def test_new_submissions_returns_all_rows_on_first_run(tmp_path):
    state_file = str(tmp_path / "state.json")
    rows = [{"Timestamp": "2026-01-01 10:00:00", "What's this about?": "A bug"}]
    assert new_submissions(rows, state_file) == rows


def test_new_submissions_skips_already_seen_rows(tmp_path):
    state_file = str(tmp_path / "state.json")
    rows = [{"Timestamp": "2026-01-01 10:00:00", "What's this about?": "A bug"}]
    new_submissions(rows, state_file)  # first run marks it seen
    assert new_submissions(rows, state_file) == []


def test_new_submissions_only_returns_the_new_ones(tmp_path):
    state_file = str(tmp_path / "state.json")
    old_row = {"Timestamp": "2026-01-01 10:00:00", "What's this about?": "A bug"}
    new_submissions([old_row], state_file)
    new_row = {"Timestamp": "2026-01-02 11:00:00", "What's this about?": "An idea"}
    assert new_submissions([old_row, new_row], state_file) == [new_row]


def test_new_submissions_ignores_rows_without_a_timestamp(tmp_path):
    state_file = str(tmp_path / "state.json")
    row = {"Timestamp": "", "What's this about?": "A bug"}
    assert new_submissions([row], state_file) == []


def test_load_seen_returns_empty_set_when_file_missing(tmp_path):
    assert _load_seen(str(tmp_path / "missing.json")) == set()


def test_save_then_load_seen_round_trips(tmp_path):
    state_file = str(tmp_path / "state.json")
    _save_seen({"a", "b"}, state_file)
    assert _load_seen(state_file) == {"a", "b"}
