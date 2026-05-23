from queries.models import QueryScenario

QUERY_B_TOKYO = QueryScenario(
    name="query_b_tokyo",
    display_name="Query B - Tokyo Activities + Weather",
    query_text=(
        "Find 3 family-friendly things to do in Tokyo this weekend. "
        "Check Saturday's weather forecast there and tell me which one is most appropriate."
    ),
    query_type="search_plus_contextual_choice",
    expected_iterations=4,
    max_pass_iterations=12,
    metadata={
        "goal_count_hint": 3,
        "context": {
            "city": "Tokyo",
            "time_window": "this weekend",
            "target_day": "Saturday",
            "search_blocked_domains": [
                "accuweather.com",
                "timeanddate.com",
            ],
            "weather_search": {
                "blocked_domains": [
                    "accuweather.com",
                    "timeanddate.com",
                ],
                "avoid_bot_protected_domains": True,
            },
            "steering_goal_sequence": [
                "activities_discovery_and_source_read",
                "saturday_weather_retrieval",
                "weather_conditioned_activity_selection",
            ],
            "task_structure": [
                "activities_source_fetch",
                "saturday_weather_fetch",
                "weather_conditioned_recommendation",
            ],
            "memory_carryover": {
                "between_goals": [
                    "saturday_weather_fact -> final_recommendation_reasoning",
                ],
            },
            "goal_completion_requirements": {
                "activities_goal_requires_source_read": True,
                "weather_goal_requires_forecast_read": True,
                "recommendation_goal_requires_activity_and_weather_evidence": True,
            },
            "required_outputs": [
                "three family friendly activities",
                "saturday weather forecast",
                "most appropriate activity recommendation",
            ],
        },
        "preferences": {
            "require_tool_evidence_before_answer": True,
            "weather_search_blocked_domains": [
                "accuweather.com",
                "timeanddate.com",
            ],
            "prefer_activity_source_read_before_weather_lookup": True,
            "prefer_single_activity_source_with_multiple_options": True,
            "prefer_weather_fact_before_recommendation": True,
            "prefer_sequential_goal_completion": True,
            "prefer_memory_carryover_between_weather_and_recommendation": True,
            "prefer_goal_texts_with_read_and_synthesize_verbs": True,
            "prefer_attaching_activity_and_weather_evidence_for_recommendation": True,
            "prefer_final_recommendation_as_answer_not_new_search": True,
            "avoid_prior_knowledge_without_run_evidence": True,
        },
        "answer_style": "short_numbered_list_with_weather_reasoning",
    },
)
