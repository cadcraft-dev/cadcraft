# Plan Schema v0.2 规范 — L2 故障复盘 + 多轮廓 / 比例尺锚 / 加强筋扩展

> 任务 t1 交付物。自主决策冻结版（不再向用户提问），下游 t2 / t3 / t4 / t5 以此为唯一契约。
> 机器可读 Schema：`docs/plan-v02.schema.json`（与本文第 4 节等价，冲突时以 `.json` 为准）。
> 版本：v0.2.0 ｜ 日期：2026-09-21 ｜ 作者：tracer

---

## 1. 背景与目标

- L1（单矩形 / 单轮廓 tracing）已通过，但属于弱通过：verifier 只比**大包围盒 IoU**，任何能框住目标的单矩形都能拿高分。
- L2 `level2_bracket`（角支架：外轮廓 L 形 + 内孔 + 加强筋 rib + 尺寸标注文字）首次暴露该弱验收：**输出半对**——外形大致框对，内孔/缺口/加强筋全丢，比例尺靠手猜，仍被旧 verifier 判“通过/半通过”。
- v0.2 目标：把 Plan 从“单个多边形 + 手填 scale”升级为“**多 loop + scale anchor + rib 标记**”，并把验收线收紧到**实体级召回**，彻底封死“单矩形冒充通过”。

---

## 2. L2 `level2_bracket` 半对故障复盘

### 2.1 “半对”的具体表现（现象）

| # | 现象 | 后果 |
|---|------|------|
| P1 | 输出只有 1 个外包矩形/外轮廓，L 形缺口被填平 | 缺口实体召回 = 0 |
| P2 | 内孔（通孔）完全丢失 | 孔实体召回 = 0 |
| P3 | 加强筋 rib 线（细线）被当噪点滤掉 | rib 召回 = 0 |
| P4 | 尺寸标注文字（"120", "Ø20" 等）污染几何检测，轮廓被文字截断/粘连 | 外轮廓 IoU 虚低或虚高，不稳定 |
| P5 | `scale`（px/mm）手填固定值，与图实际比例尺偏差可达 ±15% | 绝对尺寸全错，但旧 verifier 只看归一化 IoU所以发现不了 |

按实体计数：bracket 真值实体 ≈ 外轮廓(1) + L 形缺口边(≥1，计入外轮廓 loop 形状) + 内孔(≥1) + rib(≥1)，
旧 pipeline 只对了“大致外形”1 项 → **约 40–50% 实体正确 = “半对”**。

### 2.2 根因分析（R1–R5）

- **R1 — Plan v0.1 只能表达单轮廓（schema 天花板）。**
  v0.1 的 `polygon`/`bbox` 单字段设计，使 tracer 即使检测到多轮廓也无处可放，
  下游 executor 只能出单实体 DXF。这是 P1/P2 的**根本原因**，不是调参能修的 → 必须升 schema（§4.1 multi-loop）。
- **R2 — 轮廓检索只取外轮廓。**
  OpenCV 风格 `RETR_EXTERNAL` / 最大连通域逻辑天然丢弃内孔；L 形凹缺口在多边形近似（过大 epsilon）下被磨平。
  这是 P1/P2 的**算法原因** → t2 必须用 `RETR_CCOMP`/`RETR_TREE` 等级 + 分 loop 输出。
- **R3 — OCR/标注文字未先掩膜（text-mask 缺失）。**
  尺寸数字和标注线先被当成几何吃进二值图，导致轮廓粘连、断裂。这是 P4 的原因 → t2 必须“OCR 文字区先掩膜再检测”（§6）。
- **R4 — 比例尺靠手猜（scale solver 缺失）。**
  v0.1 `scale_px_per_mm` 为手填常量；同一批图分属不同导出比例时系统性偏 10–20%。
  旧 verifier 用归一化 IoU，对绝对尺度**完全失明**，这是 P5 被长期掩盖的原因 → 必须做 scale anchor（§5）。
- **R5 — verifier 只看大包围盒 IoU（验收漏洞）。**
  单矩形只要框住 bracket，bbox-IoU 就能 ≥0.8，“半对”被判“通过”。
  这是**流程原因**：弱验收纵容了 R1–R4 长期存在 → v0.2 验收必须逐 loop 实体召回（§7、§8），bbox-IoU 降级为参考值。

### 2.3 根因 → 修复映射

