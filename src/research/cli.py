import argparse
import copy
import json
import os
import sys
import toml
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(prog="veritas")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # search
    sp = subparsers.add_parser("search", help="Search the web or legal databases")
    sp.add_argument("query", nargs="+", help="Search queries")
    sp.add_argument("--run-dir", help="Research run directory (auto-generated if omitted)")
    sp.add_argument("--limit", type=int, help="Results per query (default from config: search.default_limit)")
    sp.add_argument("--scrape", action="store_true", help="Light-scrape each result")
    sp.add_argument("--json", action="store_true", help="JSON output")
    sp.add_argument("-o", "--output", help="Output file path")
    sp.add_argument("--backend", choices=["opencli", "yuandian"], default="opencli",
                    help="Search backend (default: opencli)")
    sp.add_argument("--type", dest="legal_type", choices=["all", "law", "case"], default="all",
                    help="Legal search type (yuandian only)")
    sp.add_argument("--region", default="",
                    help="地区过滤（yuandian only, 如 北京/广东）")
    sp.add_argument("--since", default="",
                    help="发布日期起始 (YYYY-MM-DD, yuandian only)")
    sp.add_argument("--until", default="",
                    help="发布日期截止 (YYYY-MM-DD, yuandian only)")
    sp.add_argument("--opencli-sites", help="Comma-separated opencli sites to search (e.g. 'hackernews,arxiv')")
    sp.add_argument("--opencli-public-only", action="store_true", default=None,
                    help="Only use PUBLIC-strategy opencli sites (no browser needed)")
    sp.add_argument("--opencli-timeout", type=int,
                    help="Timeout per opencli command (seconds)")
    sp.set_defaults(func=cmd_search)

    # scrape
    sp = subparsers.add_parser("scrape", help="Scrape URLs via opencli or yuandian:// adapters")
    sp.add_argument("url", nargs="+", help="URLs to scrape")
    sp.add_argument("--backend", choices=["opencli"], default="opencli",
                    help="Scrape backend (default: opencli)")
    sp.add_argument("--run-dir", help="Research run directory (auto-generated if omitted)")
    sp.add_argument("--timeout", type=int, help="Per-request timeout (s; default from config: opencli.timeout)")
    sp.add_argument("--json", action="store_true", help="JSON output")
    sp.add_argument("-o", "--output", help="Output file path")
    sp.set_defaults(func=cmd_scrape)

    # verify
    sp = subparsers.add_parser("verify", help="Verify evidence in a run directory")
    sp.add_argument("--run-dir", required=True, help="Research run directory")
    sp.add_argument("--type", dest="type", default="general",
                    choices=["general", "deep-research", "practical-guide", "case-research"],
                    help="Report type for type-aware validation (default: general)")
    sp.add_argument("--json", action="store_true", help="JSON output")
    sp.add_argument("--allow-repairable", action="store_true", help="Don't fail on repairable issues")
    sp.add_argument("--fix-manifest", action="store_true", help="Auto-fix manifest")
    sp.set_defaults(func=cmd_verify)

    # config
    sp = subparsers.add_parser("config", help="Manage configuration and API keys")
    sp.add_argument("action", choices=["show", "set", "init"],
                    help="Config action")
    sp.add_argument("key", nargs="?", help="Config key (e.g. api_keys.yuandian_key)")
    sp.add_argument("value", nargs="?", help="Config value")
    sp.set_defaults(func=cmd_config)

    # legal
    sp = subparsers.add_parser("legal", help="Legal research tools (元典开放平台)")
    sp.add_argument("action", choices=["verify-citations"],
                    help="Legal action")
    sp.add_argument("--run-dir", help="Research run directory containing draft")
    sp.add_argument("--text", help="Text to check for legal hallucinations")
    sp.add_argument("--file", help="File to check for legal hallucinations")
    sp.add_argument("--json", action="store_true", help="JSON output")
    sp.set_defaults(func=cmd_legal)

    # finalize
    sp = subparsers.add_parser("finalize", help="Finalize a research report")
    sp.add_argument("--run-dir", required=True, help="Research run directory")
    sp.add_argument("--type", dest="type", default="general",
                    choices=["general", "deep-research", "practical-guide", "case-research"],
                    help="Report type for type-aware finalization (default: general)")
    sp.add_argument("--report", help="Draft report file path")
    sp.add_argument("--report-stdin", action="store_true", help="Read draft from stdin")
    sp.add_argument("--output", help="Final report path")
    sp.add_argument("--summary", help="Summary output path")
    sp.set_defaults(func=cmd_finalize)

    # template
    sp = subparsers.add_parser("template", help="Generate a draft template for a report type")
    sp.add_argument("--type", dest="type", default="general",
                    choices=["general", "deep-research", "practical-guide", "case-research"],
                    help="Report type (default: general)")
    sp.add_argument("--topic", required=True, help="Research topic / title")
    sp.add_argument("--run-dir", help="Write template to run-dir/draft-report.md")
    sp.add_argument("-o", "--output", help="Output file path")
    sp.set_defaults(func=cmd_template)

    # regtrack
    sp = subparsers.add_parser("regtrack", help="法规雷达 — 按行业监控法规变更")
    sp.add_argument("action", choices=["add", "remove", "check", "status"],
                    help="操作")
    sp.add_argument("--industry", help="行业关键词")
    sp.add_argument("--keywords", nargs="+", help="多个搜索关键词")
    sp.add_argument("--region", default="", help="地区/区域")
    sp.add_argument("--count", type=int, default=50, help="每关键词搜索数量")
    sp.add_argument("--since", default="", help="起始日期 (YYYY-MM-DD)")
    sp.add_argument("--until", default="", help="截止日期 (YYYY-MM-DD)")
    sp.add_argument("--id", dest="reg_id", help="法规 ID")
    sp.add_argument("--regtrack-file", default=".research/regtrack.json",
                    help="跟踪数据文件路径")
    sp.add_argument("--json", action="store_true", help="JSON 输出")
    sp.set_defaults(func=cmd_regtrack)

    # inject-cases — 反附录式证据分配
    sp = subparsers.add_parser("inject-cases",
                               help="从 run-dir 抽取的 case 按主题词分配到报告章节（生成 case-allocation.md 推荐表）")
    sp.add_argument("--run-dir", required=True, help="研究 run 目录（含 query-*.json / scrape-*.json / scrape-manifest.tsv）")
    sp.add_argument("--type", dest="type", default="practical-guide",
                    choices=["practical-guide", "deep-research", "case-research"],
                    help="报告类型（决定默认章节关键词表）")
    sp.add_argument("--topic", help="报告主题（用于 case-allocation.md 标题）")
    sp.add_argument("--section-keywords",
                    help="自定义章节关键词，格式：'一、:词1,词2;二、:词3,词4'")
    sp.add_argument("--top-n", type=int, default=3, help="每章推荐 case 数（默认 3）")
    sp.add_argument("--output", help="输出文件路径（默认 <run-dir>/case-allocation.md）")
    sp.add_argument("--json", action="store_true", help="JSON 输出")
    sp.set_defaults(func=cmd_inject_cases)

    args = parser.parse_args()
    args.func(args)


