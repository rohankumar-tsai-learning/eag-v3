from queries.models import QueryScenario

QUERY_C_MOM_RUN1 = QueryScenario(
    name="query_c_mom_run1",
    display_name="Query C Run 1 - Store Birthday + Reminders",
    query_text=(
        "My mom's birthday is 10 June 2026. Remember that and give me "
        "a calendar reminder for two weeks before and on the day."
    ),
    query_type="memory_write_with_reminders",
    expected_iterations=3,
    max_pass_iterations=8,
    metadata={
        "context": {
            "person": "mom",
            "event": "birthday",
            "event_date": "2026-06-10",
            "reminder_offsets_days": [14, 0],
        },
        "preferences": {
            "persistence": "durable_external_artifact",
            "location_hint": "reminders",
            "confirm_only_after_persistence": True,
        },
        "goal_count_hint": 3,
        "answer_style": "concise",
    },
)

QUERY_C_MOM_RUN2 = QueryScenario(
    name="query_c_mom_run2",
    display_name="Query C Run 2 - Recall Birthday",
    query_text="When is mom's birthday?",
    query_type="memory_recall",
    expected_iterations=1,
    max_pass_iterations=4,
    metadata={
        "context": {
            "person": "mom",
            "event": "birthday",
            "expected_source": "stored memory from prior run",
            "storage_location_hint": "reminders",
        },
        "preferences": {
            "answer_from_retrieved_evidence": True,
            "persistence": "reuse_existing_artifacts",
            "location_hint": "reminders",
        },
        "goal_count_hint": 2,
        "answer_style": "direct",
    },
)