| 根因 | 修 nowhere-else | 落点任务 |
|------|----------------|----------|
| R1 单轮廓天花板 | multi-loop loops[] | 本 spec §4.1 → t2 实现，t3 出多实体 DXF |
| R2 只取外轮廓 | 连通域分级 + 多 loop 缝合 | t2 |
| R3 文字污染 | OCR 先掩膜再检测 + texts_masked 留痕 | 本 spec §6 → t2 |
| R4 手猜 scale | scale_anchor + 最长 OCR 尺寸反推 | 本 spec §5 → t4 |
| R5 bbox 验收漏洞 | 逐 loop 召回 + 反单矩形规则 | 本 spec §7/§8 → t3/t5 |

---

## 3. Plan v0.1 回顾（重建，供兼容对照）

```json
{
  "version": "0.1",
  "units": "mm",
  "scale_px_per_mm": 3.78,
  "polygon": [[x, y], "..."],
  "bbox": [x0, y0, x1, y1]
}
```

v0.1 问题定性：单 `polygon`（R1）、`scale` 无来源不可审计（R4）、无文字掩膜留痕（R3）、
verifier 只消费 `bbox`（R5）。v0.2 **向后兼容读取 v0.1**（§4.5），但 v0.1 输出**永远过不了** v0.2 的 L2 验收（§8.3）。

---

## 4. Plan Schema v0.2（规范正文）

### 4.1 顶层结构

```json
{
  "version": "0.2",
  "units": "mm",
  "image": { "width_px": 0, "height_px": 0, "source": "" },
  "scale": {
    "px_per_mm": 0.0,
    "anchor": { "...见§5..." },
    "uncertain": false
  },
  "loops": ["...见§4.2，至少 1 个 outer..."],
  "ribs": ["...见§4.3，可为空数组..."],
  "texts_masked": ["...见§6，可为空数组..."],
  "meta": { "tracer": "", "created_at": "", "notes": "" }
}
```

字段规则：

| 字段 | 必需 | 说明 |
|------|------|------|
| `version` | ✅ | 必须为 `"0.2"` |
| `units` | ✅ | 必须为 `"mm"`（唯一合法单位） |
| `image` | ✅ | 原图尺寸 + 来源文件名，用于复现 px→mm 变换 |
| `scale` | ✅ | px/mm + anchor（§5），`uncertain=true` 时 verifier 必须警告但仍可跑 L1 |
| `loops` | ✅ | ≥1 个；恰好 1 个 `role=outer`；其余为 hole/notch/detail（§4.2） |
| `ribs` | ✅ | 可 `[]`；L2 bracket 不得为空（§8.3 反冒充规则） |
| `texts_masked` | ✅ | 可 `[]`；凡调用 OCR 即必须如实填写 |
| `meta` | ❌ | 可选，调试信息 |

### 4.2 loops[] — 多轮廓（multi-loop）

每个 loop：

```json
{
  "id": "outer_0",
  "role": "outer | hole | notch | detail",
  "points": [[x_mm, y_mm], "..."],
  "closed": true,
  "area_mm2": 0.0,
  "confidence": 0.0,
  "source": "stitched | detected | ocr-derived"
}
```

- `role` 语义：`outer` 外边界（恰 1 个）；`hole` 完全被 outer 包围的闭合内孔；
  `notch` 与 outer 相接的凹缺口（允许与 outer 共享边）；`detail` 其他闭合细节。
- 坐标系（冻结决策 D1）：**CAD 系，x 向右、y 向上，单位 mm**；图像系（x 向右、y 向下、原点左上）
  → CAD 系的变换为 `x_mm = x_px / S`，`y_mm = (H_px - y_px) / S`（S = px_per_mm，H_px = 图高）。
  tracer 负责变换，plan 里只存 CAD 系。
- 闭合性（D2）：所有 loop `closed` 必须为 `true`，首尾点距离 ≤ `0.05mm`；
  点数 ≥3；自交多边形非法。
- 环绕方向（D3）：`outer` 为逆时针（CCW，有向面积 >0），`hole` 为顺时针（CW）；
  verifier 按此校验，方向反了判该 loop 不合格（可自动纠正并警告，不得静默通过）。
- 面积单调性（D4）：`Σhole 面积 < 50% outer 面积`，否则判 plan 非法（防把外形当孔套娃）。
- L1 兼容：L1 单矩形 case 允许 `loops == [outer]` 单元素；此时 v0.2 退化为 v0.1 语义（§8.1）。

### 4.3 ribs[] — 加强筋标记

rib 是**中心线 + 宽度**的标注体，不是闭合 loop（这是与 hole 的本质区别）：

```json
{
  "id": "rib_0",
  "centerline": [[x_mm, y_mm], "...至少 2 点..."],
  "width_mm": 0.0,
  "extends_mm": [0.0, 0.0],
  "confidence": 0.0
}
```

