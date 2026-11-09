# 字体图集工具（拆分 / 打包）

基于 Python 与 Pillow 的桌面小工具，支持**双向**处理位图字体：

- **拆分**：字体描述文件 + 图集 → 每个字符一张独立图片
- **打包**：一组散图 → 图集 + 字体描述文件

字体描述文件支持 **BMFont 文本格式 `.fnt`** 与 **Unity `Custom Font` 资源 `.fontsettings`** 两种。

## 功能特性

- **双标签页**：`拆分：字体 → 图片` / `打包：图片 → 字体`，互不干扰。
- **图形界面**：拆分支持导出 **PNG** 或 **JPG**（默认 PNG）。
- **两种描述格式**：自动按文件内容识别 `.fnt`（BMFont 文本）与 `.fontsettings`（Unity 文本序列化字体），无需手动切换格式。
- **打包输出**：MaxRects 装箱生成 2 的幂图集，可同时输出 `.fnt` 与 `.fontsettings`，字段与主流 BMFont 工具一致。
- **字符命名**：根据 `char id` 还原为文件名；兼容 `unicode=0/1`、ANSI/GBK 双字节、以及「标为 ANSI 但实际为 Unicode 码点」的字体。
- **中文标点**：在检测到 CJK 字体时，将常见 ASCII 标点映射为全角（如 `:` → `：`），便于与中文 UI 资源对应。
- **安全命名**：Windows 非法字符、保留设备名等会回退或加后缀；同名自动 `xxx_1.jpg` 避免覆盖。
- **输出前清空**：拆分前会**清空所选输出目录下的全部文件与子目录**（界面内有醒目提示，请勿选择含重要数据的文件夹）；打包只覆盖同名文件。
- **打包脚本**：同目录下 `打包脚本.bat` 可一键 PyInstaller 打包，并支持自定义版本号与 exe 名称。

## 环境要求

- **Python** 3.10+（使用了 `str | None` 等类型标注语法）
- **Pillow**（`PIL`）
- **tkinter**：Windows 官方 Python 安装通常已自带；若缺失需按系统安装 Tcl/Tk 或使用完整安装包。

## 安装依赖

```bash
pip install -r requirements.txt
```

或：

```bash
pip install Pillow
```

## 使用方法

1. 克隆或下载本仓库。
2. 安装依赖后，在项目根目录执行：

   ```bash
   python main.py
   ```

### 拆分：字体 → 图片

在「拆分」页依次选择：

- **字体描述文件**：BMFont **文本**格式 `.fnt`，或 Unity 文本序列化的 `.fontsettings`。
- **PNG 文件**：与之配套的图集（`.fnt` 对应 `page` 行引用的图；`.fontsettings` 对应 `m_DefaultMaterial` 所用材质里的贴图，通常为同名字体图）。
- **输出目录**：仅用于本次导出；**会先被清空再写入**。

再选择导出格式 **PNG** 或 **JPG**，点击 **开始拆分**。

宽度或高度为 `0` 的字符（如空格占位、以及 Unity 字体中未配置的槽位）会被跳过，不生成图片。

### 打包：图片 → 字体

在「打包」页：

1. **散图目录**：存放每字符一张图，**文件名即字符**：
   - `万.png` → U+4E07，`A.png` → U+0041
   - `U+4E07.png` / `uni4E07.png` / `0x4E07.png` 亦可
   - 多字符文件名（如 `地主.png`）按首字符处理，并给出提示
2. **输出目录**：写入 `<字体名>.png` 及所选描述文件，**同名文件会被覆盖**（不会清空目录）。
3. **字体名称**：决定输出文件名，也是 `.fnt` 的 `face` 与 `.fontsettings` 的 `m_Name`。
4. **空格宽度 / 行高**：留空则自动取「最宽图宽」与「最高图高」。
5. **输出文件**：可勾选 `.fnt`、`.fontsettings`（可同时输出）。
6. **Unity 模板**（可选）：建议选择同目录下现有的 `.fontsettings`，用于沿用引擎自定义的 YAML 头、`serializedVersion` 与材质引用。

图集尺寸按总面积推导 2 的幂（如 256×256、512×256），放不下时自动翻倍；每格图四周留 1px 空白（共 2px 间隔），并换算为 `xoffset/yoffset`。

