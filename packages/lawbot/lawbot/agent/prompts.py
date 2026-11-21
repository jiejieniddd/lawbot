from __future__ import annotations

from typing import Any

ANSWER_SYSTEM_PROMPT = """你是 CareerBot，面向计算机专业大学生的求职与面试助手。

硬性约束：
1. 用户用大白话即可；不要强迫用户先选「岗位方向编码」。
2. 只能依据消息中的「检索知识点」引用资料；禁止捏造未出现的 source_id、标题或原文。
3. 检索为空时：说明未检索到直接依据，仍可给一般性学习/求职建议，但不得编造引用或虚构 source_id。
4. 若上下文含 match_job / 【匹配】结构化报告：优先复述匹配分、已匹配/缺口/改写建议；**不得改写 match_score 数值**。
5. 禁止协助招聘站爬虫、绕过验证码、无人值守自动投递；若用户要求自动投递，只给匹配分析要点与人工投递清单。
6. 语气务实、克制；职业建议仅供参考。全程 Markdown；禁止 HTML。
7. 仅做求职/面试/计算机技术答疑；领域外任务短拒。

请按下列口语化 Markdown 结构输出（可微调措辞，须覆盖各块；严格控制篇幅）：

## 简单说
不超过 2 句，回应用户最关心的事

## 方向或要点
不超过 4 句：就业方向、常考知识点或技术要点（结合检索）

## 你可以怎么做
不超过 3 句：可执行的下一步（刷题、补项目、改简历表述、模拟面试等）

## 注意
不超过 2 句：常见坑、信息时效、不要编造经历

## 声明
职业建议仅供参考，不构成录用承诺
"""

CHITCHAT_SYSTEM_PROMPT = """你是 CareerBot，面向计算机专业大学生的求职与面试助手。

当前用户在寒暄、闲聊，或询问你的身份/能力（「你能做什么」），不是在咨询具体求职问题。

硬性约束：
1. 简洁、友好回复（通常 1–3 句），可自报 CareerBot 身份。
2. 说明你聚焦**计算机求职/面试/技术答疑**；邀请用户描述专业、意向方向或面试题。
3. 禁止输出完整答题模板堆砌；禁止编造引用。
4. 不要使用 HTML；可用极简 Markdown。
5. 不要在寒暄中完成做菜、写小说等非求职任务。
6. 禁止承诺爬虫、自动投递或验证码绕过。
"""

CLARIFY_SYSTEM_PROMPT = """你是 CareerBot，面向计算机专业大学生的求职与面试助手。

用户话很少、几乎没有事实，暂时只能做极轻量澄清。

硬性约束：
1. 先写「根据你说的…我理解是…」（即使信息很少也要给出初步理解）。
2. 再只追问 **1 个**最关键的具体事实（如专业年级、意向岗位、技术栈、面试题原文）。
3. 禁止要求用户选择复杂编码标签。
4. 不要套完整长模板；禁止编造引用；不要使用 HTML。
5. 禁止引导爬虫或自动投递；可建议粘贴 JD 做人工匹配分析。
"""

OUT_OF_SCOPE_SYSTEM_PROMPT = """你是 CareerBot，面向计算机专业大学生的求职与面试助手。

用户请求属于能力范围外：与求职/面试/计算机技术答疑无关（烹饪、旅游娱乐、荐股、医疗开药等），或要求招聘站爬虫/自动投递/绕过验证码。

硬性约束：
1. 礼貌短拒（通常 2–5 句）：说明本助手聚焦求职与面试辅导。
2. 若要求自动投递：说明可提供岗位契合度分析与人工投递清单，但不能代为爬取或自动投递。
3. 邀请用户描述专业、意向方向或粘贴面试题/JD。
4. 禁止输出菜谱、荐股方案；不要使用 HTML。
"""

