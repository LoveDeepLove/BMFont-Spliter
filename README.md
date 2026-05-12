# BMFont 图片拆分工具

基于 Python 与 Pillow 的桌面小工具：将 **BMFont 文本格式**（`.fnt`）与配套位图（`.png`）中的每个字符区域裁剪为独立图片，并尽量用**可读字符**作为文件名（含中文、全角标点等场景的兼容处理）。

## 功能特性

- **图形界面**：选择 `.fnt`、位图 `.png`、输出目录；支持导出 **PNG** 或 **JPG**（默认 PNG）。
- **字符命名**：根据 `char id` 还原为文件名；兼容 `unicode=0/1`、ANSI/GBK 双字节、以及「标为 ANSI 但实际为 Unicode 码点」的字体。
- **中文标点**：在检测到 CJK 字体时，将常见 ASCII 标点映射为全角（如 `:` → `：`），便于与中文 UI 资源对应。
- **安全命名**：Windows 非法字符、保留设备名等会回退或加后缀；同名自动 `xxx_1.jpg` 避免覆盖。
- **输出前清空**：开始拆分前会**清空所选输出目录下的全部文件与子目录**（界面内有醒目提示，请勿选择含重要数据的文件夹）。
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

3. 在界面中依次选择：
   - **FNT 文件**：BMFont **文本**格式 `.fnt`（非 XML/二进制 `.fnt`）。
   - **PNG 文件**：与 `.fnt` 中 `page` 行引用的图集一致（通常为同名字体图）。
   - **输出目录**：仅用于本次导出；**会先被清空再写入**。
4. 选择导出格式 **PNG** 或 **JPG**，点击 **开始拆分**。

宽度或高度为 `0` 的字符（如空格占位）会被跳过，不生成图片。

## 支持的字体描述格式

当前解析逻辑针对 BMFont **文本** `.fnt` 中形如：

```text
char  id=48  x=...  y=...  width=...  height=...
```

的行。若你的 `.fnt` 为 **XML** 或 **二进制** 格式，需先用 BMFont 等工具导出为文本格式，或自行扩展解析代码。

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
├── main.py           # 主程序（GUI + 拆分逻辑）
├── 打包脚本.bat      # Windows 一键打包（交互输入版本号）
├── requirements.txt  # Python 依赖
└── README.md
```

## 注意事项

- **输出目录会被清空**：请专门新建空文件夹作为输出目录，勿指向桌面、文档根目录等。
- **JPG 无透明通道**：带 Alpha 的图块导出 JPG 时会转为 RGB，可能与 PNG 观感不同。
- 文件名尽量贴近「字符含义」，极端情况下仍会使用 `U+XXXX` 等形式以保证可写、不冲突。

## 开源协议

若上传到 GitHub，请根据你的意愿补充 **LICENSE** 文件（例如 MIT、Apache-2.0 等）。本 README 不包含法律意义上的许可条款。

---

如有问题或改进建议，欢迎通过 Issue / PR 交流。
