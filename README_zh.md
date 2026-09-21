# CadCraft（中文）

CadCraft 是一个本地优先的小模型指挥 CAD 工具包（0.5B–4B）。

把自然语言和位图变成**尺寸正确**的 CAD（先 DXF，再 STEP/FreeCAD/AutoCAD）：小模型只写带单位的符号计划（JSON），确定性 Python/Rust 代码负责精确几何，裁判（本地公差检查 + 可选 Jev Score/Choice）负责闭环。

> 思想来源 `Pointer-CAD v2 (ECCV 2026)`：参数推理与几何构建解耦；以及 `TypeSafe Jev`：用便宜、快速、校准过的判断覆盖每一步，而不是一次大生成。

## 为什么做这个

通用大模型画的 CAD 像但尺度不对：`0.7cm` 变成 `0.67`，IoU 还有 `0.96`，零件却报废了。Pointer-CAD v2 用 1.5B 专用模型在顶点/边/面三级精度上超通用大模型 21%+，靠的是：

1. 先规划再构建，参数带单位和符号（`<L1=80mm>`、`<L3=2*L2>`）；
2. 用指针引用参数，不做量化猜值；
3. 不归一化评测，容差取包围盒最小边 1/1000。

CadCraft 是这套思想的工程版：**小模型当包工头，CAD 内核当手，裁判当质检。**

## 四件套路线

- [x] 文本出DXF：文本 → JSON计划 → `ezdxf` → 公差校验 → 自动修 3 轮
- [ ] Jev裁判：Score验收尺寸、Choice分类图元、Noul决定完成/返工 + 上下文压缩
- [ ] 图片描图：OpenCV/LSD + 矢量化 + OCR尺寸 + LLM语义缝合 → DXF
- [ ] AutoCAD/FreeCAD联调：同一份计划驱动 `pyautocad` / FreeCAD headless / CadQuery

详见 [docs/product-plan.md](docs/product-plan.md)。

## 快速开始

```bash
cd ~/work/github/cadcraft-dev/cadcraft
./scripts/bootstrap.sh
ollama pull qwen3:4b

python -m cadcraft "画80x50矩形，中心Φ20孔" -o out.dxf --verify
python examples/text_to_dxf.py --text "100x60矩形，左下角R5圆角" --out /tmp/demo.dxf

export TYPESAFE_API_KEY=...
python examples/jev_verify.py --dxf /tmp/demo.dxf
```

默认纯本地，只有显式 `--with-jev` 才调云端。

## 目录

见英文 README。Rust 核心对标 `markcraft-dev/markcraft` 的 WASM 流程：`cargo` → `wasm-pack` → `wasm/`，Python 可选加速。

## 隐私

图纸默认不出本机，Jev 需显式开 flag 才发请求。见 [SECURITY.md](SECURITY.md)。

## 协议

MIT，见 [LICENSE](LICENSE)。Copyright (c) 2026 Tinker Agora。远端拟为 `tinkeragora/cadcraft`，本地用 `cadcraft-dev/cadcraft` 做分组（对标 `markcraft-dev/markcraft`）。