def cmd_search(args):
    from research.search import run_search
    run_search(args)


def cmd_scrape(args):
    from research.scrape import run_scrape
    run_scrape(args)


def cmd_verify(args):
    from research.verify import run_verify
    result = run_verify(args)
    if args.json:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_config(args):
    from research.config import load_config
    config_path = _config_path()

    if args.action == "init":
        if config_path.exists():
            print(f"Config already exists at {config_path}")
            return
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("""# research-cli configuration
# Copy to ~/.config/research-cli/config.toml and fill local values.
# Never commit a real config file or API key to version control.

[api_keys]
yuandian_key = ""

[opencli]
public_only = false
timeout = 30
inter_command_delay = 3.0
default_sites = ""

[search]
default_limit = 10
max_concurrent = 4

[run_dir]
base = ".research/runs"

[reader_selfhost]
# Optional: absolute path to a local reader-selfhost checkout.
# Leave empty to disable automatic local server startup.
dir = ""
command = "node src/server.js"
port = 3099
# Optional: override runtime files. Empty values use OS temporary/cache directories.
pid_file = ""
puppeteer_cache_dir = ""
""")
        config_path.chmod(0o600)
        print(f"Config created at {config_path} (chmod 600)")
        return

    if args.action == "show":
        cfg = load_config()
        safe = _redact_keys(cfg)
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        return

    if args.action == "set":
        if not args.key or not args.value:
            print("Usage: research config set <key> <value>")
            print("Example: research config set api_keys.yuandian_key sk-...")
            return
        _set_config_value(config_path, args.key, args.value)
        print(f"Set {args.key}")
        return


def _config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return Path(xdg) / "research-cli" / "config.toml"


def _redact_keys(cfg: dict) -> dict:
    redacted = copy.deepcopy(cfg)
    api_keys = redacted.get("api_keys", {})
    for k in ("yuandian_key", "exa_key", "anysearch_key"):
        if api_keys.get(k):
            v = api_keys[k]
            api_keys[k] = v[:4] + "..." + v[-4:] if len(v) > 12 else "***"
    return redacted


def _set_config_value(config_path: Path, key: str, value: str):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        cfg = toml.load(str(config_path))
    else:
        cfg = {}
    parts = key.split(".")
    target = cfg
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value
    config_path.write_text(toml.dumps(cfg))
    config_path.chmod(0o600)


def _split_keywords(values: list[str] | None) -> list[str]:
    if not values:
        return []
    keywords = []
    for value in values:
        keywords.extend(k.strip() for k in value.split(",") if k.strip())
    return keywords