- `centerline` ≥2 点（折线允许）；`width_mm > 0`；端点外延 `extends_mm` 记录筋超出/嵌入边界的长度（可为 0）。
- rib 必须整体落在 `outer` 内（允许端点触边，超出 0.5mm 即不合格）。
- L2 bracket 真值 rib ≥1 → plan `ribs` 为空在 L2 直接判不合格（§8.3）。

### 4.4 最小示例（L2 bracket，应含 outer + hole + rib）

```json
{
  "version": "0.2",
  "units": "mm",
  "image": { "width_px": 1200, "height_px": 900, "source": "level2_bracket.png" },
  "scale": {
    "px_per_mm": 4.0,
    "anchor": {
      "type": "dimension",
      "ocr_text": "120",
      "real_length_mm": 120.0,
      "px_length": 480.0,
      "bbox_px": [100, 800, 580, 840],
      "confidence": 0.93
    },
    "uncertain": false
  },
  "loops": [
    { "id": "outer_0", "role": "outer", "points": [[0,0],[120,0],[120,40],[40,40],[40,80],[0,80]], "closed": true, "area_mm2": 6400.0, "confidence": 0.95, "source": "stitched" },
    { "id": "hole_0", "role": "hole", "points": [[15,15],[15,25],[25,25],[25,15]], "closed": true, "area_mm2": 100.0, "confidence": 0.9, "source": "detected" }
  ],
  "ribs": [
    { "id": "rib_0", "centerline": [[40,40],[80,40]], "width_mm": 6.0, "extends_mm": [0.0, 0.0], "confidence": 0.85 }
  ],
  "texts_masked": [
    { "text": "120", "bbox_px": [100,800,580,840], "used_as_anchor": true }
  ],
  "meta": { "tracer": "t2-stitch", "notes": "L-shape outer + 1 hole + 1 rib" }
}
```

### 4.5 兼容规则（冻结决策 D4）

1. Reader 必须能读 v0.1（`polygon`→`loops=[outer]`，`scale_px_per_mm`→`scale.px_per_mm` + `anchor.type=manual` + `uncertain=true`）。
2. Writer 只写 v0.2。
3. v0.1 升级输入在 L2/L3 验收中**一律判不合格**（anchor=manual 且 loops 单一，不满足 §8.3）。

---

## 5. Scale Solver 契约（scale anchor，供 t4 实现）

`scale.anchor` 结构：

```json
{
  "type": "dimension | bar | manual",
  "ocr_text": "120",
  "real_length_mm": 120.0,
  "px_length": 480.0,
  "bbox_px": [x0, y0, x1, y1],
  "confidence": 0.0
}
```

- 算法（冻结决策 D5）：OCR 全部尺寸文本 → 解析数值+单位 → 取**最长可信尺寸**（`real_length_mm` 最大且 confidence ≥0.5）
  反推 `S = px_length / real_length_mm`。最长者相对误差最小，这是选“最长”而非“最清晰”的数学理由。
- `type=bar`：图中有比例尺条时用条总长；`type=manual`：无任何 OCR 尺寸时的降级（必须同时 `uncertain=true`）。
- 无 anchor（OCR 全无）时：`uncertain=true`，允许跑 L1（L1 只看归一化形状），**禁止宣称 L2/L3 通过**。
- `px_per_mm` 精度：≥4 位有效数字；`image` 尺寸必须与计算 S 时用的图一致，否则 verifier 报错。
- t4 无 key 时本地启发式与云 Jev 返回**同一 schema**（字段可空但键齐全），verifier 不分支。

## 6. Text-mask 契约（供 t2 实现）

- 顺序铁律：**OCR → 掩膜（mask）→ 几何检测**。严禁先检测后补救。
- `texts_masked[]` 每项 `{ text, bbox_px, used_as_anchor }`；OCR 调过即必须填（空 OCR 填 `[]` 并在 meta 注明引擎/无 key）。
- 掩膜方法：bbox 外扩 2–3px 涂白（白底图）/涂黑（蓝晒图按底色），标注引线不断开几何：掩膜只盖文字 bbox，不盖引线。
- 最长 anchor 文本的 bbox 必须同时出现在 `texts_masked`（`used_as_anchor=true`）与 `scale.anchor.bbox_px`，两处坐标逐值相等——verifier 交叉检查，防 scale 编造。

## 7. Verifier 硬化要求（供 t3 实现，反 R5）

