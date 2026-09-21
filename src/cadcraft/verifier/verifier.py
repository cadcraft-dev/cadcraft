"""Hardened per-loop verifier (t3, anti-R5; t6 manual-L1 dual track).

Implements docs/plan-v02-spec.md §7 (per-loop IoU, rib scoring, scale
check, D2–D4 structural checks) and §8.3 (anti-single-rectangle hard
fails). ``bbox-IoU`` is computed but **never** decides the verdict (D7).

Dual track (t6, closes bench gap N1): when ``level == "L1"`` and the plan
scale anchor is ``manual`` (no trusted OCR size, spec §5 "L1 只看归一化形状"),
per-loop matching is scored on **normalized IoU** (translation +
uniform-scale invariant) while the absolute mm IoU is still computed and
reported; absolute key-dimension errors are recorded as advisories instead
of hard fails. Every other case (L2/L3, or L1 with a solved anchor) uses
the absolute track exactly as before — L2/L3 behaviour is bit-identical
to the t5 snapshot.

Ground-truth schema (test/bench fixture, mm CAD space)::

    {
      "loops": [{"id": "outer_0", "role": "outer",
                 "points": [[x_mm, y_mm], ...]}],
      "ribs": [{"id": "rib_0", "centerline": [...], "width_mm": 6.0}],
      "key_dimensions": [{"id": "k_width", "loop_id": "outer_0",
                          "edge": [0, 1], "length_mm": 120.0}]
    }

``key_dimensions`` names absolute lengths the plan must reproduce within
2 % (§7.3); each names a GT loop edge by vertex index. L2/L3 ground truth
without key dimensions is unverifiable and fails the scale gate.
"""

from __future__ import annotations

from .. import geometry as G
from ..plan_io import PlanError, validate_plan

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"

MIN_RECALL = 0.80  # §8.2 single-case floor
REQUIRED_REPORT_KEYS = ("verdict", "per_loop", "ribs", "scale_error_pct",
                        "bbox_iou_advisory")


def _fail_report(reason: str, level: str, extra: dict | None = None) -> dict:
    report = {
        "verdict": VERDICT_FAIL,
        "level": level,
        "recall": 0.0,
        "recall_detail": {"recalled": 0, "total": 0},
        "per_loop": [],
        "ribs": [],
        "scale_error_pct": None,
        "bbox_iou_advisory": None,
        "hard_fails": [reason] if reason else [],
        "warnings": [],
        "reasons": [reason] if reason else [],
    }
    if extra:
        report.update(extra)
    return report


def infer_level(gt: dict) -> str:
    """L1 iff the GT is a single loop with no ribs, else L2."""
    loops = gt.get("loops", [])
    ribs = gt.get("ribs", [])
    if len(loops) <= 1 and len(ribs) == 0:
        return "L1"
    return "L2"


def check_report_conformance(report: dict) -> tuple[bool, list[str]]:
    """§8.3.4: a verifier report without per-loop detail is non-conformant.

    Legacy ``{"bbox_iou": ..., "passed": ...}`` blobs fail here — they can
    never count as a pass no matter how high the bbox number is.
    """
    problems: list[str] = []
    if not isinstance(report, dict):
        return False, ["report must be an object"]
    for key in REQUIRED_REPORT_KEYS:
        if key not in report:
            problems.append(f"missing required key: {key}")
    if not isinstance(report.get("per_loop"), list) or not report.get("per_loop"):
        problems.append("per_loop must be a non-empty array (§8.3.4)")
    else:
        for entry in report["per_loop"]:
            for key in ("id", "role", "iou", "matched"):
                if not isinstance(entry, dict) or key not in entry:
                    problems.append(f"per_loop entry missing {key}")
                    break
    if report.get("verdict") not in (VERDICT_PASS, VERDICT_FAIL):
        problems.append("verdict must be PASS or FAIL")
    return (len(problems) == 0, problems)


def _overall_bbox(loops: list) -> list | None:
    pts = [p for loop in loops for p in loop.get("points", [])]
    if not pts:
        return None
    return G.bbox_of(pts)