生成规则（与常见 BMFont 工具保持一致）：

```text
info face="<字体名>" size=0 ... charset="ANSI" unicode=0
common lineHeight=<行高> base=0 scaleW=<图宽> scaleH=<图高> pages=1 packed=0
page id=0 file="<字体名>.png"
chars count=<字形数 + 1>
char id=32 ... xadvance=<空格宽度>       # 自动补一个空格
char id=<字符编码> x/y/width/height ... xoffset=1 yoffset=1 xadvance=<图宽>
```

`.fontsettings` 的 `uv` 由图集像素坐标归一化并**翻转 Y 轴**得到，`vert.y = 图高`、`vert.height = -图高`，`advance = 图宽`。

> 打包 → 拆分已做像素级往返验证：同一批散图打包后再拆回，与原始图片逐像素一致。

## 支持的字体描述格式

### 1. BMFont 文本 `.fnt`

针对形如：

```text
char  id=48  x=...  y=...  width=...  height=...
```

的行。若你的 `.fnt` 为 **XML** 或 **二进制** 格式，需先用 BMFont 等工具导出为文本格式。

### 2. Unity `.fontsettings`

即 Unity 在 `Assets` 下创建的 Custom Font 资源（Inspector 中的 `Character Rects`），解析其中每个字符的：

| 字段 | 用途 |
|---|---|
| `index` | 字符编码（Unicode 码点） |
| `uv.x / uv.y / uv.width / uv.height` | 归一化 UV（**原点在左下，Y 轴向上**） |
| `vert.width / vert.height` | 像素尺寸（`height` 通常为负数，取绝对值） |
| `flipped` | 该字形在纹理中是否上下翻转，导出时会自动翻正 |

UV 到像素坐标的换算（`W/H` 为图集尺寸）为：

```text
x = uv.x * W
y = H - (uv.y + uv.height) * H
w = uv.width  * W
h = uv.height * H
```

前提是该文件为 **文本** 序列化格式（用记事本可看到 `%YAML`、`m_CharacterRects`）。
若打开是乱码（二进制），请在 Unity 中把 `Project Settings → Editor → Asset Serialization`
改为 **Force Text** 后重新导入，工具会给出明确提示。

## Windows 打包为可执行文件

### 方式一：使用仓库内脚本（推荐）

双击运行 **`打包脚本.bat`**，按提示输入版本号。脚本会调用 PyInstaller，生成：

`dist\BMFont拆分工具v{版本号}.exe`

首次使用前请确保已安装 PyInstaller：

```bash
pip install pyinstaller
```

### 方式二：命令行手动打包

```bash
pyinstaller --noconfirm --clean --onefile --windowed -n "BMFont拆分工具v1.0.0" main.py
```

将 `-n` 后的名称改为你需要的 exe 名称即可；**无需**重命名 `main.py`。

## 项目结构（简要）

```text
.
├── main.py           # 主程序（GUI + 拆分 / 打包逻辑）
├── 打包脚本.bat      # Windows 一键打包（交互输入版本号）
├── requirements.txt  # Python 依赖
└── README.md
```

## 注意事项

- **拆分**会清空输出目录：请专门新建空文件夹，勿指向桌面、文档根目录等。
- **打包**只覆盖同名文件，不会清空目录。
- **JPG 无透明通道**：带 Alpha 的图块导出 JPG 时会转为 RGB，可能与 PNG 观感不同。
- 文件名尽量贴近「字符含义」，极端情况下仍会使用 `U+XXXX` 等形式以保证可写、不冲突。
- `.fontsettings` 打包时若未指定模板，`m_DefaultMaterial` 为空，需要进 Unity 手动指定材质；引擎使用了自定义 `%TAG`（如 `tag:yousandi.cn,2023`）时**必须**选择现有 `.fontsettings` 作模板。
- 工具的 `.meta` 文件不由本工具生成，交给 Unity 导入时自动创建。

## 开源协议

若上传到 GitHub，请根据你的意愿补充 **LICENSE** 文件（例如 MIT、Apache-2.0 等）。本 README 不包含法律意义上的许可条款。

---

如有问题或改进建议，欢迎通过 Issue / PR 交流。
