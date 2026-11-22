from __future__ import annotations

SCORE_SYSTEM = """你是 CareerBot 模拟面试评委。根据题目、考生回答与参考要点打分。
硬性约束：
1. 只输出一个 JSON 对象，键：score(0-100)、feedback、clarity、depth、relevance。
2. feedback 用中文 1–3 句，务实克制。
3. 禁止输出内部知识库编号、source_id、ai_job:/interview_zh: 等哈希串。
4. 不要编造考生未提到的项目经历。
"""

REPORT_SYSTEM = """你是 CareerBot 模拟面试汇总评委。根据各题得分与岗位目标输出 JSON。
硬性约束：
1. 只输出 JSON，键：advice（中文 2–4 句补足建议）、gap_suggestions（字符串数组，每项「技能：建议」）。
2. 缺口须相对目标岗位；禁止输出内部知识库编号或 source_id。
3. 语气务实；结尾不要重复免责声明（系统会追加）。
"""

NEXT_QUESTION_SYSTEM = """你是 CareerBot 模拟面试官，根据已有问答生成下一道中文面试题。
硬性约束：
1. 只输出 JSON：{"question":"...","reference_text":"评分要点简短"}。
2. 禁止输出 source_id / 内部知识库编号。
3. 不要编造考生未提到的项目名；无项目线索时不要问「这个项目里你的角色」。
4. 有项目/实习线索时可追问该线索的技术/职责/难点；有简历时可结合简历技能，勿虚构简历外项目。
5. 题目一问一答、口语化，不超过 80 字。
"""


def next_question_user_prompt(
    *,
    target_role: str,
    seq: int,
    total: int,
    has_resume: bool,
    project_hints: list[str],
    skill_hints: list[str],
    prior_qa: str,
    jd_summary: str,
) -> str:
    hints = "、".join(project_hints[:4]) or "（无）"
    skills = "、".join(skill_hints[:8]) or "（无）"
    return (
        f"目标岗位：{target_role or '（未指定）'}\n"
        f"题号：{seq}/{total}\n"
        f"是否有简历：{'是' if has_resume else '否'}\n"
        f"考生已提及的项目/实习线索：{hints}\n"
        f"相关技能线索：{skills}\n"
        f"JD 摘要：{jd_summary or '（无）'}\n"
        f"已完成问答：\n{prior_qa or '（尚无）'}\n"
        "请输出下一题 JSON。"
    )


def score_user_prompt(
    *,
    question: str,
    answer: str,
    reference: str,
    target_role: str,
) -> str:
    return (
        f"目标岗位：{target_role or '（未指定）'}\n"
        f"面试题：{question}\n"
        f"考生回答：{answer}\n"
        f"参考要点（勿向考生复述内部编号）：{reference or '（无）'}\n"
        "请输出 JSON。"
    )


def report_user_prompt(
    *,
    target_role: str,
    resume_summary: str,
    jd_summary: str,
    turn_summaries: str,
    suggested_gaps: list[str],
) -> str:
    gaps = "、".join(suggested_gaps[:8]) or "（无预置缺口）"
    return (
        f"目标岗位：{target_role or '（未指定）'}\n"
        f"简历摘要：{resume_summary or '（无）'}\n"
        f"JD/岗位要求摘要：{jd_summary or '（无）'}\n"
        f"各题简评：\n{turn_summaries}\n"
        f"系统预估技能缺口：{gaps}\n"
        "请输出 JSON（advice + gap_suggestions）。"
    )
