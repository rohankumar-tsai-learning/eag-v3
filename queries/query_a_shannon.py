from queries.models import QueryScenario

QUERY_A_SHANNON = QueryScenario(
    name="query_a_shannon",
    display_name="Query A - Shannon Wikipedia",
    query_text=(
        "Fetch https://en.wikipedia.org/wiki/Claude_Shannon and tell me his "
        "birth date, death date, and three key contributions to information theory."
    ),
    query_type="single_source_fact_extraction",
    expected_iterations=2,
    max_pass_iterations=6,
    metadata={
        "context": {
            "required_outputs": [
                "birth_date",
                "death_date",
                "three_key_contributions",
            ],
        },
    },
)