def _match_loops(gt_loops: list, plan_loops: list, cell: float):
    """Greedy same-role one-to-one matching by polygon IoU.

    Returns list of (gt_loop, plan_loop|None, iou).
    """
    pool: dict[str, list] = {}
    for pl in plan_loops:
        pool.setdefault(pl.get("role"), []).append(pl)
    matches = []
    for gl in gt_loops:
        best, best_iou = None, 0.0
        for cand in pool.get(gl.get("role"), []):
            iou = G.polygon_iou(gl["points"], cand["points"], cell=cell)
            if iou > best_iou:
                best, best_iou = cand, iou
        if best is not None:
            pool[gl.get("role")].remove(best)
        matches.append((gl, best, best_iou))
    matched_ids = {id(p) for _, p, _ in matches if p is not None}
    extras = [pl for pl in plan_loops if id(pl) not in matched_ids]
    return matches, extras


def _rib_endpoint_error(gt_cl, plan_cl) -> float:
    """Max endpoint distance, orientation-free (min over both flips)."""
    a0, a1 = gt_cl[0], gt_cl[-1]
    b0, b1 = plan_cl[0], plan_cl[-1]
    straight = max(G.segment_length(a0, b0), G.segment_length(a1, b1))
    flipped = max(G.segment_length(a0, b1), G.segment_length(a1, b0))
    return min(straight, flipped)


def _match_ribs(gt_ribs: list, plan_ribs: list):
    """Greedy matching by endpoint error. Returns (gt, plan|None, err)."""
    pool = list(plan_ribs)
    matches = []
    for gr in gt_ribs:
        best, best_err = None, float("inf")
        for cand in pool:
            err = _rib_endpoint_error(gr["centerline"], cand["centerline"])
            if err < best_err:
                best, best_err = cand, err
        if best is not None:
            pool.remove(best)
        matches.append((gr, best, best_err if best is not None else None))
    return matches


