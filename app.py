"""
FounderLens｜AI创业项目传播助手
基于蚂蚁百灵大模型（Ling）生成项目分析、传播选题与内容初稿
"""
import html
import json
import os
import re

import requests
import streamlit as st

# 本地开发自动加载 .env（部署时也可直接配置系统环境变量）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

LING_API_KEY = os.getenv("LING_API_KEY", "")
# 以下两项请以百灵开发者平台当前文档为准，可通过环境变量覆盖
LING_BASE_URL = os.getenv("LING_BASE_URL", "https://api.ant-ling.com/v1").rstrip("/")
LING_MODEL = os.getenv("LING_MODEL", "Ling-3.1-flash")

PAGE_CSS = """
<style>
    .stApp { background-color: #FAF7F1; }
    .block-container { padding-top: 2.5rem; padding-bottom: 3rem; }
    .main-title { color:#0F2B4D; font-size:2.2rem; font-weight:700; margin-bottom:0; }
    .sub-title { color:#5B6B80; font-size:1rem; margin-top:.25rem; }
    .card { background:#FFFFFF; border:1px solid #E8E2D6; border-radius:12px;
            padding:1rem 1.2rem; margin-bottom:.8rem; line-height:1.7; }
    .tag { color:#1D5C99; background:#EAF1F8; border-radius:999px;
           padding:.1rem .6rem; font-size:.78rem; }
    .disclaimer { color:#8A6D1F; background:#FBF4DF; border-left:4px solid #E0B94E;
                  padding:.7rem 1rem; border-radius:6px; font-size:.85rem; }
</style>
"""

SYSTEM_PROMPT = """你是「FounderLens」AI创业项目传播助手，服务对象是品牌运营与内容策划人员。请严格依据用户提供的项目介绍完成分析与创作，规则如下：

1. 只能使用介绍中明确出现的信息；可以基于行业常识做合理推断，但涉及融资金额、估值、用户规模、营收、成立时间、合作关系等具体事实时，若介绍中未提及，必须标注"（需核实）"，严禁编造数字。
2. 语言自然，像真实创作者写的，避免AI腔：不要用"赋能、抓手、闭环、综上所述、总而言之"等套话，避免"不是A而是B"的模板句式。
3. 只输出一个合法JSON对象，不要输出任何额外文字、解释或代码块标记。

JSON结构（所有文案使用中文）：
{
  "one_liner": "一句话介绍（不超过40字）：项目是谁、做什么、面向谁",
  "target_users": ["目标用户群1", "目标用户群2", "目标用户群3"],
  "pain_points": ["核心痛点1", "核心痛点2"],
  "selling_points": ["产品卖点1", "产品卖点2", "产品卖点3"],
  "topics": [{"title": "选题标题", "reason": "一句推荐理由（不超过50字）", "platform": "公众号|小红书|通用"}],
  "draft": "内容初稿全文（第一行为标题，空一行后为正文）"
}
"""


def user_prompt(intro: str, platform: str) -> str:
    if platform == "公众号":
        draft_rule = "公众号长图文初稿：标题 + 约500字连贯段落正文，语气专业但不端着，适合品牌号/行业号发布。"
    else:
        draft_rule = "小红书笔记初稿：标题（可带emoji）+ 约300字口语化正文，表达具体自然，不得虚构亲身体验或用户反馈，结尾附5-10个#话题标签。"
    return (f"目标平台：{platform}\n内容要求：{draft_rule}\n"
            f"请生成恰好3个传播选题，优先适配该平台（可含1个通用选题）。\n\n【项目介绍】\n{intro}")


def call_ling(intro: str, platform: str) -> str:
    resp = requests.post(
        f"{LING_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {LING_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": LING_MODEL,
            "temperature": 0.7,
            "max_tokens": 4096,
            "thinking": {"type": "disabled"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt(intro, platform)},
            ],
        },
        timeout=90,
    )
    if resp.status_code != 200:
        raise RuntimeError({401: "密钥无效，请检查本地 .env 文件。", 403: "没有调用权限，请检查平台模型权限。", 429: "请求受限或额度不足，请查看平台控制台。"}.get(resp.status_code, f"百灵服务返回错误（HTTP {resp.status_code}），请稍后重试。"))
    payload = resp.json()
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("百灵未返回生成结果，请稍后重试。")
    choice = choices[0]
    content = (choice.get("message") or {}).get("content")
    if choice.get("finish_reason") == "length":
        raise RuntimeError("生成内容超出长度限制，请缩短项目介绍后重试。")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("百灵本次未返回正文，请重新点击开始分析。")
    return content


