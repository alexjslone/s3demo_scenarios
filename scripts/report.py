"""Build results/<demo_id>-results.md from recorded timings."""
from __future__ import annotations

from common import Ctx, base_parser, fmt_dur, load_manifest, log, parse_iso


def verified(ctx: Ctx, label: str) -> str:
    v = ctx.read_result(f"verify-{label}.json")
    return "n/a" if not v else ("PASS" if v["pass"] else "FAIL")


def rate(objs, secs) -> str:
    return f"{objs / secs * 60:,.0f}" if secs else "n/a"


def main() -> None:
    p = base_parser("Generate the timing table.")
    p.add_argument("--clumio-start", help="UTC ISO, e.g. 2026-11-05T17:10:00Z (from the Clumio UI)")
    p.add_argument("--clumio-end")
    ctx = Ctx(a := p.parse_args())
    base = load_manifest(ctx.manifest_path)
    seed = ctx.read_result("seed.json") or {}
    fin = [r for k, r in base.items() if k.startswith("finance/")]
    fin_objs, fin_bytes = len(fin), sum(int(r["size"]) for r in fin)
    rows = []

    ip = ctx.read_result("restore-in-place.json")
    if ip:
        rows.append(("AWS Backup in-place restore", "finance/ (restore job succeeded; corrupted objects NOT replaced)",
                     fin_objs, fin_bytes, ip["duration_s"], 0, "aws-inplace"))
    for mode, label, name in (("prefix", "aws-prefix", "AWS Backup prefix restore + copy back"),
                              ("full", "aws-full", "AWS Backup full-bucket restore + copy back")):
        r = ctx.read_result(f"restore-{mode}.json")
        if not r:
            continue
        cb = ctx.read_result(f"copyback-{mode}.json")
        rows.append((name, ", ".join(r["scope"]) + " -> recovery bucket -> finance/", fin_objs, fin_bytes,
                     r["duration_s"], cb["duration_s"] if cb else 0, label))
    if a.clumio_start and a.clumio_end:
        d = (parse_iso(a.clumio_end) - parse_iso(a.clumio_start)).total_seconds()
        rows.append(("Clumio recovery (UI)", "finance/ only (prefix filter)", fin_objs, fin_bytes, d, 0, "clumio"))

    lines = [f"# Scenario 2 results: {ctx.demo_id}", "",
             f"- Region: {ctx.region}",
             f"- Dataset profile: {seed.get('dataset_profile', 'unknown')}",
             f"- Bucket total: {seed.get('objects', len(base)):,} objects, {seed.get('bytes', 0) / 1e9:.2f} GB",
             f"- finance/: {fin_objs:,} objects, {fin_bytes / 1e9:.2f} GB", "",
             "| Method | Scope | Objects | Bytes | Restore time | Copy back time | End to end | Objects/min | Verified |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, scope, objs, size, rt, cbt, label in rows:
        e2e = rt + cbt
        lines.append(f"| {name} | {scope} | {objs:,} | {size:,} | {fmt_dur(rt)} | {fmt_dur(cbt) if cbt else '-'} | "
                     f"{fmt_dur(e2e)} | {rate(objs, e2e)} | {verified(ctx, label)} |")
    inc = ctx.read_result("incident.json")
    bk = ctx.read_result("backup.json")
    lines += [""]
    if bk:
        lines.append(f"- On-demand backup: {bk['state']} in {fmt_dur(bk['duration_s'])} (recorded {bk['end']})")
    if inc:
        lines.append(f"- Incident window: {inc['incident_start']} to {inc['incident_end']}")
    lines.append("- Timings measured by this repo; re-measure for each customer run (conditions vary).")
    out = ctx.result_path("results.md")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Wrote %s", out)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