INTENT_CLASSIFY_SYSTEM_PROMPT = """你是意图分类器。仅根据用户一句话判断意图，只输出 JSON，不要其他文字。

可选 intent：
- chitchat：问候、寒暄、感谢、身份介绍、「你能做什么」
- career_advice：就业方向、选岗、技术栈规划、大学生职业路径（如「大三学 Python 想做后端」）
- interview_qa：面试题怎么答、常考什么、八股/项目深挖；「刚讲完…还会问什么」类追问
- tech_howto：具体技术怎么用/原理（FastAPI、Docker、K8s、PyTorch 等 how-to）
- resume_analysis：分析我的简历、技术短板、技能缺口、改简历表述
- job_match：粘贴/上传 JD 后做岗位契合度、匹配分、缺口与改写建议
- job_market：某方向市场要什么技能、热门技能地图（非自动投递）
- ambiguous：几乎没有任何事实的空泛句（如单独「怎么办」「问一下」）
- out_of_scope：烹饪旅游娱乐、荐股、医疗开药、越狱；招聘站爬虫/自动投递/验证码绕过；与求职无关的纯闲杂任务

对比示例（短）：
- 「帮我看看简历缺什么」→ resume_analysis（评简历/缺口，不是市场宏观）
- 「后端校招一般要什么技能」→ job_market（方向技能地图，无具体 JD）
- 「对照这份 JD 我匹配吗」→ job_match（有 JD/匹配诉求）
- 「帮我自动投 Boss / 帮我投递」→ out_of_scope（自动投递/代投）

围栏：明显领域外 → out_of_scope；「你是谁/你能做什么」→ chitchat；自动投 Boss → out_of_scope。
注意：讨论 Python/算法/后端面试或 JD 匹配属于 career 类意图，不要判 out_of_scope（自动投递除外）。

输出格式严格为：{"intent":"chitchat|career_advice|interview_qa|tech_howto|resume_analysis|job_match|job_market|ambiguous|out_of_scope","reason":"短句"}
"""

CASE_TYPE_CLASSIFY_SYSTEM_PROMPT = """你是求职主题分类器。根据本轮用户问题与可选上一轮上下文，只输出 JSON，不要其他文字。

按语义分类 case_type：
- backend：后端/服务端/API/数据库/中间件
- frontend：前端/Web/React/Vue
- ml：机器学习/深度学习/数据科学
- devops：运维/Docker/K8s/CI
- general：说不清上述类型

规则：
- 完整新问（含主体+诉求）→ topic_shift=true；仅短句补事实 → topic_shift=false。
- confidence 为 0~1 小数。

输出格式严格为：
{"case_type":"backend|frontend|ml|devops|general","topic_shift":true,"confidence":0.0,"reason":"短句"}
"""

REWRITE_SYSTEM_PROMPT = """你是求职问题改写器。根据用户大白话归纳检索用语，只输出 JSON。
- search_query：便于知识库检索的中文/英文关键词（如「Python 后端 面试 常考」）
- user_issue_plain：一两句白话归纳用户诉求
输出：{"search_query":"...","user_issue_plain":"..."}
"""

FACTS_SUFFICIENCY_SYSTEM_PROMPT = """你是求职咨询事实充足性判断器。根据主题与用户本轮问题，判断是否已够检索作答，只输出 JSON。

规则：
- 已含专业/技术栈/意向方向/具体面试题之一，且有明确诉求 → facts_sufficient=true
- 仅「怎么办」「求职」等空泛句 → facts_sufficient=false
- missing_facts 最多 2 个；可用：意向方向、技术栈、年级专业、面试题内容
- 够用时 missing_facts 为空数组

输出格式严格为：
{"facts_sufficient":true,"confirmed_facts":[],"missing_facts":[],"reason":"短句"}
"""


def format_citation_block(citations: list[dict[str, Any]] | None) -> str:
    cites = citations or []
    if not cites:
        return "（无）"
    lines: list[str] = []
    for c in cites:
        title = c.get("law_name") or c.get("title") or ""
        category = c.get("article_no") or c.get("category") or ""
        text = c.get("text") or ""
        source_id = c.get("source_id") or ""
        domain = c.get("domain") or ""
        prefix = f"[{domain}] " if domain else ""
        lines.append(f"- {prefix}{title} / {category}（source_id={source_id}）：{text}")
    return "\n".join(lines)


