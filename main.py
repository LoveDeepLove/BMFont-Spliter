import re
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

from PIL import Image

# 匹配 BMFont 文本格式中的 char 行
char_line_pattern = re.compile(
    r"^char\s+id=(\d+)\s+x=(\d+)\s+y=(\d+)\s+width=(\d+)\s+height=(\d+)\b"
)
invalid_filename_chars = set('<>:"/\\|?*')
reserved_names = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}
cjk_ascii_punctuation_map = {
    ":": "：",
    ",": "，",
    ".": "。",
    ";": "；",
    "?": "？",
    "!": "！",
}


def decode_char_from_id(char_id: int, is_unicode_font: bool) -> str | None:
    """把 BMFont 的 char_id 还原为字符。"""
    if is_unicode_font:
        try:
            return chr(char_id)
        except ValueError:
            return None

    # ANSI 模式：先尝试单字节（ASCII/扩展字符）
    if 0 <= char_id <= 0xFF:
        try:
            return bytes([char_id]).decode("gbk")
        except UnicodeDecodeError:
            return None

    # 兼容部分错误标记为 unicode=0 的字体：char_id 实际直接存的是 Unicode 码点
    try:
        unicode_char = chr(char_id)
        if unicode_char.isprintable() and not unicode_char.isspace():
            return unicode_char
    except ValueError:
        pass

    # ANSI 模式中文常见为双字节编码值
    high = (char_id >> 8) & 0xFF
    low = char_id & 0xFF
    candidates = (
        bytes([high, low]),
        bytes([low, high]),
    )
    for b in candidates:
        try:
            return b.decode("gbk")
        except UnicodeDecodeError:
            continue
    return None


def to_readable_filename(char_id: int, is_unicode_font: bool) -> str:
    """把 char_id 转为可用于文件名的可读形式。"""
    ch = decode_char_from_id(char_id, is_unicode_font)
    if ch is None:
        return f"U+{char_id:04X}"

    # 避免多字符结果导致异常命名（理论上单个 glyph 应对应单个字符）
    if len(ch) != 1:
        return f"U+{char_id:04X}"

    # Windows 文件名不允许的字符，或不可见字符，统一回退到码点格式
    if ch in invalid_filename_chars or ch.isspace() or not ch.isprintable():
        return f"U+{char_id:04X}"
    return ch


def safe_filename_base(name: str, char_id: int) -> str:
    """将字符名清洗为 Windows 可用的文件名基础部分。"""
    # 尽量保留原始字符命名，仅去掉首尾空白
    cleaned = name.strip()
    if not cleaned:
        return f"U+{char_id:04X}"

    if cleaned.upper() in reserved_names:
        return f"{cleaned}_{char_id}"

    return cleaned


def analyze_fnt(fnt_path: Path) -> tuple[bool, bool]:
    """一次性读取 .fnt 文件，返回 (is_unicode_font, is_likely_cjk_font)。"""
    is_unicode = False
    has_cjk = False
    with fnt_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("info "):
                is_unicode = "unicode=1" in stripped
            match = char_line_pattern.match(stripped)
            if match:
                char_id = int(match.group(1))
                if char_id > 255:
                    try:
                        ch = chr(char_id)
                    except ValueError:
                        continue
                    if (
                        ("\u4e00" <= ch <= "\u9fff")
                        or ("\u3400" <= ch <= "\u4dbf")
                        or ("\uf900" <= ch <= "\ufaff")
                    ):
                        has_cjk = True
    return is_unicode, has_cjk


def detect_unicode_flag(fnt_file: Path) -> bool:
    """从 .fnt 头部读取 unicode 标记（兼容旧调用）。"""
    return analyze_fnt(fnt_file)[0]


def is_likely_cjk_font(fnt_path: Path) -> bool:
    """检测字体是否包含较明显的 CJK 码点（兼容旧调用）。"""
    return analyze_fnt(fnt_path)[1]


