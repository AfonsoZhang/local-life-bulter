#!/usr/bin/env python3
"""SKILL.md 规范与文档-代码一致性闸门。

机械校验，不含 LLM。任何一条不过就 exit 1，用于 pre-commit 与 CI。
挡的是「文档说的和代码做的对不上」这类漂移——SKILL.md 是 agent 唯一的操作依据，
它写错一条命令，agent 就会照错的调一整轮。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"

errors: list[str] = []


def err(skill: str, rule: str, msg: str) -> None:
    line = f"[{skill}] {rule}: {msg}"
    if line not in errors:
        errors.append(line)


def parse_frontmatter(text: str):
    if not text.startswith("---\n"):
        return None, text
    _, fm, body = text.split("---\n", 2)
    data = {}
    for line in fm.splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    return data, body


def main() -> int:
    skill_dirs = sorted(d for d in SKILLS.iterdir() if d.is_dir())
    skill_names = {d.name for d in skill_dirs}

    for d in skill_dirs:
        name = d.name
        f = d / "SKILL.md"
        if not f.exists():
            err(name, "R0", "缺 SKILL.md")
            continue
        text = f.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)

        # R1 frontmatter 完整、name 与目录一致、metadata 是合法 JSON
        if fm is None:
            err(name, "R1", "缺 YAML frontmatter")
            continue
        for key in ("name", "description", "metadata"):
            if key not in fm:
                err(name, "R1", f"frontmatter 缺 {key}")
        if fm.get("name") != name:
            err(name, "R1", f"name={fm.get('name')!r} 与目录名不一致")
        try:
            json.loads(fm.get("metadata", "{}"))
        except json.JSONDecodeError as e:
            err(name, "R1", f"metadata 不是合法 JSON: {e}")

        # R2 description 必须承担路由：写明触发场景，且够长（它是唯一常驻上下文的部分）
        desc = fm.get("description", "")
        if "触发场景" not in desc:
            err(name, "R2", "description 未写「触发场景」——正文的 Trigger 只有命中后才读，路由不到")
        if len(desc) < 60:
            err(name, "R2", f"description 仅 {len(desc)} 字，写不下触发场景与边界")

        # R3 必须有硬约束段（防模型自由发挥）与坑段（防重复踩）
        if not re.search(r"##.*(硬约束|⚠️)", body):
            err(name, "R3", "缺硬约束段")
        if "## 坑与降级" not in body:
            err(name, "R3", "缺「## 坑与降级」段")

        # R4 文档→代码一致性：SKILL.md 里写的脚本必须存在
        script_refs = set(re.findall(r"\{baseDir\}/([\w./-]+\.py)", body))
        script_refs |= {
            f"../{m}" for m in re.findall(r"\{baseDir\}/\.\./([\w./-]+\.py)", body)
        }
        for rel in sorted(script_refs):
            target = (d / rel).resolve()
            if not target.exists():
                err(name, "R4", f"引用的脚本不存在: {rel}")

        # R5 文档里写的子命令/参数必须真在脚本源码里
        for block in re.findall(r"```bash\n(.*?)```", body, re.S):
            for line in block.splitlines():
                line = line.strip()
                m = re.match(r"python3?\s+\{baseDir\}/([\w./-]+\.py)\s*(.*)", line)
                if not m:
                    continue
                rel, rest = m.groups()
                target = (d / rel).resolve()
                if not target.exists():
                    continue
                src = target.read_text(encoding="utf-8")
                for flag in re.findall(r"(?<![\w-])(--[a-z][\w-]*)", rest):
                    if flag not in src:
                        err(name, "R5", f"{rel} 源码里没有 {flag}（文档与代码漂移）")
                head = rest.split()
                if head:
                    sub = head[0].strip("\"'")
                    if sub.startswith("-") or sub.startswith("<"):
                        sub = ""
                    if sub and f'"{sub}"' not in src and f"'{sub}'" not in src:
                        err(name, "R5", f"{rel} 源码里没有子命令 {sub}（文档与代码漂移）")

        # R6 提到的兄弟技能必须存在（防指向已删/改名的技能）
        for ref in re.findall(r"skills/([\w-]+)/", body + desc):
            if ref not in skill_names:
                err(name, "R6", f"引用了不存在的技能 skills/{ref}/")

    # R7 AGENTS.md 的路由收口层必须覆盖全部技能
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    if "技能路由" not in agents:
        errors.append("[AGENTS.md] R7: 缺技能路由收口层——只有技能目录、没有仲裁与兜底分支")
    else:
        routing = agents.split("技能路由", 1)[1][:2000]
        for n in sorted(skill_names):
            if n not in routing:
                errors.append(f"[AGENTS.md] R7: 路由收口层未覆盖技能 {n}")

    if errors:
        print(f"✗ {len(errors)} 条不合规：\n")
        for e in errors:
            print("  " + e)
        return 1
    print(f"✓ {len(skill_dirs)} 个技能全部通过（R1–R7）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