def verify_plan(plan: dict, gt: dict, level: str = "auto",
               cell: float = 0.25) -> dict:
    """Verify one v0.2 plan against ground truth. Never raises on plan
    content problems — those become FAIL reports (bench-safe)."""
    gt = gt or {}
    gt_loops = gt.get("loops", [])
    gt_ribs = gt.get("ribs", [])
    key_dims = gt.get("key_dimensions", [])
    if level == "auto":
        level = infer_level(gt)

    try:
        validate_plan(plan)
    except PlanError as exc:
        return _fail_report(f"plan_invalid: {exc}", level)

    plan_loops = plan["loops"]
    plan_ribs = plan["ribs"]
    hard_fails: list[str] = []
    warnings: list[str] = []
    reasons: list[str] = []

    # --- §8.3.1 single-outer spoof -------------------------------------
    if (len(gt_loops) >= 2 or len(gt_ribs) >= 1) and len(plan_loops) == 1 \
            and plan_loops[0].get("role") == "outer":
        hard_fails.append(
            "single_outer_spoof: GT has "
            f"{len(gt_loops)} loops + {len(gt_ribs)} ribs but plan has a "
            "single outer (§8.3.1)")

    # --- §8.3.2 missing ribs --------------------------------------------
    if len(gt_ribs) >= 1 and len(plan_ribs) == 0:
        hard_fails.append(
            f"ribs_empty: GT has {len(gt_ribs)} rib(s) but plan has none (§8.3.2)")

    # --- scale anchor gates (§5, §6, §8.3.3) -------------------------------
    anchor = plan["scale"]["anchor"]
    if anchor["type"] == "manual":
        if level in ("L2", "L3"):
            hard_fails.append(
                "manual_anchor: scale.anchor.type==manual fails L2/L3 (§8.3.3)")
        else:
            warnings.append("manual_anchor: scale unverifiable, L1 shape-only")
    else:
        abbox = anchor.get("bbox_px")
        if not abbox:
            hard_fails.append("anchor_crosscheck: dimension/bar anchor lacks bbox_px (§6)")
        else:
            hit = [t for t in plan.get("texts_masked", [])
                   if t.get("used_as_anchor") and list(t.get("bbox_px", [])) == list(abbox)]
            if not hit:
                hard_fails.append(
                    "anchor_crosscheck: anchor bbox_px has no equal "
                    "texts_masked entry with used_as_anchor=true (§6)")
        # Internal consistency: px_per_mm must equal px_length/real_length.
        s = float(plan["scale"]["px_per_mm"])
        implied = float(anchor["px_length"]) / float(anchor["real_length_mm"])
        if s > 0 and abs(s - implied) / s > 0.005:
            hard_fails.append(
                f"scale_inconsistent: px_per_mm={s} vs anchor-implied {implied:.4f} (§5)")

    # --- t6/N1 dual track --------------------------------------------------
    # manual anchor on L1: absolute scale is unverifiable by construction,
    # so the per-loop gate runs on normalized (shape-only) IoU while the
    # absolute numbers stay on the report as advisories. L2/L3 + solved
    # anchors never enter this branch.
    manual_l1 = (level == "L1" and anchor["type"] == "manual")
    if manual_l1:
        warnings.append(
            "manual_l1_normalized_gate: anchor=manual, L1 scored on "
            "normalized IoU>=0.90; absolute IoU/scale advisory-only (§5/N1)")

    # --- structural per-loop checks (D2–D4 detail) -------------------------
    struct: dict[str, dict] = {}
    for loop in plan_loops:
        flags = {"closure_ok": True, "winding_ok": True,
                 "self_intersect_ok": True, "problems": []}
        ok, msg = G.loop_closure_ok(loop)
        if not ok:
            flags["closure_ok"] = False
            flags["problems"].append(msg)
        ok, msg = G.winding_ok(loop)
        if not ok:
            # D3: wrong winding fails the loop — correct-and-warn, never
            # silent-pass. The caller must fix the winding and re-run.
            flags["winding_ok"] = False
            flags["problems"].append(msg)
        if G.has_self_intersection(loop["points"]):
            flags["self_intersect_ok"] = False
            flags["problems"].append(
                f"loop {loop['id']}: self-intersecting polygon (D2)")
        struct[loop["id"]] = flags

    # --- §7.1 per-loop matching -------------------------------------------
    matches, extras = _match_loops(gt_loops, plan_loops, cell=cell)
    per_loop = []
    recalled_loops = 0
    for gl, pl, iou in matches:
        if pl is None:
            per_loop.append({"id": gl["id"], "gt_id": gl["id"], "plan_id": None,
                             "role": gl.get("role"), "iou": 0.0,
                             "iou_normalized": None,
                             "gate": "normalized" if manual_l1 else "absolute",
                             "matched": False, "reasons": ["unmatched"]})
            continue
        flags = struct[pl["id"]]
        entry_reasons = list(flags["problems"])
        iou_n = G.normalized_iou(gl["points"], pl["points"]) if manual_l1 else None
        gate, gate_iou = ("normalized", iou_n) if manual_l1 else ("absolute", iou)
        matched = (gate_iou >= G.LOOP_IOU_PASS and flags["closure_ok"]
                   and flags["winding_ok"] and flags["self_intersect_ok"])
        if not matched and gate_iou < G.LOOP_IOU_PASS:
            entry_reasons.append(
                f"{gate} iou {gate_iou:.3f} < {G.LOOP_IOU_PASS:.2f}")
        if matched:
            recalled_loops += 1
        per_loop.append({"id": gl["id"], "gt_id": gl["id"], "plan_id": pl["id"],
                         "role": gl.get("role"), "iou": round(iou, 4),
                         "iou_normalized": (round(iou_n, 4) if iou_n is not None
                                            else None),
                         "gate": gate,
                         "matched": matched, "reasons": entry_reasons})
    for extra in extras:
        warnings.append(
            f"extra plan loop {extra['id']} ({extra.get('role')}) not in GT")

    # --- §7.2 rib scoring ---------------------------------------------------
    rib_matches = _match_ribs(gt_ribs, plan_ribs)
    rib_reports = []
    recalled_ribs = 0
    for gr, pr, err in rib_matches:
        if pr is None:
            rib_reports.append({"gt_id": gr["id"], "plan_id": None,
                                "recalled": False, "endpoint_err_mm": None,
                                "width_err_pct": None,
                                "reasons": ["unmatched"]})
            continue
        gw = float(gr["width_mm"])
        pw = float(pr["width_mm"])
        width_err = abs(pw - gw) / gw if gw > 0 else float("inf")
        ok = (err <= G.RIB_ENDPOINT_TOL_MM and width_err <= G.RIB_WIDTH_REL_TOL)
        entry_reasons = []
        if err > G.RIB_ENDPOINT_TOL_MM:
            entry_reasons.append(
                f"endpoint error {err:.2f}mm > {G.RIB_ENDPOINT_TOL_MM:.1f}mm")
        if width_err > G.RIB_WIDTH_REL_TOL:
            entry_reasons.append(
                f"width error {width_err * 100:.1f}% > "
                f"{G.RIB_WIDTH_REL_TOL * 100:.0f}%")
        if ok:
            recalled_ribs += 1
        rib_reports.append({"gt_id": gr["id"], "plan_id": pr["id"],
                            "recalled": ok,
                            "endpoint_err_mm": round(err, 3),
                            "width_err_pct": round(width_err * 100, 2),
                            "reasons": entry_reasons})

    # --- §7.3 absolute scale check -------------------------------------------
    match_by_gt = {gl["id"]: pl for gl, pl, _ in matches}
    scale_errors: list[float] = []
    if key_dims:
        for kd in key_dims:
            gl = next((g for g in gt_loops if g["id"] == kd.get("loop_id")), None)
            pl = match_by_gt.get(kd.get("loop_id"))
            if gl is None or pl is None:
                reasons.append(
                    f"scale_unverifiable: key {kd.get('id')} references "
                    "unmatched GT loop")
                continue
            edge = kd.get("edge", [0, 1])
            try:
                a = pl["points"][edge[0] % len(pl["points"])]
                b = pl["points"][edge[1] % len(pl["points"])]
            except (IndexError, TypeError, KeyError):
                reasons.append(
                    f"scale_unverifiable: key {kd.get('id')} bad edge")
                continue
            got = G.segment_length(a, b)
            want = float(kd["length_mm"])
            rel = abs(got - want) / want if want > 0 else float("inf")
            scale_errors.append(rel)
            if rel > G.SCALE_REL_TOL:
                msg = (f"scale_error: key {kd.get('id')} {rel * 100:.2f}% > "
                       f"{G.SCALE_REL_TOL * 100:.0f}% "
                       f"(got {got:.2f}mm, want {want:.2f}mm)")
                # N1 dual track: on manual-L1 the absolute error is
                # expected (fallback S) — record, don't fail.
                (warnings if manual_l1 else reasons).append(
                    ("advisory " if manual_l1 else "") + msg)
        scale_error_pct = round(max(scale_errors) * 100, 3) if scale_errors else None
        if scale_errors and max(scale_errors) > G.SCALE_REL_TOL and not manual_l1:
            hard_fails.append("scale_gate: absolute dimension error > 2% (§7.3)")
        if any(r.startswith("scale_unverifiable") for r in reasons):
            hard_fails.append("scale_gate: key dimension unverifiable (§7.3)")
    else:
        scale_error_pct = None
        if level in ("L2", "L3"):
            hard_fails.append(
                "scale_gate: GT has no key_dimensions, scale unchecked (§7.3)")
        else:
            warnings.append("no key_dimensions: L1 shape-only, scale unchecked")

    # --- bbox advisory (D7: recorded, never decisive) --------------------------
    plan_bb = _overall_bbox(plan_loops)
    gt_bb = _overall_bbox(gt_loops)
    bbox_iou = G.bbox_iou(plan_bb, gt_bb) if (plan_bb and gt_bb) else None

    total = len(gt_loops) + len(gt_ribs)
    recalled = recalled_loops + recalled_ribs
    recall = (recalled / total) if total else 0.0

    if hard_fails:
        reasons = hard_fails + [r for r in reasons if r not in hard_fails]
    # Structural failures fail the case only when they sit on a *matched*
    # loop (they already forced matched=false above). Problems on extra,
    # unmatched plan loops stay warnings so recall semantics stay pure.
    matched_ids = {e["plan_id"] for e in per_loop if e.get("plan_id")}
    matched_problems = [f"{lid}: {'; '.join(f['problems'])}"
                        for lid, f in struct.items()
                        if f["problems"] and lid in matched_ids]
    extra_problems = [f"{lid}: {'; '.join(f['problems'])}"
                      for lid, f in struct.items()
                      if f["problems"] and lid not in matched_ids]
    if extra_problems:
        warnings.extend([f"loop_invalid (extra): {s}" for s in extra_problems])
    if matched_problems:
        reasons.extend([f"loop_invalid: {s}" for s in matched_problems])
    if total and recall < MIN_RECALL:
        reasons.append(
            f"recall {recall:.2f} < {MIN_RECALL:.2f} "
            f"({recalled}/{total} entities, §8.2)")

    fail = bool(hard_fails or matched_problems
                or (total and recall < MIN_RECALL))
    verdict = VERDICT_FAIL if fail else VERDICT_PASS

    return {
        "verdict": verdict,
        "level": level,
        "recall": round(recall, 4),
        "recall_detail": {"recalled": recalled, "total": total},
        "per_loop": per_loop,
        "ribs": rib_reports,
        "scale_error_pct": scale_error_pct,
        "bbox_iou_advisory": round(bbox_iou, 4) if bbox_iou is not None else None,
        "hard_fails": hard_fails,
        "warnings": warnings,
        "reasons": reasons,
    }