def extract_json(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("百灵本次未返回正文，请重新点击开始分析。")
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("模型返回内容解析失败，请重试或简化输入。")


def normalize(data: dict) -> dict:
    def ensure_list(x):
        return x if isinstance(x, list) else ([x] if x else [])
    if not isinstance(data, dict):
        raise RuntimeError("模型返回格式不正确，请重试。")
    topics = []
    for t in (data.get("topics") or [])[:3]:
        if isinstance(t, dict):
            topics.append({
                "title": str(t.get("title", "未命名选题")),
                "reason": str(t.get("reason", "")),
                "platform": str(t.get("platform", "通用")),
            })
    return {
        "one_liner": str(data.get("one_liner", "")),
        "target_users": ensure_list(data.get("target_users")),
        "pain_points": ensure_list(data.get("pain_points")),
        "selling_points": ensure_list(data.get("selling_points")),
        "topics": topics,
        "draft": str(data.get("draft", "")),
    }


def compose_full_text(data: dict, platform: str) -> str:
    lines = [f"一句话介绍：{data['one_liner']}", "", "目标用户："]
    lines += [f"- {u}" for u in data["target_users"]]
    lines += ["", "核心痛点："] + [f"- {p}" for p in data["pain_points"]]
    lines += ["", "产品卖点："] + [f"- {s}" for s in data["selling_points"]]
    lines += ["", "传播选题："]
    for i, t in enumerate(data["topics"], 1):
        lines.append(f"{i}. {t['title']}（{t['platform']}）— {t['reason']}")
    lines += ["", f"{platform}内容初稿：", "", data["draft"]]
    return "\n".join(lines)


def copy_button(text: str, label: str, key: str):
    st.caption(f"{label}：点击下方文本框右上角的复制图标。")
    st.code(text, language=None)


def render_result(data: dict, platform: str):
    copy_button(compose_full_text(data, platform), "复制完整方案", "copy_all")
    tabs = st.tabs(["📌 项目分析", "💡 传播选题", f"✍️ {platform}初稿"])

    with tabs[0]:
        if data["one_liner"]:
            st.markdown(f"> {data['one_liner']}")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**目标用户**")
            for u in data["target_users"]:
                st.markdown(f"- {u}")
        with c2:
            st.markdown("**核心痛点**")
            for p in data["pain_points"]:
                st.markdown(f"- {p}")
        with c3:
            st.markdown("**产品卖点**")
            for s in data["selling_points"]:
                st.markdown(f"- {s}")

    with tabs[1]:
        for i, t in enumerate(data["topics"], 1):
            st.markdown(
                f"<div class='card'><span class='tag'>{html.escape(t['platform'])}</span> "
                f"<b>选题 {i}：{html.escape(t['title'])}</b><br>"
                f"<span style='color:#5B6B80'>推荐理由：{html.escape(t['reason'])}</span></div>",
                unsafe_allow_html=True,
            )

    with tabs[2]:
        copy_button(data["draft"], "复制初稿", "copy_draft")
        st.markdown(data["draft"])


def main():
    st.set_page_config(page_title="FounderLens｜AI创业项目传播助手", page_icon="🔍", layout="centered")
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    st.markdown(
        "<h1 class='main-title'>FounderLens</h1>"
        "<p class='sub-title'>AI 创业项目传播助手 · 理解项目 · 生成选题 · 产出初稿</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    if not LING_API_KEY:
        st.markdown(
            "<div class='card'><b>⚙️ 尚未配置百灵 API Key</b><br>"
            "请按以下步骤配置后刷新页面：<br>"
            "1. 访问百灵开发者平台 <a href='https://developer.ant-ling.com'>developer.ant-ling.com</a>，注册账号并创建 API Key"
            "（接口地址与模型名以平台当前文档为准）；<br>"
            "2. 在本项目目录新建 <code>.env</code> 文件，写入：<code>LING_API_KEY=你的APIKey</code>；<br>"
            "3. 如平台地址或模型名称不同，追加配置 <code>LING_BASE_URL=...</code> 和 <code>LING_MODEL=...</code>；<br>"
            "4. 或直接在终端设置环境变量：<code>export LING_API_KEY=你的APIKey</code>"
            "（Windows 用 <code>set LING_API_KEY=你的APIKey</code>），然后重新运行。</div>",
            unsafe_allow_html=True,
        )
        st.stop()

    st.caption(f"当前模型：`{LING_MODEL}`")
    intro = st.text_area(
        "请粘贴或输入创业项目介绍（产品简介、官网文案、新闻稿片段均可）",
        height=170, key="intro",
        help="输入越具体，生成内容越贴合实际",
    )
    platform = st.radio("内容发布平台", ["公众号", "小红书"], horizontal=True)

    if st.button("开始分析", type="primary", use_container_width=True):
        if not intro.strip():
            st.warning("请先输入创业项目介绍后再分析。")
        else:
            with st.spinner("正在调用百灵大模型（Ling）分析中…"):
                try:
                    data = normalize(extract_json(call_ling(intro.strip(), platform)))
                    st.session_state["result"] = data
                    st.session_state["platform"] = platform
                    st.rerun()
                except Exception as e:
                    st.error("生成失败：" + str(e).replace(LING_API_KEY, "[密钥已隐藏]"))

    if st.session_state.get("result"):
        render_result(st.session_state["result"], st.session_state.get("platform", "公众号"))
        st.divider()
        st.markdown(
            "<div class='disclaimer'>⚠️ 以上内容基于您输入的项目介绍由 AI 生成。"
            "涉及融资金额、用户规模、营收等具体数据请以官方公开信息为准；"
            "标注「需核实」的部分请人工确认后再对外使用。</div>",
            unsafe_allow_html=True,
        )


if __name__ == "__main__":
    main()