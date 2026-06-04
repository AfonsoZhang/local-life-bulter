"""轻量 Markdown → HTML 渲染器（专为 Dashboard 设计）"""
import re


def render(md: str) -> str:
    lines = md.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # 代码块
        if line.strip().startswith("```"):
            lang = line.strip()[3:].strip() or "text"
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            code = "\n".join(code_lines)
            code = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            out.append(f'<pre class="code-block"><code class="lang-{lang}">{code}</code></pre>')
            i += 1
            continue

        # 表格
        if "|" in line and i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|", lines[i + 1]):
            headers = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2  # skip separator
            rows = []
            while i < len(lines) and "|" in lines[i]:
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(row)
                i += 1
            th = "".join(f"<th>{h}</th>" for h in headers)
            trs = "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>"
                for row in rows
            )
            out.append(f'<table class="md-table"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>')
            continue

        # H1
        if line.startswith("# ") and not line.startswith("## "):
            out.append(f'<h1 class="md-h1">{inline(line[2:])}</h1>')
            i += 1
            continue

        # H2
        if line.startswith("## "):
            out.append(f'<h2 class="md-h2">{inline(line[3:])}</h2>')
            i += 1
            continue

        # H3
        if line.startswith("### "):
            out.append(f'<h3 class="md-h3">{inline(line[4:])}</h3>')
            i += 1
            continue

        # 列表
        if re.match(r"^[-*•]\s", line):
            items = []
            while i < len(lines) and re.match(r"^[-*•]\s", lines[i]):
                items.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            out.append(f'<ul class="md-list">{"".join(items)}</ul>')
            continue

        # 有序列表
        if re.match(r"^\d+\.\s", line):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i]):
                text = re.sub(r"^\d+\.\s", "", lines[i])
                items.append(f"<li>{inline(text)}</li>")
                i += 1
            out.append(f'<ol class="md-list">{"".join(items)}</ol>')
            continue

        # 水平线
        if re.match(r"^---+$", line.strip()):
            out.append('<hr class="md-hr">')
            i += 1
            continue

        # 引用块
        if line.startswith("> "):
            out.append(f'<blockquote class="md-blockquote">{inline(line[2:])}</blockquote>')
            i += 1
            continue

        # 空行
        if not line.strip():
            i += 1
            continue

        # 普通段落
        out.append(f'<p class="md-p">{inline(line)}</p>')
        i += 1

    return "\n".join(out)


def inline(text: str) -> str:
    """处理行内格式：粗体、斜体、行内代码、链接"""
    # 行内代码
    text = re.sub(r"`([^`]+)`", r'<code class="inline-code">\1</code>', text)
    # 粗体
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # 斜体（下划线形式）
    text = re.sub(r"_(.+?)_", r"<em>\1</em>", text)
    # 链接（只保留文字，不做外链跳转）
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"<span class=\"md-link\">\1</span>", text)
    return text


def extract_section(md: str, heading: str) -> str:
    """提取指定 H2 节的内容"""
    pattern = rf"## {re.escape(heading)}\n(.*?)(?=\n## |\Z)"
    m = re.search(pattern, md, re.DOTALL)
    return m.group(1).strip() if m else ""


def extract_sections(md: str) -> list:
    """返回所有 H2 节：[{title, content_html}]"""
    parts = re.split(r"\n## ", md)
    result = []
    for part in parts[1:]:
        lines = part.split("\n", 1)
        title = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        result.append({"title": title, "html": render(body)})
    return result
