from __future__ import annotations

import json
from typing import Any


def jd_analysis_prompt(job_description: str) -> str:
    return (
        "Analyze the following job description and return exactly one JSON object.\n\n"
        "Goal:\n"
        "Extract the hiring signals needed to tailor a strong resume.\n\n"
        "Return JSON with exactly these keys:\n"
        "- must_have_skills: string[]\n"
        "- preferred_skills: string[]\n"
        "- domain_terms: string[]\n"
        "- seniority_signals: string[]\n"
        "- required_outcomes: string[]\n"
        "- role_summary: string\n\n"
        "Rules:\n"
        "- Use only information supported by the job description.\n"
        "- Normalize overlapping items.\n"
        "- Keep arrays concise and high-signal.\n"
        "- Do not include markdown or prose outside JSON.\n\n"
        f"Job description:\n{job_description}"
    )


def resume_example_prompt(
    job_description: str,
    jd_analysis: dict[str, Any],
    target_role_name: str | None = None,
) -> str:
    analysis_json = json.dumps(jd_analysis, ensure_ascii=False, indent=2, default=str)
    role_line = f"Target role name: {target_role_name}\n\n" if target_role_name else ""
    return (
        "Generate an ideal example resume for reference only and return exactly one JSON object.\n\n"
        "Goal:\n"
        "Create a high-quality example resume that demonstrates:\n"
        "- full keyword coverage\n"
        "- strong structure\n"
        "- realistic evidence patterns\n"
        "- strong summary, skills, and experience bullet style\n\n"
        "This is NOT the candidate's factual resume.\n"
        "Do NOT claim it belongs to the candidate.\n"
        "Do NOT use candidate-specific facts.\n\n"
        "Return JSON with exactly these keys:\n"
        "- reference_only: boolean\n"
        "- not_user_factual: boolean\n"
        "- ideal_resume_text: string\n"
        "- ideal_resume_outline: string[]\n"
        "- keyword_placement_notes: string[]\n"
        "- evidence_examples: string[]\n\n"
        "Rules:\n"
        "- Set reference_only=true\n"
        "- Set not_user_factual=true\n"
        "- Make the resume look like an ideal strong applicant for this role.\n"
        "- Include realistic example evidence patterns, but keep them generic.\n"
        "- No markdown or prose outside JSON.\n\n"
        f"{role_line}"
        f"Job description:\n{job_description}\n\n"
        f"JD analysis:\n{analysis_json}"
    )


def resume_gap_detect_prompt(candidate_resume: str, jd_analysis: dict[str, Any]) -> str:
    analysis_json = json.dumps(jd_analysis, ensure_ascii=False, indent=2, default=str)
    return (
        "Compare the source resume against the analyzed job description and return exactly one JSON object.\n\n"
        "Goal:\n"
        "Identify what is clearly covered, what is partially implied, and what appears missing or under-emphasized.\n\n"
        "Return JSON with exactly these keys:\n"
        "- explicit_matches: string[]\n"
        "- implicit_matches: string[]\n"
        "- missing_requirements: string[]\n"
        "- recommended_questions: string[]\n"
        "- section_gaps: string[]\n"
        "- suggested_improvements: string[]\n\n"
        "Rules:\n"
        "- Use only the source resume and jd_analysis.\n"
        "- Prefer high-signal requirements over minor preferences.\n"
        "- Section gaps should mention sections like summary, skills, experience, certifications, education, links/projects.\n"
        "- recommended_questions should help recover omitted but plausible experience from the user.\n"
        "- No markdown or prose outside JSON.\n\n"
        f"JD analysis:\n{analysis_json}\n\n"
        f"Source resume:\n{candidate_resume}"
    )


def resume_gap_report_prompt(
    candidate_resume: str,
    jd_analysis: dict[str, Any],
    gap_detection: dict[str, Any],
) -> str:
    analysis_json = json.dumps(jd_analysis, ensure_ascii=False, indent=2, default=str)
    gap_json = json.dumps(gap_detection, ensure_ascii=False, indent=2, default=str)
    return (
        "Generate a candidate-specific resume improvement report and return exactly one JSON object.\n\n"
        "Goal:\n"
        "Turn the gap analysis into a practical improvement report the user can act on.\n\n"
        "Return JSON with exactly these keys:\n"
        "- report_text: string\n"
        "- section_recommendations: array of objects with keys:\n"
        "  - section: string\n"
        "  - issues: string[]\n"
        "  - recommended_changes: string[]\n"
        "- priority_actions: string[]\n"
        "- coverage_summary: object with keys:\n"
        "  - explicit_match_count: integer\n"
        "  - implicit_match_count: integer\n"
        "  - missing_requirement_count: integer\n\n"
        "Rules:\n"
        "- Provide concrete, section-specific recommendations.\n"
        "- Focus on summary, skills, experience, education, certifications, and links/projects where relevant.\n"
        "- priority_actions should be the highest-impact next edits.\n"
        "- report_text should read like a polished diagnostic document.\n"
        "- No markdown or prose outside JSON.\n\n"
        f"JD analysis:\n{analysis_json}\n\n"
        f"Gap detection:\n{gap_json}\n\n"
        f"Source resume:\n{candidate_resume}"
    )


def resume_skill_inject_prompt(
    tailored_resume: dict[str, Any],
    skills: list[str],
    target_sections: list[str] | None = None,
    job_description: str | None = None,
    instructions: str | None = None,
) -> str:
    resume_json = json.dumps(tailored_resume, ensure_ascii=False, indent=2, default=str)
    skills_json = json.dumps(skills, ensure_ascii=False)
    sections_json = json.dumps(target_sections or [], ensure_ascii=False)
    job_text = job_description.strip() if isinstance(job_description, str) else ""
    extra = instructions.strip() if isinstance(instructions, str) else ""
    return (
        "Improve the impact of a tailored resume by incorporating the requested skill terms into the most relevant sections.\n"
        "Return exactly one JSON object.\n\n"
        "Goal:\n"
        "- strengthen keyword coverage\n"
        "- improve impact and relevance\n"
        "- keep the resume credible and coherent\n"
        "- do not invent unsupported company names, dates, or certifications\n\n"
        "Return JSON with exactly these keys:\n"
        "- tailored_resume: object\n"
        "- applied_skills: string[]\n"
        "- placement_summary: array of objects with keys:\n"
        "  - skill: string\n"
        "  - sections: string[]\n"
        "  - rationale: string\n\n"
        "Rules:\n"
        "- Update only sections where the skill fits naturally.\n"
        "- Prefer summary, skills, and existing experience bullets unless target_sections restricts placement.\n"
        "- Keep structure stable.\n"
        "- No markdown or prose outside JSON.\n\n"
        f"Skills to inject:\n{skills_json}\n\n"
        f"Target sections:\n{sections_json}\n\n"
        f"Additional instructions:\n{extra or 'None'}\n\n"
        f"Job description:\n{job_text or 'Not provided'}\n\n"
        f"Tailored resume:\n{resume_json}"
    )