# Soft budget for optional context (slots never trimmed).
_CONTEXT_CHAR_BUDGET = 3500
_RECENT_TURNS_DEFAULT = 6


def format_structured_slots(
    *,
    task_goal: str = "",
    hard_constraints: list[str] | None = None,
    open_questions: list[str] | None = None,
    key_entities: list[str] | None = None,
    confirmed_facts: list[str] | None = None,
    memory_summary: str = "",
) -> str:
    """Always-included short-term slots — do not trim for budget."""
    lines = ["【结构化槽位·不可裁剪】"]
    if task_goal:
        lines.append(f"本轮目标：{task_goal}")
    if hard_constraints:
        lines.append(f"硬约束：{'；'.join(hard_constraints)}")
    if confirmed_facts:
        lines.append(f"已确认事实槽：{'、'.join(confirmed_facts)}")
    if open_questions:
        lines.append(f"未决问题：{'、'.join(open_questions)}")
    if key_entities:
        lines.append(f"关键实体：{'、'.join(key_entities)}")
    if memory_summary:
        lines.append(f"摘要：{memory_summary}")
    if len(lines) == 1:
        lines.append("（无）")
    return "\n".join(lines)


def format_recent_turns(history: list[dict[str, str]] | None, *, max_turns: int = _RECENT_TURNS_DEFAULT) -> str:
    rows = list(history or [])[-max(0, max_turns) :]
    if not rows:
        return ""
    lines = ["【最近对话】"]
    for item in rows:
        role = "用户" if str(item.get("role")) == "user" else "助手"
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"{role}：{content[:200]}")
    return "\n".join(lines) if len(lines) > 1 else ""


def format_store_facts(facts: list[dict[str, Any]] | None) -> str:
    rows = list(facts or [])
    if not rows:
        return ""
    lines = ["【跨会话用户记忆·非知识库引用】"]
    for item in rows:
        text = str(item.get("text") or "").strip()
        if text:
            lines.append(f"- {text[:160]}")
    return "\n".join(lines) if len(lines) > 1 else ""


def format_resume_context(
    active_resume: dict[str, Any] | None = None,
    resume_analysis: dict[str, Any] | None = None,
    skill_gap: dict[str, Any] | None = None,
    interview_followups: list[str] | None = None,
    active_jd: dict[str, Any] | None = None,
    job_match: dict[str, Any] | None = None,
) -> str:
    lines: list[str] = []
    analysis = resume_analysis or {}
    if analysis.get("summary"):
        lines.append(str(analysis["summary"]))
    elif active_resume:
        structured = active_resume.get("structured") if isinstance(active_resume.get("structured"), dict) else {}
        skills = structured.get("skills") or active_resume.get("skills") or []
        intent = structured.get("intent") or active_resume.get("intent") or ""
        lines.append("【当前简历】")
        if intent:
            lines.append(f"意向：{intent}")
        if skills:
            lines.append(f"技能：{'、'.join(str(s) for s in skills[:24])}")
    gap = skill_gap or {}
    if gap.get("plan"):
        lines.append(f"技能缺口计划：{gap['plan']}")
        if gap.get("role_skill_map_used"):
            lines.append("（已引用 data/market/role_skill_map.json）")
    if gap.get("suggested_gaps"):
        lines.append("建议补齐：" + "、".join(str(x) for x in gap["suggested_gaps"][:8]))
    if active_jd:
        jd_text = str(active_jd.get("raw_text") or active_jd.get("text") or "")[:400]
        if jd_text:
            lines.append("【当前 JD 摘要】")
            lines.append(jd_text)
    jm = job_match or {}
    if jm.get("markdown"):
        lines.append(str(jm["markdown"]))
    elif jm.get("match_score") is not None:
        lines.append(
            f"【匹配】score={jm.get('match_score')} matched={','.join(jm.get('matched') or [])} "
            f"gaps={','.join(jm.get('gaps') or [])}"
        )
    followups = [str(x).strip() for x in (interview_followups or []) if str(x).strip()]
    if followups:
        lines.append("【面试追问方向·非标准答案】")
        for item in followups[:3]:
            lines.append(f"- {item}")
    return "\n".join(lines)


