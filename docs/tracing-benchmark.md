# Tracing Benchmark v0.2（诚实评分）

> t5 交付物。全部数字来自 `bench/run_bench.py` 实测（合成图 → `trace_drawing`
> 真实管线 → `verify_plan(plan, gt, level='auto')` 真实 verifier），产物见
> `bench/out/`（`dxf/` 8 件、`preview/` 8 件、`report.json` 全量报告）。
> 复跑：`/opt/homebrew/opt/python@3.12/bin/python3.12 bench/run_bench.py`
> （需 ezdxf/PIL；默认 python3.14 缺依赖，见下环境说明）。
> 门限测试：`tests/test_bench_v02.py`（6 项，pytest 全绿的一部分）。

---

## 1. 总览（三级 + 负对照 + 基线）

| case | level | 实体（loop+rib） | verdict | recall | loop IoU | scale_err | bbox（参考） |
|------|-------|-----------------|---------|--------|----------|-----------|--------------|
| L1a（100×40 矩形 + 100 标注） | L1 | 1 | **PASS** | 1/1 | 0.9938 | —（shape-only） | 0.9913 |
| L1b（80×60 矩形 + 80 标注） | L1 | 1 | **PASS** | 1/1 | 0.9886 | — | 0.9903 |
| L1c（40×25 矩形 + 40 标注） | L1 | 1 | **PASS** | 1/1 | 0.9901 | — | 0.9839 |
| L1a-manual（同图，无 OCR） | L1 | 1 | **PASS（t6 归一化门，N1 已关闭）** | 1/1 | 0.8048（绝对）/ 1.0000（归一化门） | —（shape-only） | 0.8059 |
| L2a（L  bracket + 孔 + 筋 + 120/20） | L2 | 3 | **PASS** | 3/3 | 0.9932 / 0.9833 | 0.83% | 0.9944 |
| L2b（板 + 双孔 + 筋 + 100/12） | L2 | 4 | **PASS** | 4/4 | 0.9958 / 0.9792 / 0.9688 | 1.55% | 0.9934 |
| L3a（板 + 三孔 + 双筋 + 120/12） | L3 | 6 | **PASS（参考级，见 N3）** | 5/6 | 0.9964 / 0.9792 / 0.975 / 0.9688 | 1.55% | 0.9944 |
| L2-neg（单矩形冒充 L2a） | L2 | 3 | **FAIL（预期）** | 0/3 | 0.5238 / 0.0 | 0.0%（键不可验证） | **1.0** |

v0.1 最优手测基线（polygon 取真值角点 + 真值 scale，经 `upgrade_v01`）：
L1a/L1b/L1c 均为 **PASS 1/1**。

> L1a-manual 行说明：`bench/out/report.json` 为 t5 快照（该行 FAIL）；
> t6 用同一管线（`B.run_case(B.l1_manual_case())`，同一代码同一合成图）复测
> verdict=**PASS**（绝对 IoU=0.8048，归一化 IoU=1.0，`gate=normalized`，报告合规），
> 上表为复测值。`bench/out/` 未重跑刻意保持 t5 产物原样；N1 细节见 §3。

## 2. 发布门判定（spec §8.4）

| 门 | 条件 | 实测 | 结论 |
|----|------|------|------|
| L1 不退化 | v0.2 通过率 ≥ v0.1 基线 | 3/3 vs 3/3 | ✅ PASS |
| L2 recall | 平均 ≥90%，单 case ≥80% | 平均 100%，最小 100% | ✅ PASS |
| 反冒充 | §8.3 全过，负对照 FAIL | `single_outer_spoof` + `ribs_empty` 开火，verdict FAIL；bbox=1.0 仍 FAIL | ✅ PASS |
| 全绿 | pytest 全过 + DXF/preview/report 齐 | 90 passed（84＋6 t6 回归）；`bench/out` 8 DXF + 8 preview + report.json（t5 快照） | ✅ PASS |

**RELEASE：满足发布门。**

细节：
- L2a/L2b/L3a 的 scale 全部为 `dimension` anchor（`uncertain=false`），
  手猜 scale 已消除（R4 关闭）；anchor/bbox 交叉检查（§6）全过。
- L3a rib_0（横筋）端点误差 1.008mm，距 1.0mm 门限差 0.008mm 未召回；
  rib_1（竖筋）召回（0.28mm）。5/6 = 0.833 ≥ 0.80，verdict PASS，但余量最薄。