def cmd_legal(args):
    if args.action == "verify-citations":
        from research.backends.yuandian import YuandianBackend
        from research.config import load_config
        cfg = load_config()
        api_key = cfg.get("api_keys", {}).get("yuandian_key", "")
        if not api_key:
            print("Error: YUANDIAN_API_KEY not configured")
            print("Set it via: research config set api_keys.yuandian_key <key>")
            return

        text = ""
        if args.text:
            text = args.text
        elif args.file:
            text = Path(args.file).read_text()
        elif args.run_dir:
            draft = Path(args.run_dir) / "draft-report.md"
            if draft.exists():
                text = draft.read_text()
        else:
            print("Error: provide --text, --file, or --run-dir")
            return

        backend = YuandianBackend(api_key=api_key)
        result = backend.detect_hallucinations(text)
        regs = result.get("regulations", [])
        cases = result.get("cases", [])

        issues = []
        for r in regs:
            sc = r.get("semantic_compare", {})
            conclusion = sc.get("结论", "")
            if conclusion and conclusion not in {"语义比对一致", "语义比对无法确定"}:
                issues.append({
                    "type": "法规",
                    "name": r.get("name", ""),
                    "clause": r.get("clause", ""),
                    "conclusion": conclusion,
                    "detail": sc.get("说明", ""),
                })
        for c in cases:
            if c.get("case_number") and not c.get("think_tank_content"):
                issues.append({
                    "type": "案例",
                    "case_number": c.get("case_number", ""),
                    "conclusion": "未命中权威来源",
                    "detail": "案号未能匹配权威案例库",
                })

        output = {
            "total_regulations": len(regs),
            "total_cases": len(cases),
            "issues": issues,
            "hall_detect_raw": result,
        }
        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(f"检测到 {len(regs)} 条法规引用, {len(cases)} 条案例引用")
            if issues:
                print(f"⚠ 发现 {len(issues)} 个潜在问题:")
                for iss in issues:
                    print(f"  [{iss['type']}] {iss.get('name') or iss.get('case_number','')}: {iss['conclusion']}")
            else:
                print("✓ 未发现问题")


def cmd_finalize(args):
    from research.finalize import run_finalize
    result = run_finalize(args)
    print(f"FINAL_STATUS={result['status']}")
    print(f"REPORT={result.get('report_path', 'N/A')}")


def cmd_template(args):
    from research.template import cmd_template as _cmd_template
    _cmd_template(args)


def cmd_regtrack(args):
    from research.regtrack import (
        RegtrackStore, add_industry, check_industry,
        format_status, format_changes, _make_key,
    )
    from research.backends.yuandian import YuandianBackend
    from research.config import load_config
    cfg = load_config()
    api_key = cfg.get("api_keys", {}).get("yuandian_key", "")
    if not api_key:
        print("Error: YUANDIAN_API_KEY not configured")
        return
    backend = YuandianBackend(api_key=api_key)

    store = RegtrackStore.load(args.regtrack_file)

    if args.action == "add":
        if args.industry:
            keywords = _split_keywords(args.keywords) or [args.industry]
            region = args.region or ""
            store = add_industry(store, keywords, backend, region=region, count=args.count or 50)
            store.save(args.regtrack_file)
            key = _make_key(args.industry, region)
            n = len(store.industries[key].regulations) if key in store.industries else 0
            print(f"已注册行业「{args.industry}」, 跟踪 {n} 部法规")
        else:
            print("请指定 --industry")
        return

    if args.action == "remove":
        key = _make_key(args.industry, args.region or "") if args.industry else None
        if key and key in store.industries:
            del store.industries[key]
            store.save(args.regtrack_file)
            print(f"已移除行业「{args.industry}」")
        elif args.reg_id:
            removed = False
            for g in store.industries.values():
                before = len(g.regulations)
                g.regulations = [r for r in g.regulations if r.id != args.reg_id]
                if len(g.regulations) < before:
                    removed = True
            if removed:
                store.save(args.regtrack_file)
                print(f"已移除法规 ID: {args.reg_id}")
            else:
                print(f"未找到法规 ID: {args.reg_id}")
        elif args.industry:
            print(f"行业「{args.industry}」未注册")
        else:
            print("请指定 --industry 或 --id")
        return

    if args.action == "check":
        if args.industry:
            key = _make_key(args.industry, args.region or "")
            industries_to_check = [key]
        else:
            industries_to_check = list(store.industries.keys())
        all_changes = []
        for kw in industries_to_check:
            if kw not in store.industries:
                print(f"行业「{kw}」未注册，请先 add --industry")
                continue
            store, changes = check_industry(store, kw, backend,
                                            count=args.count or 50,
                                            since=args.since or "",
                                            until=args.until or "")
            all_changes.extend(changes)
        store.save(args.regtrack_file)
        print(format_changes(all_changes))
        return

    if args.action == "status":
        kw = _make_key(args.industry, args.region or "") if args.industry else None
        print(format_status(store, kw))
        if args.json:
            import json
            print(json.dumps({
                name: {
                    "keywords": g.keywords,
                    "added": g.added,
                    "last_checked": g.last_checked,
                    "region": g.region,
                    "regulation_count": len(g.regulations),
                    "regulations": [
                        {"id": r.id, "name": r.name, "status": r.status}
                        for r in g.regulations
                    ],
                }
                for name, g in store.industries.items()
            }, ensure_ascii=False, indent=2))
        return


def cmd_inject_cases(args):
    from research.inject import cmd_inject_cases as _cmd_inject_cases
    _cmd_inject_cases(args)


if __name__ == "__main__":
    main()