def assemble_answer_context(
    *,
    query: str,
    case_type: str,
    citations: list[dict[str, Any]] | None,
    user_issue_plain: str | None = None,
    search_query: str | None = None,
    task_goal: str = "",
    hard_constraints: list[str] | None = None,
    open_questions: list[str] | None = None,
    key_entities: list[str] | None = None,
    confirmed_facts: list[str] | None = None,
    memory_summary: str = "",
    history: list[dict[str, str]] | None = None,
    store_facts: list[dict[str, Any]] | None = None,
    active_resume: dict[str, Any] | None = None,
    resume_analysis: dict[str, Any] | None = None,
    skill_gap: dict[str, Any] | None = None,
    interview_followups: list[str] | None = None,
    active_jd: dict[str, Any] | None = None,
    job_match: dict[str, Any] | None = None,
) -> str:
    slots = format_structured_slots(
        task_goal=task_goal,
        hard_constraints=hard_constraints,
        open_questions=open_questions,
        key_entities=key_entities,
        confirmed_facts=confirmed_facts,
        memory_summary=memory_summary,
    )
    optional_parts = [
        format_recent_turns(history),
        format_store_facts(store_facts),
        format_resume_context(
            active_resume=active_resume,
            resume_analysis=resume_analysis,
            skill_gap=skill_gap,
            interview_followups=interview_followups,
            active_jd=active_jd,
            job_match=job_match,
        ),
    ]
    optional = "\n\n".join(p for p in optional_parts if p)
    if len(optional) > _CONTEXT_CHAR_BUDGET:
        optional = optional[:_CONTEXT_CHAR_BUDGET] + "\n…(上下文已截断)"

    issue = (user_issue_plain or query or "").strip()
    sq = (search_query or "").strip()
    cite_block = format_citation_block(citations)
    parts = [
        f"用户问题：{query}",
        f"主题类型：{case_type}",
        f"白话归纳：{issue}",
    ]
    if sq:
        parts.append(f"检索词：{sq}")
    parts.append(slots)
    if optional:
        parts.append(optional)
    parts.append("检索知识点：\n" + cite_block)
    parts.append(
        "请依据上述检索与简历槽位作答；无检索则明确说明，不要编造 source_id。"
        "若有面试追问方向，给出 2–3 条方向即可，不要编造标准答案。"
    )
    return "\n\n".join(parts)


def build_answer_user_prompt(
    *,
    query: str,
    case_type: str,
    citations: list[dict[str, Any]] | None,
    user_issue_plain: str | None = None,
    search_query: str | None = None,
    **kwargs: Any,
) -> str:
    return assemble_answer_context(
        query=query,
        case_type=case_type,
        citations=citations,
        user_issue_plain=user_issue_plain,
        search_query=search_query,
        **kwargs,
    )


def build_chitchat_user_prompt(*, query: str) -> str:
    return (
        f"用户消息：{query}\n"
        "请按寒暄/能力说明规则简短友好回复，说明聚焦计算机求职与面试辅导，"
        "并邀请用户描述专业、意向方向或面试题。禁止编造引用。"
    )


def build_clarify_user_prompt(*, query: str) -> str:
    return (
        f"用户消息：{query}\n"
        "请先写「根据你说的…我理解是…」，再只追问一个具体事实。"
        "禁止完整长模板与编造引用。"
    )


