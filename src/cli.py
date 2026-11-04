import argparse
import json
import sys
from pathlib import Path

from .runner import ROOT, build_agent, load_env


def scan_pending(data_dir, drafts_file=None):
    materials = json.loads((Path(data_dir) / "materials.json").read_text(encoding="utf-8"))
    drafts_path = Path(drafts_file) if drafts_file else Path(data_dir) / "drafts.json"
    scheduled = set()
    if drafts_path.exists():
        drafts = json.loads(drafts_path.read_text(encoding="utf-8"))
        saved = drafts.get("drafts", [])
        scheduled = {d["material_id"] for d in saved if d.get("status") == "pending_confirmation"}
    pending = [
        {"id": m["id"], "title": m.get("title"), "review_status": m.get("review_status")}
        for mid in sorted(materials)
        for m in [materials[mid]]
        if mid not in scheduled
    ]
    print(json.dumps({"pending_materials": pending}, ensure_ascii=False, indent=2))


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="publish-scheduler",
        description="素材审核与发布排期 Agent：审核素材、检查时段冲突、保存待确认排期草稿（不发布）",
    )
    parser.add_argument("--input", "-i", help="任务 JSON 文件；提供时优先于命令行参数")
    parser.add_argument("--material", "-m", help="素材 ID，如 M01")
    parser.add_argument("--date", help="要求的发布日期，YYYY-MM-DD")
    parser.add_argument("--time", dest="time", help="要求的发布时段，HH:MM（24 小时整点）")
    parser.add_argument("--llm", choices=["mock", "openai"], default=None, help="模型提供方，默认取 .env 的 LLM_PROVIDER，再默认 mock")
    parser.add_argument("--max-steps", type=int, default=10, help="执行步数上限，达到上限返回未完成状态")
    parser.add_argument("--data-dir", default=str(ROOT / "data"), help="数据目录（素材/规则/已有排期）")
    parser.add_argument("--drafts-file", default=None, help="草稿存储文件路径，默认 data/drafts.json")
    parser.add_argument("--out", default=None, help="输出目录：写入 output.json / trace.json / trace.md")
    parser.add_argument("--scan", action="store_true", help="仅列出待处理素材，不运行 Agent")
    parser.add_argument("--simulate-save-failure", action="store_true", help="注入保存故障，验证失败路径")
    args = parser.parse_args(argv)

    load_env()
    if args.scan:
        tools_drafts = Path(args.drafts_file) if args.drafts_file else Path(args.data_dir) / "drafts.json"
        materials = json.loads((Path(args.data_dir) / "materials.json").read_text(encoding="utf-8"))
        scheduled = set()
        if tools_drafts.exists():
            data = json.loads(tools_drafts.read_text(encoding="utf-8"))
            scheduled = {d["material_id"] for d in data.get("drafts", [])}
        pending = [
            {"id": materials[mid]["id"], "title": materials[mid].get("title"), "review_status": materials[mid].get("review_status")}
            for mid in sorted(materials)
            if mid not in scheduled
        ]
        print(json.dumps({"pending_materials": pending}, ensure_ascii=False, indent=2))
        return 0

    spec = {}
    if args.input:
        spec = json.loads(Path(args.input).read_text(encoding="utf-8"))
    material_id = args.material or spec.get("material_id")
    date = args.date or spec.get("requested_date")
    time = args.time or spec.get("requested_time")
    if not (material_id and date and time):
        parser.error("需要提供 --material/--date/--time 或 --input 任务文件；或使用 --scan / --help")
    task = {"material_id": material_id, "requested_date": date, "requested_time": time}
    max_steps = int(spec.get("max_steps", args.max_steps))
    drafts_file = args.drafts_file or spec.get("drafts_file")

    agent = build_agent(
        args.data_dir,
        drafts_file=drafts_file,
        provider=args.llm,
        max_steps=max_steps,
        simulate_save_failure=args.simulate_save_failure,
    )
    run = agent.run(task)

    if args.out:
        outdir = Path(args.out)
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "trace.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        (outdir / "output.json").write_text(
            json.dumps(
                {"status": run["status"], "steps_used": run["steps_used"], "final_result": run["final_result"]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        from .trace import run_to_markdown

        (outdir / "trace.md").write_text(run_to_markdown(run), encoding="utf-8")
    summary = {
        "status": run["status"],
        "steps_used": run["steps_used"],
        "max_steps": run["max_steps"],
        "final_result": run["final_result"],
    }
    if args.out:
        summary["trace_files"] = [str(Path(args.out) / "trace.md"), str(Path(args.out) / "trace.json")]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if run["status"] in ("completed",) else 1


if __name__ == "__main__":
    raise SystemExit(main())