def split_font_images(
    fnt_path: Path, png_path: Path, output_dir: Path, export_format: str = "png"
) -> int:
    """执行拆图逻辑，返回成功导出的图片数量。"""
    export_format = export_format.lower()
    if export_format not in {"png", "jpg"}:
        raise ValueError("仅支持 png 或 jpg 格式导出。")

    image_format = "PNG" if export_format == "png" else "JPEG"
    is_unicode_font, likely_cjk_font = analyze_fnt(fnt_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_count = 0
    name_counter: dict[str, int] = {}

    with Image.open(png_path) as atlas:
        with fnt_path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                match = char_line_pattern.match(line)
                if not match:
                    continue

                char_id, x, y, width, height = map(int, match.groups())
                if width == 0 or height == 0:
                    continue

                crop_img = atlas.crop((x, y, x + width, y + height))
                if likely_cjk_font and 0 <= char_id <= 0xFF:
                    ascii_char = chr(char_id)
                    if ascii_char in cjk_ascii_punctuation_map:
                        readable_name = cjk_ascii_punctuation_map[ascii_char]
                    else:
                        readable_name = to_readable_filename(char_id, is_unicode_font)
                else:
                    readable_name = to_readable_filename(char_id, is_unicode_font)
                base_name = safe_filename_base(readable_name, char_id)

                # 处理重名，避免覆盖同名字符图
                index = name_counter.get(base_name, 0)
                name_counter[base_name] = index + 1
                if index == 0:
                    filename = f"{base_name}.{export_format}"
                else:
                    filename = f"{base_name}_{index}.{export_format}"

                # 显式指定格式，避免 Pillow 依赖扩展名推断失败
                if image_format == "JPEG" and crop_img.mode in ("RGBA", "LA", "P"):
                    crop_img = crop_img.convert("RGB")
                crop_img.save(output_dir / filename, format=image_format)
                saved_count += 1

    return saved_count


def clear_output_dir(output_dir: Path) -> None:
    """清空输出目录内的所有文件和子目录。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    for item in output_dir.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


class FontSplitterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("BMFont 图片拆分工具")
        self.root.geometry("680x320")
        self.root.resizable(False, False)

        self.fnt_var = tk.StringVar()
        self.png_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.export_format_var = tk.StringVar(value="png")
        self.status_var = tk.StringVar(value="请选择 fnt、png 和输出目录。")

        self._build_ui()

    def _build_ui(self) -> None:
        self._build_row("FNT 文件:", self.fnt_var, self.select_fnt_file, 0)
        self._build_row("PNG 文件:", self.png_var, self.select_png_file, 1)
        self._build_row("输出目录:", self.output_var, self.select_output_dir, 2)
        self._build_output_warning_row(3)
        self._build_format_row(4)

        run_button = ttk.Button(self.root, text="开始拆分", width=15, command=self.run_split)
        run_button.grid(row=5, column=1, padx=10, pady=15, sticky="w")

        status_label = ttk.Label(self.root, textvariable=self.status_var, foreground="blue", anchor="w")
        status_label.grid(row=6, column=0, columnspan=3, padx=10, pady=(0, 10), sticky="we")

        self.root.grid_columnconfigure(1, weight=1)

    def _build_row(self, label_text: str, var: tk.StringVar, browse_cmd, row_idx: int) -> None:
        label = ttk.Label(self.root, text=label_text)
        label.grid(row=row_idx, column=0, padx=10, pady=10, sticky="w")

        entry = ttk.Entry(self.root, textvariable=var, state="readonly", width=60)
        entry.grid(row=row_idx, column=1, padx=10, pady=10, sticky="we")

        browse_button = ttk.Button(self.root, text="浏览", width=10, command=browse_cmd)
        browse_button.grid(row=row_idx, column=2, padx=10, pady=10)

    def _build_output_warning_row(self, row_idx: int) -> None:
        hint = (
            "提示：开始拆分前会先清空所选输出目录下的全部文件与子目录，再写入新图片；"
            "请勿选择含重要数据的文件夹。"
        )
        warn_label = ttk.Label(
            self.root,
            text=hint,
            foreground="#b45309",
            wraplength=620,
            anchor="w",
            justify="left",
        )
        warn_label.grid(row=row_idx, column=0, columnspan=3, padx=10, pady=(0, 6), sticky="we")

    def _build_format_row(self, row_idx: int) -> None:
        label = ttk.Label(self.root, text="导出格式:")
        label.grid(row=row_idx, column=0, padx=10, pady=10, sticky="w")

        frame = ttk.Frame(self.root)
        frame.grid(row=row_idx, column=1, padx=10, pady=10, sticky="w")

        png_radio = ttk.Radiobutton(frame, text="PNG", value="png", variable=self.export_format_var)
        png_radio.pack(side="left")

        jpg_radio = ttk.Radiobutton(frame, text="JPG", value="jpg", variable=self.export_format_var)
        jpg_radio.pack(side="left", padx=(16, 0))

    def select_fnt_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 FNT 文件",
            filetypes=[("FNT 文件", "*.fnt"), ("所有文件", "*.*")],
        )
        if path:
            self.fnt_var.set(path)

    def select_png_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 PNG 文件",
            filetypes=[("PNG 图片", "*.png"), ("所有文件", "*.*")],
        )
        if path:
            self.png_var.set(path)

    def select_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_var.set(path)

    def run_split(self) -> None:
        fnt_value = self.fnt_var.get().strip()
        png_value = self.png_var.get().strip()
        output_value = self.output_var.get().strip()
        export_format = self.export_format_var.get().strip().lower()

        if not fnt_value or not png_value or not output_value:
            messagebox.showwarning("参数不完整", "请先选择 fnt 文件、png 文件和输出目录。")
            return

        fnt_path = Path(fnt_value)
        png_path = Path(png_value)
        output_dir = Path(output_value)

        if not fnt_path.is_file():
            messagebox.showerror("文件不存在", "fnt 文件路径无效。")
            return
        if not png_path.is_file():
            messagebox.showerror("文件不存在", "png 文件路径无效。")
            return

        try:
            clear_output_dir(output_dir)
            count = split_font_images(fnt_path, png_path, output_dir, export_format)
        except Exception as e:
            messagebox.showerror("执行失败", f"拆分失败：{e}")
            self.status_var.set("执行失败，请检查文件格式和路径。")
            return

        self.status_var.set(f"执行完成，已清空旧文件并导出 {count} 张 {export_format.upper()} 图片。")
        messagebox.showinfo("完成", f"拆分完成，已清空旧文件并导出 {count} 张 {export_format.upper()} 图片。")


def main() -> None:
    root = tk.Tk()
    app = FontSplitterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()