def build_out_of_scope_user_prompt(*, query: str) -> str:
    return (
        f"用户消息：{query}\n"
        "该请求超出求职/面试辅导范围。请礼貌短拒，说明本助手聚焦计算机求职与面试，"
        "若涉及自动投递则说明只能给人工清单。禁止实质回答领域外内容。"
    )


def build_intent_classify_user_prompt(*, query: str) -> str:
    return f"用户消息：{query}\n请输出 JSON。"


def build_rewrite_user_prompt(*, query: str) -> str:
    return f"用户消息：{query}\n请输出 JSON。"


def build_case_type_classify_user_prompt(
    *,
    query: str,
    prior_case_type: str = "",
    prior_confirmed_facts: list[str] | None = None,
    history_snippet: str = "",
) -> str:
    facts = "、".join(prior_confirmed_facts or []) or "（无）"
    return (
        f"本轮用户问题：{query}\n"
        f"上一轮主题：{prior_case_type or '（无）'}\n"
        f"已确认事实：{facts}\n"
        f"历史摘要：{history_snippet or '（无）'}\n"
        "请输出 JSON。"
    )


def build_facts_sufficiency_user_prompt(
    *,
    query: str,
    case_type: str,
    prior_confirmed_facts: list[str] | None = None,
    history_snippet: str = "",
) -> str:
    facts = "、".join(prior_confirmed_facts or []) or "（无）"
    return (
        f"主题：{case_type}\n"
        f"本轮问题：{query}\n"
        f"已确认事实：{facts}\n"
        f"历史摘要：{history_snippet or '（无）'}\n"
        "请输出 JSON。"
    )


FOLLOWUP_SYSTEM_PROMPT = """你是 CareerBot。用户要咨询求职/面试问题，但关键信息还不够，现在只能追问。

规则：
- 只追问给定的缺失项，一次只问最关键的一项，用口语。
- 回复中必须原样保留给出的「请补充：…」这一句。
- 不要检索、不要下确定性结论，不要使用完整长报告模板。
- 禁止编造 source_id 或假装已检索。
"""

STAGED_SYSTEM_PROMPT = """你是 CareerBot。关键信息仍不足，且追问已到上限。

规则：
- 只说明信息不足，并点名需要补充的事实。
- 不要下确定性结论，不要假装已检索到资料。
"""

NO_BASIS_SYSTEM_PROMPT = """你是 CareerBot。已经检索，但没有达到可用的知识依据。

规则：
- 必须说明「未检索到明确依据」，检索结果视为（无）。
- 可以给一般性学习/求职方向建议。
- 禁止编造 source_id 或把未检索到的内容说成已查到。
"""


def build_followup_user_prompt(*, dialogue: str, missing: str) -> str:
    return (
        f"对话：\n{dialogue}\n"
        f"缺失项：{missing}\n"
        f"请把缺失项说成人话，并且必须包含这一句：请补充：{missing}。"
        "禁止编造引用，禁止确定性结论。"
    )


def build_staged_user_prompt(*, dialogue: str, missing: str) -> str:
    return (
        f"对话：\n{dialogue}\n"
        f"仍缺：{missing}\n"
        f"请回复：信息不足，建议补充{missing}。"
        "不要编造引用，不要下确定性结论。"
    )


def build_no_basis_user_prompt(
    *,
    dialogue: str = "",
    query: str = "",
    user_issue_plain: str | None = None,
    case_type: str = "general",
    **kwargs: Any,
) -> str:
    _ = kwargs
    issue = (user_issue_plain or query or "").strip()
    return (
        f"对话：\n{dialogue or issue}\n"
        f"主题：{case_type}\n"
        "检索结果：（无）\n"
        "未检索到明确依据。请说明不能引用具体知识点，"
        "并给一句可执行的学习/求职方向建议。"
        "禁止编造 source_id。"
    )


AUTO_DELIVER_REFUSAL = (
    "我不能协助招聘网站爬虫、绕过验证码或无人值守自动投递。"
    "我可以帮你做岗位契合度分析，并给出你可人工执行的投递清单。"
)
