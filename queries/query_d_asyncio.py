from queries.models import QueryScenario

QUERY_D_ASYNCIO = QueryScenario(
    name="query_d_asyncio",
    display_name="Query D - Asyncio Multi-source Synthesis",
    query_text=(
        "Search for 'Python asyncio best practices', read the top 3 results, "
        "and give me a short numbered list of the advice they agree on."
    ),
    query_type="multi_source_synthesis",
    expected_iterations=6,
    max_pass_iterations=12,
    metadata={
        "goal_count_hint": 4,
        "answer_style": "short_numbered_list",
    },
)
