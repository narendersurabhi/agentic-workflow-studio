import json

from libs.core.llm_provider import LLMProvider, LLMResponse
from libs.core.tool_registry import default_registry


class ResumeAnalysisProvider(LLMProvider):
    def generate(self, prompt: str) -> LLMResponse:
        if "reference_only" in prompt and "ideal_resume_text" in prompt:
            return LLMResponse(
                content=json.dumps(
                    {
                        "reference_only": True,
                        "not_user_factual": True,
                        "ideal_resume_text": "Ideal Example Resume",
                        "ideal_resume_outline": ["Summary", "Skills", "Experience"],
                        "keyword_placement_notes": ["Put Python in summary"],
                        "evidence_examples": ["Built production AI workflows"],
                    }
                )
            )
        if "report_text" in prompt and "coverage_summary" in prompt:
            return LLMResponse(
                content=json.dumps(
                    {
                        "report_text": "Gap report text",
                        "section_recommendations": [
                            {
                                "section": "Skills",
                                "issues": ["Missing Kubernetes"],
                                "recommended_changes": ["Add verified deployment tooling"],
                            }
                        ],
                        "priority_actions": ["Strengthen skills section"],
                        "coverage_summary": {
                            "explicit_match_count": 1,
                            "implicit_match_count": 1,
                            "missing_requirement_count": 1,
                        },
                    }
                )
            )
        if "placement_summary" in prompt and "Skills to inject" in prompt:
            return LLMResponse(
                content=json.dumps(
                    {
                        "tailored_resume": {
                            "summary": "Python and Kubernetes engineer building agentic systems.",
                            "skills": [{"term": "Platforms", "definition": "Python, Kubernetes"}],
                        },
                        "applied_skills": ["Python", "Kubernetes"],
                        "placement_summary": [
                            {
                                "skill": "Python",
                                "sections": ["summary", "skills"],
                                "rationale": "High-priority language for the target role.",
                            },
                            {
                                "skill": "Kubernetes",
                                "sections": ["skills"],
                                "rationale": "Improves infrastructure keyword coverage.",
                            },
                        ],
                    }
                )
            )
        if "explicit_matches" in prompt and "section_gaps" in prompt:
            return LLMResponse(
                content=json.dumps(
                    {
                        "explicit_matches": ["Python"],
                        "implicit_matches": ["APIs"],
                        "missing_requirements": ["Kubernetes"],
                        "recommended_questions": ["Did you deploy to Kubernetes?"],
                        "section_gaps": ["Skills missing Kubernetes"],
                        "suggested_improvements": ["Add deployment evidence"],
                    }
                )
            )
        if "must_have_skills" in prompt and "role_summary" in prompt:
            return LLMResponse(
                content=json.dumps(
                    {
                        "must_have_skills": ["Python", "FastAPI"],
                        "preferred_skills": ["Kubernetes"],
                        "domain_terms": ["agentic ai"],
                        "seniority_signals": ["ownership"],
                        "required_outcomes": ["ship production systems"],
                        "role_summary": "Build and scale agentic workflows.",
                    }
                )
            )
        raise AssertionError(f"Unexpected prompt: {prompt}")


def test_default_registry_registers_resume_analysis_tools() -> None:
    registry = default_registry(llm_enabled=True, llm_provider=ResumeAnalysisProvider())
    specs = {spec.name for spec in registry.list_specs()}
    assert "jd_analyze" in specs
    assert "resume_example_generate" in specs
    assert "resume_gap_detect" in specs
    assert "resume_gap_report_generate" in specs
    assert "resume_skill_inject" in specs


def test_resume_analysis_tools_execute_with_structured_json_outputs() -> None:
    registry = default_registry(llm_enabled=True, llm_provider=ResumeAnalysisProvider())

    analyze = registry.execute(
        "jd_analyze",
        {"job_description": "Need Python and FastAPI. Kubernetes preferred."},
        "k1",
        "t1",
    )
    assert analyze.status == "completed"
    assert analyze.output_or_error["must_have_skills"] == ["Python", "FastAPI"]

    example = registry.execute(
        "resume_example_generate",
        {
            "job_description": "Need Python and FastAPI. Kubernetes preferred.",
            "jd_analysis": analyze.output_or_error,
            "target_role_name": "Applied AI Engineer",
        },
        "k2",
        "t2",
    )
    assert example.status == "completed"
    assert example.output_or_error["reference_only"] is True

    gaps = registry.execute(
        "resume_gap_detect",
        {
            "candidate_resume": "Python APIs and backend systems",
            "jd_analysis": analyze.output_or_error,
        },
        "k3",
        "t3",
    )
    assert gaps.status == "completed"
    assert gaps.output_or_error["missing_requirements"] == ["Kubernetes"]

    report = registry.execute(
        "resume_gap_report_generate",
        {
            "candidate_resume": "Python APIs and backend systems",
            "jd_analysis": analyze.output_or_error,
            "gap_detection": gaps.output_or_error,
        },
        "k4",
        "t4",
    )
    assert report.status == "completed"
    assert report.output_or_error["coverage_summary"]["missing_requirement_count"] == 1

    inject = registry.execute(
        "resume_skill_inject",
        {
            "tailored_resume": {
                "summary": "Engineer building agentic systems.",
                "skills": [{"term": "Platforms", "definition": "Docker"}],
            },
            "skills": ["Python", "Kubernetes"],
            "target_sections": ["summary", "skills"],
        },
        "k5",
        "t5",
    )
    assert inject.status == "completed"
    assert inject.output_or_error["applied_skills"] == ["Python", "Kubernetes"]