- L2-neg 的 bbox-IoU advisory = 1.0（包围盒完全相同）仍被判 FAIL——R5 验收漏洞已封死。

## 3. 已知缺口（诚实部分，不拦发布门但必须跟进）

- **N1 — ✅ 已关闭（t6）。manual/uncertain L1 归一化 IoU 双轨落地。**
  L1a-manual（无 OCR，fallback S=3.78）：检测形状完全正确（plan 外环
  105.82×42.33 vs 真值 100×40，w/h 比 2.4995 vs 2.5），绝对 IoU=0.8048 < 0.90。
  t6 在 verifier 增加双轨：`level==L1 且 anchor==manual` 时 per-loop 改用归一化
  IoU 门（平移＋均匀缩放不变，旋转/长宽比仍可见；实现 `geometry.normalized_iou`），
  绝对 IoU/scale 误差保留为 advisory（`gate` 字段注明 `normalized`/`absolute`）。
  复测：归一化 IoU=1.0 → verdict **PASS**，recall 1/1，报告合规；
  L2/L3 与 solved-anchor L1 走绝对轨，与 t5 快照逐位一致（`test_solved_anchor_l1_stays_absolute_track`）。
  防护：长宽比错误（2.5 vs 2.0）的 manual-L1 仍 FAIL；manual 单矩形冒充 L2 仍被
  §8.3.3 拦截（无归一化救援）。回归单测 `tests/test_manual_l1_normalized.py`（6 项）。
  spec §8 以其原文为准，本改动只加 previously-missing 的 L1-shape-only 分支，
  未动 schema（`plan-v02.schema.json` 无冲突：plan 结构零改动，报告加可选键）。
- **N2 — `key_dimensions` 边索引依赖 GT/plan 点序对应。**
  方孔键天然稳定（正方形任一边等长）；外轮廓长边键（L2a `k_outer_top`）
  按“同一物理边”与当前 tracer 点序对齐（`bench_lib.L2A_TOP_EDGE=[4,5]`，
  GT 多边形本身不变）。tracer 若改动轮廓起点/方向，bench 会显式 FAIL
  而非静默通过——这是故意的敏感性，不是 bug。
- **N3 — verifier 无 L3 专属推理。**
  `infer_level` 只分 L1/L2；L3a 沿用 L2 门限记 `PASS(ref)`，非冻结门限。
  L3 当前覆盖：outer + 3 hole + 2 rib 六实体；notch 角色管线不产生
  （`assign_roles` 只出 outer/detail/hole），GT 因此不设 notch。
- **N4 — rib 可检测形态有约束。**
  rib 须为背景孤立细条且宽 ≤8px（`rib_max_width_px`）：L2a 初版 10px 条被
  当成 detail 环、L2b/L3 初版“嵌在板内”的筋条与填充融合不可见。
  真实图纸中框内筋线需要 t2 后续支持（线型分离），bench 已按当前能力
  如实取材，不虚报。

## 4. 覆盖声明（没测什么）

- `verifier/jev_judge.py`（t4 云 Choice/本地启发式）未接入 bench（尚无
  segment 管线可供端到端调用），由其 6 项单测独立覆盖。
- bench 图全为合成轴对齐几何；真实扫描图（噪声/旋转/手写标注）不在本轮覆盖内。
- L1 带标注形态（L1a/b/c）与 manual 形态（L1a-manual）检测侧全过；
  §8.1 允许的 `uncertain=true` L1 形态验收侧原受 N1 限制，t6 归一化门落地后
  manual-L1 已可 PASS（绝对 scale 仍 advisory，不可宣称尺寸正确）。

## 5. 产物索引

- 报告：`bench/out/report.json`（全部 verdict/recall/margin + 本表的机器版）
- DXF：`bench/out/dxf/{L1a,L1b,L1c,L1a-manual,L2a,L2b,L3a,L2-neg}.dxf`
- 预览：`bench/out/preview/<同名>.png`（左输入图，右 plan 叠加：outer 绿/hole 红/rib 蓝）
- 复现：`bench/bench_lib.py`（绘图 + GT 构造）→ `bench/run_bench.py`（落盘）
  → `tests/test_bench_v02.py`（门限断言）
- 环境：py3.12（pytest 9.0.3 + ezdxf 1.4.4 + PIL + numpy）；
  默认 `python3`（3.14）无 pytest/ezdxf，**不要用它跑 bench**。