1. **逐 loop 匹配**：GT 每个 loop（outer/hole/notch）与 plan 同 role loop 做 IoU（CAD 系 mm 下栅格化或裁剪法求交并），
   Hungarian/贪心一对一匹配；IoU ≥0.90 算召回一个。**bbox-IoU 仅记录、永不作为通过判据。**
2. **rib 单独计分**：centerline 端点误差 ≤1.0mm 且宽度误差 ≤20% 算召回一条。
3. **scale 实检**：GT 关键绝对尺寸（如 120mm 边）与 plan 同边换算后相对误差 ≤2%，否则即使形状对也判不合格（杀 P5）。
4. **方向/闭合/面积检查**：§4.2 D2–D4 全部执行。
5. verdict 输出必须含 `per_loop[{id, role, iou, matched}]`, `ribs[{id, recalled}]`, `scale_error_pct`, `bbox_iou_advisory`，诚实可审计。

---

## 8. 验收线（v0.2 发布门，冻结）

### 8.1 L1 不退化

- L1 数据集（单矩形/单轮廓）用 v0.2 pipeline 重跑：通过率不得低于 v0.1 基线（baseline 以 t5 实测 v0.1 值为准，允许波动 ±1%，跌超即回归失败）。
- 允许 `loops==[outer]` + `ribs==[]` + `uncertain=true` 的 L1 形态通过 L1 门。

### 8.2 L2 实体召回 ≥90%

- 定义：`recall = 召回 GT 实体数 / GT 实体总数`，实体 = 每个 GT loop（outer/hole/notch/detail 各计 1）+ 每条 GT rib（计 1）。
- 门限：**L2 全集平均 recall ≥0.90**，且**任一 L2 case recall 不得 <0.80**（防平均数掩盖单 case 全崩）。
- 单 loop IoU 门限 0.90（§7.1），rib 门限（§7.2），scale 误差门限 2%（§7.3）——三者同时满足才计召回。

### 8.3 反单矩形冒充（hard fail，任一条触发即整 case FAIL）

1. GT 有 ≥2 个 loop（或 ≥1 rib）而 plan 只有 1 个 outer → FAIL（无论 bbox-IoU 多高）。
2. `ribs==[]` 而 GT rib ≥1 → FAIL。
3. `scale.anchor.type==manual` → L2/L3 直接 FAIL（L1 放行）。
4. 仅上报 bbox-IoU、无 per-loop 明细的 verifier 报告 → 视为 FAIL（报告不合格）。
5. t5 benchmark 必须含**负对照**：故意送单矩形 plan 跑 L2，verifier 必须 FAIL，否则 verifier 实现不合格。

### 8.4 发布门汇总

| 门 | 条件 | 负责人 |
|----|------|--------|
| L1 不退化 | 通过率 ≥ v0.1 基线 −1% | t5 |
| L2 recall | 平均 ≥90%，单 case ≥80% | t5（t2/t3/t4 联调） |
| 反冒充 | §8.3 五条全过，负对照 FAIL | t3 实现，t5 验证 |
| 全绿 | pytest 全过 + DXF/preview/report 产物齐 | t5 |

---

## 9. 自主决策记录（D1–D7，不再提问，直接冻结）

- D1 坐标系：plan 只存 CAD 系（x 右 y 上，mm）；变换由 tracer 做（§4.2）。
- D2 闭合容差：首尾 ≤0.05mm，点数 ≥3，禁自交。
- D3 环绕方向：outer-CCW / hole-CW，verifier 实检。
- D4 兼容：读 v0.1、写 v0.2，升级输入 L2/L3 判不合格。
- D5 scale 选最长可信 OCR 尺寸反推；无尺寸降级 manual+uncertain。
- D6 IoU 门限 0.90、rib 端点 1.0mm/宽度 20%、scale 误差 2%、L2 recall 90%/单 case 80%。
- D7 bbox-IoU 永久降级为 advisory，不参与任何通过判定。

## 10. 下游接口一览

| 任务 | 输入（本 spec） | 输出契约 |
|------|----------------|----------|
| t2 stitch+text-mask | §4.2、§6 | `src/cadcraft/tracing/` 输出 §4 全字段 plan，单测覆 outer/hole/notch/rib+mask |
| t3 executor+verifier | §4、§7、§8.3 | 多实体 DXF + per-loop verifier（含负对照单测） |
| t4 jev+scale | §5 | 同 schema 分类/Jev 返回 + scale solver（有/无 key 同键） |
| t5 bench | §8 | `docs/tracing-benchmark.md` 诚实三级评分 + pytest 全绿 |

---

*本 spec 即 t1 交付：R1–R5 复盘 + v0.2 schema + 验收线。下游按 §10 开工。*
