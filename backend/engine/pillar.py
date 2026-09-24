PILLARS = {
    "onboard": {
        "id": "onboard",
        "name": "Pillar 1: Onboard",
        "key_tables": [
            "onboarding_kpi_detail",
            "onboarding_30_day_behavior",
            "onboarding_cut_intensity",
        ],
        "key_metrics": [
            "activation rate",
            "registration-to-first-cut",
            "canvas-to-cut conversion",
        ],
    },
    "trigger": {
        "id": "trigger",
        "name": "Pillar 2: Trigger Return",
        "key_tables": [
            "engagement_user_daily_dimensions",
            "engagement_cohorts",
        ],
        "key_metrics": ["DAU/WAU/MAU", "return rates", "session frequency"],
    },
    "content": {
        "id": "content",
        "name": "Pillar 3: Makeable Content",
        "key_tables": ["dim.image", "dim.project"],
        "key_metrics": [
            "image library metrics",
            "content availability",
            "project creation rates",
        ],
    },
    "matching": {
        "id": "matching",
        "name": "Pillar 4: Content Matching",
        "key_tables": [],
        "key_metrics": [
            "click-through rates",
            "content discovery",
            "search analytics",
        ],
    },
    "design_make": {
        "id": "design_make",
        "name": "Pillar 5: Design & Make",
        "key_tables": ["fact.content_workflow", "dim.content_workflow_status"],
        "key_metrics": [
            "cut completion rates",
            "session-to-cut conversion",
        ],
    },
    "guided": {
        "id": "guided",
        "name": "Pillar 5A: Guided Flows",
        "key_tables": [],
        "key_metrics": [
            "guided flow selection",
            "conversion funnels",
            "template usage",
        ],
    },
    "blank_canvas": {
        "id": "blank_canvas",
        "name": "Pillar 5B: Blank Canvas",
        "key_tables": [],
        "key_metrics": [
            "blank canvas conversion",
            "design complexity",
            "tool usage",
        ],
    },
    "platform": {
        "id": "platform",
        "name": "Data Platform",
        "key_tables": [],
        "key_metrics": [
            "pipeline performance",
            "data quality",
            "SLAs",
            "ingestion lag",
        ],
    },
}


def get_pillar(pillar_id: str | None) -> dict | None:
    if not pillar_id:
        return None
    return PILLARS.get(pillar_id)


def get_all_pillars() -> list[dict]:
    return list(PILLARS.values())
